"""Radio Caster: menu bar app for casting internet radio to a Chromecast.

Favourites come from ~/.config/radio-caster/stations.json (see core.py).
"""

import subprocess
import threading
import time

import AppKit
import pychromecast
import rumps
from pychromecast.config import APP_MEDIA_RECEIVER

from .core import (
    CONFIG,
    add_favourite,
    describe,
    icon_file,
    load_favourites,
    now_playing,
    play,
    remove_favourite,
    search_directory,
)

ICON = "📻"
POLL_SECONDS = 15


class RadioApp(rumps.App):
    def __init__(self, device=None):
        super().__init__("Radio Caster", title=ICON, quit_button=None)
        self.cast = None
        self.device = device
        self.favourites = []
        self.config_mtime = None
        self.results = []  # (Station, details) from the last directory search
        self.last_played = None  # so stations played from search results are recognised too
        self.playing = None  # Station, maintained by refresh() from the cast status
        self.info = None  # NowPlaying of self.playing, maintained by the poll thread
        self.icons = {}  # icon URL -> local file, filled in the background

        self.load_config()
        threading.Thread(target=self.connect, daemon=True).start()
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

        results_menu = rumps.MenuItem("Search results")
        seen = set()
        for station, details in self.results:
            title = f"{station.name}  ({details})" if details else station.name
            while title in seen:  # the directory has many near-duplicates
                title += " "
            seen.add(title)
            entry = rumps.MenuItem(title)
            entry.add(rumps.MenuItem("Play", callback=lambda _, s=station: self.start(s)))
            entry.add(rumps.MenuItem("Add to favourites", callback=lambda _, s=station: self.on_add(s)))
            results_menu.add(entry)

        remove_menu = rumps.MenuItem("Remove from favourites")
        for s in self.favourites:
            remove_menu.add(rumps.MenuItem(s.name, callback=lambda _, s=s: self.on_remove(s)))

        self.volume_menu = rumps.MenuItem("Volume")
        for v in range(10, 101, 10):
            self.volume_menu.add(rumps.MenuItem(f"{v}%", callback=self.on_volume))
        self.device_item = rumps.MenuItem(
            f"Device: {self.cast.cast_info.friendly_name}" if self.cast else "Searching for Chromecast…"
        )

        self.menu.clear()
        self.menu = [
            self.song_item,
            self.show_item,
            None,
            *self.station_items.values(),
            None,
            rumps.MenuItem("Search stations…", callback=self.on_search),
            *([results_menu] if self.results else []),
            remove_menu,
            rumps.MenuItem("Edit stations file…", callback=lambda _: subprocess.run(["open", "-t", str(CONFIG)])),
            None,
            rumps.MenuItem("Stop", callback=self.on_stop),
            self.volume_menu,
            None,
            self.device_item,
            rumps.MenuItem("Quit", callback=rumps.quit_application),
        ]

    # --- Background work --------------------------------------------------------

    def connect(self):
        while self.cast is None:
            if self.device:
                casts, browser = pychromecast.get_listed_chromecasts(friendly_names=[self.device], timeout=10)
            else:
                casts, browser = pychromecast.get_chromecasts(timeout=10)
            if casts:
                # Keep the browser running: the cast connection uses it to (re)resolve the device.
                casts[0].wait()
                self.cast = casts[0]
            else:
                browser.stop_discovery()
                time.sleep(30)

    def poll_now_playing(self):
        while True:
            station = self.playing
            info = now_playing(station) if station else None
            if station == self.playing:
                self.info = info
            time.sleep(POLL_SECONDS)

    def fetch_icons(self, stations):
        def go():
            for s in stations:
                if s.icon and s.icon not in self.icons:
                    self.icons[s.icon] = icon_file(s.icon)

        threading.Thread(target=go, daemon=True).start()

    def in_background(self, fn):
        if self.cast is None:
            rumps.notification("Radio Caster", "", "No Chromecast connected yet.")
            return
        threading.Thread(target=fn, daemon=True).start()

    # --- Actions ------------------------------------------------------------------

    def start(self, station):
        self.last_played = station
        self.fetch_icons([station])
        self.in_background(lambda: play(self.cast, station))

    def on_station(self, sender):
        self.start(next(s for s in self.favourites if self.station_items[s.id] is sender))

    def on_search(self, _):
        AppKit.NSApp.activateIgnoringOtherApps_(True)
        response = rumps.Window(
            "Station name (searches radio-browser.info):",
            "Search stations",
            ok="Search",
            cancel="Cancel",
            dimensions=(280, 24),
        ).run()
        query = response.text.strip()
        if not response.clicked or not query:
            return
        try:
            self.results = search_directory(query)
        except OSError as e:
            rumps.notification("Radio Caster", "Search failed", str(e))
            return
        if not self.results:
            rumps.notification("Radio Caster", "", f"No stations found for “{query}”.")
        self.build_menu()

    def on_add(self, station):
        add_favourite(station)
        self.load_config()

    def on_remove(self, station):
        if rumps.alert(f"Remove {station.name} from favourites?", ok="Remove", cancel="Cancel"):
            remove_favourite(station.id)
            self.load_config()

    def on_stop(self, _):
        self.in_background(lambda: self.cast.quit_app())

    def on_volume(self, sender):
        level = int(sender.title.rstrip("%")) / 100
        self.in_background(lambda: self.cast.set_volume(level))

    # --- Status -------------------------------------------------------------------

    def refresh(self, _):
        # Runs on the main thread, so it's safe to touch the menu here.
        if CONFIG.exists() and CONFIG.stat().st_mtime != self.config_mtime:
            self.load_config()  # stations file was edited by hand
        if self.cast is None:
            return
        self.device_item.title = f"Device: {self.cast.cast_info.friendly_name}"

        mc = self.cast.media_controller.status
        active = self.cast.app_id == APP_MEDIA_RECEIVER and mc.player_state in ("PLAYING", "BUFFERING")
        candidates = [*self.favourites, *([self.last_played] if self.last_played else [])]
        playing = next((s for s in candidates if active and mc.content_id == s.stream), None)
        for s in self.favourites:
            self.station_items[s.id].state = int(playing is not None and playing.stream == s.stream)
        if playing != self.playing:
            self.info = None
        self.playing = playing

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

        volume = round((self.cast.status.volume_level or 0) * 10) * 10 if self.cast.status else None
        for item in self.volume_menu.values():
            item.state = int(item.title == f"{volume}%")


def run(device=None):
    app = RadioApp(device)
    # Menu bar only, no Dock icon.
    AppKit.NSApplication.sharedApplication().setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    app.run()
