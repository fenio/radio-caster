"""Radio Caster: cast internet radio stations to a Chromecast.

Usage:
  radio-caster list               list favourites
  radio-caster <id>               play a favourite, e.g. radio-caster 357
  radio-caster now                show what's on all favourites
  radio-caster search <query>     search the radio-browser.info directory
  radio-caster add <query> <n>    add the n-th search result to favourites
                                  (best stream; <n>.<m> picks variant m)
  radio-caster stop               stop playback
  radio-caster vol 40             set volume to 40%
  radio-caster speaker            list speakers (* = the one in use)
  radio-caster speaker <name>     use this speaker from now on (app and command line)
  radio-caster menubar            run the menu bar app
  radio-caster open               show the app's window, starting the app if needed

Favourites live in ~/.config/radio-caster/stations.json (created on first run).
-d "Living Room" or the RADIOCASTER_DEVICE env var overrides the saved speaker
for one command. With no speaker saved, the first one found is used.
"""

import argparse
import os
import sys

import pychromecast

from .core import (
    add_favourite,
    describe,
    find_cast,
    load_favourites,
    load_settings,
    now_playing,
    play,
    save_setting,
    search_directory,
)


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("command", help="list, now, search, add, stop, vol, speaker, menubar, open, or a favourite's id")
    p.add_argument("args", nargs="*")
    p.add_argument("-d", "--device", default=os.environ.get("RADIOCASTER_DEVICE"))
    args = p.parse_args()

    if args.command == "menubar":
        from .menubar import run

        run(args.device)
        return

    if args.command == "open":
        from . import launcher

        launcher.open_app(launcher.executable())
        return

    favourites = {s.id: s for s in load_favourites()}

    if args.command == "list":
        for s in favourites.values():
            print(f"{s.id:<12} {s.name}")
        return

    if args.command == "now":
        for s in favourites.values():
            info = now_playing(s)
            show = info and info.show and f" [{info.show}]"
            print(f"{s.name}: {describe(info) or '?'}{show or ''}")
        return

    if args.command in ("search", "add"):
        if args.command == "add" and len(args.args) < 2:
            sys.exit('Usage: radio-caster add "<query>" <n>[.<variant>]')
        query = " ".join(args.args[:-1] if args.command == "add" else args.args)
        results = search_directory(query)
        if args.command == "search":
            for i, r in enumerate(results, 1):
                print(f"{i:>2}. {r.name}  ({r.country})")
                for j, v in enumerate(r.variants, 1):
                    print(f"      {i}.{j}  {v.label:<10} {v.station.stream}")
            return
        n, _, variant = args.args[-1].partition(".")
        result = results[int(n) - 1]
        station = add_favourite(result.variants[int(variant or 1) - 1].station)
        print(f"Added {station.name} as '{station.id}'.")
        return

    speaker = args.device or load_settings().get("speaker")

    if args.command in ("speaker", "devices"):
        if args.args:
            save_setting("speaker", " ".join(args.args))
            print(f"Using {' '.join(args.args)!r} from now on.")
            return
        casts, browser = pychromecast.get_chromecasts(timeout=10)
        browser.stop_discovery()
        for c in sorted(casts, key=lambda c: (c.cast_info.cast_type == "group", c.cast_info.friendly_name)):
            mark = "*" if c.cast_info.friendly_name == speaker else " "
            kind = "group" if c.cast_info.cast_type == "group" else c.cast_info.model_name
            print(f"{mark} {c.cast_info.friendly_name}  ({kind}, {c.cast_info.host})")
        return

    if args.command not in ("stop", "vol") and args.command not in favourites:
        sys.exit(f"Unknown command or favourite {args.command!r}. Favourites: {', '.join(favourites)}")

    cast, browser = find_cast(speaker)
    name = cast.cast_info.friendly_name

    if args.command == "stop":
        cast.quit_app()
        print(f"Stopped on {name}.")
    elif args.command == "vol":
        level = int(args.args[0]) if args.args and args.args[0].isdigit() else -1
        if not 0 <= level <= 100:
            sys.exit("Give volume 0-100, e.g.: radio-caster vol 40")
        cast.set_volume(level / 100)
        print(f"Volume on {name}: {level}%")
    else:
        play(cast, favourites[args.command])
        print(f"Playing {favourites[args.command].name} on {name}.")
    browser.stop_discovery()


if __name__ == "__main__":
    main()
