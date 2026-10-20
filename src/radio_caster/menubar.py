"""Radio Caster: menu bar app for casting internet radio to a Chromecast.

The menu gives quick access to favourites; the main window (window.py) adds
search, favourites management and playback controls.
Favourites come from ~/.config/radio-caster/stations.json (see core.py).
"""

import subprocess
import threading
import time

import AppKit
import pychromecast
import rumps
import zeroconf
from PyObjCTools.AppHelper import callAfter
from pychromecast.config import APP_MEDIA_RECEIVER
from pychromecast.discovery import CastBrowser, SimpleCastListener

from . import launcher
from .core import (
    CONFIG,
    add_favourite,
    describe,
    icon_file,
    load_favourites,
    load_settings,
    now_playing,
    play,
    remove_favourite,
    save_setting,
    search_directory,
)
from .window import MainWindow, install_edit_menu

ICON = "📻"
POLL_SECONDS = 15


class RadioApp(rumps.App):
    def __init__(self, device=None):
        super().__init__("Radio Caster", title=ICON, quit_button=None)
        self.cast = None  # the connected speaker
        self.speaker = device or load_settings().get("speaker")  # preferred speaker's name, if chosen
        self.devices = {}  # name -> CastInfo of every speaker on the network
        self.connecting = None  # CastInfo of a speaker being connected to
        self.move_station = None  # Station to carry over to the next speaker (Spotify-style switch)
        self.favourites = []
        self.config_mtime = None
        self.last_played = None  # so stations played from search results are recognised too
        self.playing = None  # Station, maintained by refresh() from the cast status
        self.info = None  # NowPlaying of self.playing, maintained by the poll thread
        self.station_changed = threading.Event()  # wakes the poll thread early
        self.volume = None  # 0-100, maintained by refresh()
        self.volume_touched = 0  # monotonic time of the last change made here, see refresh()
        self.volume_lock = threading.Lock()
        self.pending_volume = None  # latest slider value not yet sent to the speaker
        self.starting = None  # Station being started, until the speaker reports it playing
        self.error = None
        self.icons = {}  # icon URL -> local file, filled in the background
        self.search = {"query": "", "busy": False, "error": None}
        self.results = []  # SearchResults from the last directory search
        self.window = None  # created on first open

        self.load_config()
        self.zconf = zeroconf.Zeroconf()
        changed = lambda *_: callAfter(self.on_devices_changed)  # noqa: E731 - discovery runs on its own thread
        self.browser = CastBrowser(SimpleCastListener(changed, changed, changed), self.zconf)
        self.browser.start_discovery()
        threading.Thread(target=self.poll_now_playing, daemon=True).start()
        rumps.Timer(self.refresh, 2).start()

    # --- Menu -----------------------------------------------------------------

    def load_config(self):
        self.favourites = load_favourites()
        self.config_mtime = CONFIG.stat().st_mtime
        self.fetch_icons(self.favourites)
        self.build_menu()

    def build_menu(self):
        self.song_item = rumps.MenuItem("Nothing playing")
        self.show_item = rumps.MenuItem(" ")
        self.station_items = {s.id: rumps.MenuItem(s.name, callback=self.on_station) for s in self.favourites}
        self.volume_item = rumps.MenuItem(self.volume_title())
        self.volume_slider = volume_slider(self.volume or 0, self.on_volume)
        self.speaker_menu = rumps.MenuItem(self.speaker_title())
        for name, info in self.sorted_devices():
            item = rumps.MenuItem(
                f"{name} (group)" if info.cast_type == "group" else name,
                callback=lambda _, n=name: self.select_speaker(n),
            )
            item.state = int(self.cast is not None and self.cast.cast_info.friendly_name == name)
            self.speaker_menu.add(item)

        self.menu.clear()
        self.menu = [
            self.song_item,
            self.show_item,
            None,
            *self.station_items.values(),
            None,
            rumps.MenuItem("Open Radio Caster…", callback=lambda _: self.open_window(), key="o"),
            rumps.MenuItem("Find Stations…", callback=lambda _: self.open_window(focus_search=True), key="f"),
            None,
            rumps.MenuItem("Stop", callback=lambda _: self.stop()),
            self.volume_item,
            self.volume_slider,
            None,
            self.speaker_menu,
            None,
            rumps.MenuItem("Quit Radio Caster", callback=rumps.quit_application, key="q"),
        ]

    def volume_title(self):
        return "Volume" if self.volume is None else f"Volume: {self.volume}%"

    def speaker_title(self):
        if self.connecting:
            return f"Speaker: connecting to {self.connecting.friendly_name}…"
        if self.cast:
            return f"Speaker: {self.cast.cast_info.friendly_name}"
        if self.speaker:
            return f"Speaker: looking for {self.speaker}…"
        return "Speaker: looking…"

    def sorted_devices(self):
        """Speakers first, then groups, each alphabetically."""
        return sorted(self.devices.items(), key=lambda kv: (kv[1].cast_type == "group", kv[0].casefold()))

    # --- Speakers -------------------------------------------------------------

    def on_devices_changed(self):
        self.devices = {
            info.friendly_name: info for info in list(self.browser.devices.values()) if info.friendly_name
        }
        self.ensure_connected()
        self.build_menu()
        self.push_state()

    def ensure_connected(self):
        """Connect to the preferred speaker (or any, if none chosen) when not already on it."""
        if self.connecting:
            return  # connect_to() calls back here when done
        if self.speaker:
            target = self.devices.get(self.speaker)  # wait for it rather than falling back to another
        elif self.cast:
            return
        else:
            target = next((info for _, info in self.sorted_devices()), None)
        if target and not (self.cast and self.cast.uuid == target.uuid):
            self.connect_to(target)

    def select_speaker(self, name):
        if self.cast and self.cast.cast_info.friendly_name == name:
            return
        self.speaker = name
        save_setting("speaker", name)
        self.move_station = self.move_station or self.playing
        self.ensure_connected()
        self.build_menu()
        self.push_state()

    def connect_to(self, info):
        self.connecting = info
        old = self.cast
        station = self.move_station

        def go():
            try:
                cast = pychromecast.get_chromecast_from_cast_info(info, self.zconf)
                cast.wait(timeout=10)
                if station:
                    play(cast, station)  # start on the new speaker first, so the gap is short
                error = None
            except Exception as e:
                cast, error = None, f"Couldn't connect to {info.friendly_name}: {e}"

            def done():
                self.connecting = None
                self.error = error
                if cast:
                    self.cast = cast
                    if self.move_station == station:
                        self.move_station = None
                self.ensure_connected()  # the choice may have changed meanwhile
                self.build_menu()
                self.push_state()

            callAfter(done)
            if cast and old:
                try:
                    if station:
                        old.quit_app()
                    old.disconnect(timeout=5)
                except Exception:
                    pass  # the old speaker may already be gone

        self.build_menu()
        threading.Thread(target=go, daemon=True).start()

    # --- Window ---------------------------------------------------------------

    def open_window(self, focus_search=False):
        if self.window is None:
            self.window = MainWindow(self.on_window_message)
        self.window.show(focus_search)
        self.push_state()

    def push_state(self):
        if self.window is None or not self.window.visible:
            return
        favourite_streams = {s.stream for s in self.favourites}
        playing = self.playing
        self.window.render(
            {
                "speaker": self.cast.cast_info.friendly_name if self.cast else None,
                "wanted_speaker": self.speaker,
                "connecting": self.connecting.friendly_name if self.connecting else None,
                "speakers": [
                    {"name": name, "group": info.cast_type == "group"} for name, info in self.sorted_devices()
                ],
                "volume": self.volume,
                "starting": self.starting.name if self.starting else None,
                "error": self.error,
                "playing": playing
                and {
                    "name": playing.name,
                    "stream": playing.stream,
                    "artwork": playing.artwork or playing.icon,
                    "song": describe(self.info),
                    "show": self.info and self.info.show,
                },
                "favourites": [{"id": s.id, "name": s.name, "icon": s.icon, "stream": s.stream} for s in self.favourites],
                "search": {
                    **self.search,
                    "results": [
                        {
                            "name": r.name,
                            "country": r.country,
                            "icon": r.icon,
                            "variants": [
                                {
                                    "label": v.label,
                                    "stream": v.station.stream,
                                    "favourite": v.station.stream in favourite_streams,
                                }
                                for v in r.variants
                            ],
                        }
                        for r in self.results
                    ],
                },
            }
        )

    def on_window_message(self, msg):
        # Called on the main thread by the web view.
        action = msg.get("action")
        if action == "ready":
            self.window.page_ready()
        elif action == "play_favourite":
            station = next((s for s in self.favourites if s.id == msg["id"]), None)
            if station:
                self.start(station)
        elif action == "play_result":
            self.start(self.results[msg["index"]].variants[msg["variant"]].station)
        elif action == "add_result":
            station = self.results[msg["index"]].variants[msg["variant"]].station
            if station.stream not in {s.stream for s in self.favourites}:
                add_favourite(station)
                self.load_config()
        elif action == "remove":
            remove_favourite(msg["id"])
            self.load_config()
        elif action == "search":
            self.start_search(msg["query"])
        elif action == "stop":
            self.stop()
        elif action == "volume":
            self.set_volume(msg["value"])
        elif action == "speaker":
            self.select_speaker(msg["name"])
        elif action == "edit_file":
            subprocess.run(["open", "-t", str(CONFIG)])
        self.push_state()

    # --- Background work --------------------------------------------------------

    def poll_now_playing(self):
        while True:
            station = self.playing
            info = now_playing(station) if station else None
            if station == self.playing:
                self.info = info
                callAfter(self.push_state)
            self.station_changed.wait(POLL_SECONDS)
            self.station_changed.clear()

    def fetch_icons(self, stations):
        def go():
            for s in stations:
                if s.icon and s.icon not in self.icons:
                    self.icons[s.icon] = icon_file(s.icon)

        threading.Thread(target=go, daemon=True).start()

    def start_search(self, query):
        self.search = {"query": query, "busy": True, "error": None}
        self.results = []

        def go():
            try:
                results, error = search_directory(query), None
            except OSError as e:
                results, error = [], str(e)

            def done():
                if self.search["query"] == query:  # ignore an older search finishing late
                    self.results = results
                    self.search = {"query": query, "busy": False, "error": error}
                    self.push_state()

            callAfter(done)

        threading.Thread(target=go, daemon=True).start()

    def in_background(self, fn):
        if self.cast is None:
            self.error = "No speaker found yet."
            rumps.notification("Radio Caster", "", "No Chromecast connected yet.")
            return
        threading.Thread(target=fn, daemon=True).start()

    # --- Actions ------------------------------------------------------------------

    def start(self, station):
        self.last_played = station
        self.starting = station
        self.error = None
        self.fetch_icons([station])

        def go():
            try:
                play(self.cast, station)
                error = None
            except Exception as e:  # shown in the window instead of killing the thread silently
                error = f"Couldn't play {station.name}: {e}"

            def done():
                if self.starting == station:
                    self.starting = None
                self.error = error
                self.push_state()

            callAfter(done)

        self.in_background(go)

    def stop(self):
        self.in_background(lambda: self.cast.quit_app())

    def set_volume(self, percent):
        # Dragging the slider fires many changes; one thread sends the latest until it catches up.
        if self.cast is None:
            self.in_background(None)  # reports there's no speaker
            return
        self.volume = percent
        self.volume_touched = time.monotonic()
        self.volume_item.title = self.volume_title()
        self.volume_slider.value = percent  # when changed from the window
        with self.volume_lock:
            already_sending = self.pending_volume is not None
            self.pending_volume = percent
        if already_sending:
            return

        def send():
            while True:
                with self.volume_lock:
                    percent = self.pending_volume
                try:
                    self.cast.set_volume(percent / 100)
                finally:
                    with self.volume_lock:
                        if self.pending_volume == percent:
                            self.pending_volume = None
                            return

        self.in_background(send)

    def on_station(self, sender):
        self.start(next(s for s in self.favourites if self.station_items[s.id] is sender))

    def on_volume(self, sender):
        percent = round(sender.value)
        if percent != self.volume:
            self.set_volume(percent)

    # --- Status -------------------------------------------------------------------

    def refresh(self, _):
        # Runs on the main thread, so it's safe to touch the menu here.
        if CONFIG.exists() and CONFIG.stat().st_mtime != self.config_mtime:
            self.load_config()  # stations file was edited by hand
        self.speaker_menu.title = self.speaker_title()
        if self.cast is None:
            self.push_state()
            return

        mc = self.cast.media_controller.status
        active = self.cast.app_id == APP_MEDIA_RECEIVER and mc.player_state in ("PLAYING", "BUFFERING")
        candidates = [*self.favourites, *([self.last_played] if self.last_played else [])]
        playing = next((s for s in candidates if active and mc.content_id == s.stream), None)
        for s in self.favourites:
            self.station_items[s.id].state = int(playing is not None and playing.stream == s.stream)
        if playing != self.playing:
            self.info = None
            self.station_changed.set()
        self.playing = playing
        if playing and self.starting and playing.stream == self.starting.stream:
            self.starting = None

        icon = playing and self.icons.get(playing.icon)
        if icon:
            self.icon = str(icon)
            self.title = None
        else:
            self.icon = None
            self.title = ICON

        info = self.info
        if playing:
            self.song_item.title = f"♪ {describe(info) or '…'}"
            self.show_item.title = (info and info.show) or playing.name
        else:
            self.song_item.title = "Nothing playing"
            self.show_item.title = " "

        # The speaker reports a change made here a moment later, so don't jump the slider back meanwhile.
        if self.cast.status and time.monotonic() - self.volume_touched > 3:
            self.volume = round((self.cast.status.volume_level or 0) * 100)
            self.volume_slider.value = self.volume
        self.volume_item.title = self.volume_title()

        self.push_state()


def volume_slider(value, callback):
    """A slider inside the menu, inset to line up with the item titles."""
    item = rumps.SliderMenuItem(value=value, min_value=0, max_value=100, callback=callback, dimensions=(200, 22))
    slider = item._slider
    container = AppKit.NSView.alloc().initWithFrame_(((0, 0), (245, 26)))
    item._menuitem.setView_(container)  # first: replacing the view detaches the old one (the slider)
    slider.setFrameOrigin_((25, 2))
    container.addSubview_(slider)
    return item


def run(device=None):
    app = RadioApp(device)
    app.observer = launcher.listen(app.open_window)
    app.lock = launcher.acquire_lock()  # after listen(), so `radio-caster open` never finds it deaf
    if app.lock is None:
        print("Radio Caster is already running.")
        return
    if launcher.take_window_request():
        callAfter(app.open_window)
    # Menu bar only, no Dock icon.
    AppKit.NSApplication.sharedApplication().setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    install_edit_menu()
    app.run()
