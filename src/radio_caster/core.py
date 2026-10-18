"""Stations, favourites, directory search, now-playing info and casting."""

import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

import pychromecast

CONFIG = Path.home() / ".config" / "radio-caster" / "stations.json"
ICON_CACHE = Path.home() / "Library" / "Caches" / "radio-caster" / "icons"
DIRECTORY_API = "https://de1.api.radio-browser.info/json"
USER_AGENT = "RadioCaster/1.0"
METADATA_TYPE_MUSIC_TRACK = 3


@dataclass(frozen=True)
class NowPlaying:
    artist: str | None = None
    song: str | None = None
    show: str | None = None


@dataclass(frozen=True)
class Station:
    id: str
    name: str
    stream: str
    artwork: str = ""  # shown on the speaker's display
    tagline: str = ""  # second line on the speaker's display
    icon: str = ""  # small image for the menu bar
    now_playing: str = "icy"  # "radio357", "nowyswiat" or "icy" (song info from the stream itself)
    content_type: str = "audio/mpeg"


DEFAULT_FAVOURITES = [
    Station(
        id="357",
        name="Radio 357",
        stream="https://stream.radio357.pl/",
        artwork="https://media.radio357.pl/2022/10/8d70285b-a620-4452-9fa5-2b6946e8e82b.jpg"
        "?auto=format%2Ccompress&fit=crop&crop=faces%2Ctop&w=660&ar=1:1",
        tagline="Najlepszy radiowy adres na świecie!",
        icon="https://radio357.pl/wp-content/themes/customTpl/img/apple-touch-icon.png",
        now_playing="radio357",
    ),
    Station(
        id="ns",
        name="Radio Nowy Świat",
        stream="https://stream.nowyswiat.online/mp3",
        # Their app sends no artwork; this is the web player's default cover.
        artwork="https://nowyswiat.online/assets/images/cover-default.png",
        tagline="PION I POZIOM!",
        icon="https://nowyswiat.online/assets/favicons/apple-icon-180x180.png",
        now_playing="nowyswiat",
    ),
]


# --- Favourites ---------------------------------------------------------------


def load_favourites():
    if not CONFIG.exists():
        save_favourites(DEFAULT_FAVOURITES)
    data = json.loads(CONFIG.read_text())
    return [Station(**s) for s in data["favourites"]]


def save_favourites(stations):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    data = {"favourites": [asdict(s) for s in stations]}
    CONFIG.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def add_favourite(station):
    favourites = load_favourites()
    ids = {s.id for s in favourites}
    base = slug = re.sub(r"[^a-z0-9]+", "-", station.name.casefold()).strip("-") or "station"
    n = 2
    while slug in ids:
        slug, n = f"{base}-{n}", n + 1
    station = Station(**{**asdict(station), "id": slug})
    save_favourites([*favourites, station])
    return station


def remove_favourite(station_id):
    save_favourites([s for s in load_favourites() if s.id != station_id])


# --- Directory ----------------------------------------------------------------


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.load(r)


def search_directory(query, limit=15):
    """Stations from radio-browser.info, most popular first."""
    params = urllib.parse.urlencode(
        {"name": query, "limit": limit, "hidebroken": "true", "order": "clickcount", "reverse": "true"}
    )
    results = []
    for s in fetch_json(f"{DIRECTORY_API}/stations/search?{params}"):
        codec = s.get("codec", "").upper()
        content_type = {"AAC": "audio/aac", "AAC+": "audio/aac"}.get(codec, "audio/mpeg")
        if s.get("hls") or s["url_resolved"].endswith(".m3u8"):
            content_type = "application/x-mpegURL"
        details = ", ".join(x for x in (s.get("countrycode"), codec, s.get("bitrate") and f"{s['bitrate']}k") if x)
        results.append(
            (
                Station(
                    id=s["stationuuid"],
                    name=s["name"].strip(),
                    stream=s["url_resolved"],
                    artwork=s.get("favicon", ""),
                    icon=s.get("favicon", ""),
                    content_type=content_type,
                ),
                details,
            )
        )
    return results


# --- Now playing --------------------------------------------------------------


def now_playing(station):
    """What's on air right now; None if unknown."""
    try:
        if station.now_playing == "radio357":
            return radio357_now_playing(station)
        if station.now_playing == "nowyswiat":
            return nowyswiat_now_playing()
        return icy_now_playing(station.stream)
    except (OSError, ValueError, KeyError):
        return None


def cache_busted(url):
    # Without it Nowy Świat's CDN serves a days-old answer.
    return f"{url}?tsapi={int(time.time() * 1000)}"


def radio357_now_playing(station):
    data = fetch_json(cache_busted("https://radio357.pl/stream/now/playing.json"))
    artist, _, song = (data.get("s") or "").partition(" - ")
    if artist == station.name:  # "Radio 357 - <tagline>" when no song is on
        artist = song = ""
    return NowPlaying(artist or None, song or None, (data.get("p") or {}).get("n"))


def nowyswiat_now_playing():
    d = fetch_json(cache_busted("https://nowyswiat.online/api/oZeta/stat")).get("data") or {}
    # Nowy Świat swaps the fields: "title" holds the artist, "artist" the song.
    return NowPlaying(d.get("title"), d.get("artist"))


def icy_now_playing(stream):
    """Read the StreamTitle that many stations embed in their stream."""
    req = urllib.request.Request(stream, headers={"Icy-MetaData": "1", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=5) as r:
        metaint = int(r.headers.get("icy-metaint") or 0)
        if not metaint:
            return None
        r.read(metaint)
        meta = r.read(r.read(1)[0] * 16).rstrip(b"\0").decode("utf-8", "replace")
    title = (re.search(r"StreamTitle='(.*?)';", meta) or [None, ""])[1].strip()
    artist, sep, song = title.partition(" - ")
    if not sep:
        return NowPlaying(song=title) if title else NowPlaying()
    return NowPlaying(artist.strip(), song.strip())


def describe(info):
    if not info:
        return None
    if info.artist and info.song:
        return f"{info.artist} – {info.song}"
    return info.song or info.artist


# --- Menu bar icons -------------------------------------------------------------


def icon_file(url):
    """Download a station icon and shrink it for the menu bar; None if that fails."""
    if not url:
        return None
    path = ICON_CACHE / f"{hashlib.sha1(url.encode()).hexdigest()[:16]}.png"
    if path.exists():
        return path
    ICON_CACHE.mkdir(parents=True, exist_ok=True)
    raw = path.with_suffix(".download")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            raw.write_bytes(r.read())
        subprocess.run(
            ["sips", "-s", "format", "png", "-Z", "44", str(raw), "--out", str(path)],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    finally:
        raw.unlink(missing_ok=True)
    return path


# --- Casting --------------------------------------------------------------------


def play(cast, station):
    metadata = {"metadataType": METADATA_TYPE_MUSIC_TRACK, "title": station.name}
    if station.tagline:
        metadata["artist"] = station.tagline
    mc = cast.media_controller
    mc.play_media(
        station.stream, station.content_type, thumb=station.artwork or None, stream_type="LIVE", metadata=metadata
    )
    mc.block_until_active(timeout=15)


def find_cast(name):
    if name:
        casts, browser = pychromecast.get_listed_chromecasts(friendly_names=[name], timeout=10)
    else:
        casts, browser = pychromecast.get_chromecasts(timeout=10)
    if not casts:
        browser.stop_discovery()
        sys.exit(f"No Chromecast found{f' named {name!r}' if name else ''}.")
    cast = casts[0]
    cast.wait()
    return cast, browser
