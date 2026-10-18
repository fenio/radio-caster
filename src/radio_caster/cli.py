"""Radio Caster: cast internet radio stations to a Chromecast.

Usage:
  radio-caster list               list favourites
  radio-caster <id>               play a favourite, e.g. radio-caster 357
  radio-caster now                show what's on all favourites
  radio-caster search <query>     search the radio-browser.info directory
  radio-caster add <query> <n>    add the n-th search result to favourites
  radio-caster stop               stop playback
  radio-caster vol 40             set volume to 40%
  radio-caster devices            list Chromecasts on the network
  radio-caster menubar            run the menu bar app

Favourites live in ~/.config/radio-caster/stations.json (created on first run).
Pick a device with -d "Living Room" or the RADIOCASTER_DEVICE env var
(otherwise the first one found is used).
"""

import argparse
import os
import sys

import pychromecast

from .core import add_favourite, describe, find_cast, load_favourites, now_playing, play, search_directory


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("command", help="list, now, search, add, stop, vol, devices, menubar, or a favourite's id")
    p.add_argument("args", nargs="*")
    p.add_argument("-d", "--device", default=os.environ.get("RADIOCASTER_DEVICE"))
    args = p.parse_args()

    if args.command == "menubar":
        from .menubar import run

        run(args.device)
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
            sys.exit('Usage: radio-caster add "<query>" <n>')
        query = " ".join(args.args[:-1] if args.command == "add" else args.args)
        results = search_directory(query)
        if args.command == "search":
            for i, (s, details) in enumerate(results, 1):
                print(f"{i:>2}. {s.name}  ({details})\n    {s.stream}")
            return
        station = add_favourite(results[int(args.args[-1]) - 1][0])
        print(f"Added {station.name} as '{station.id}'.")
        return

    if args.command == "devices":
        casts, browser = pychromecast.get_chromecasts(timeout=10)
        browser.stop_discovery()
        for c in casts:
            print(f"{c.cast_info.friendly_name}  ({c.cast_info.model_name}, {c.cast_info.host})")
        return

    if args.command not in ("stop", "vol") and args.command not in favourites:
        sys.exit(f"Unknown command or favourite {args.command!r}. Favourites: {', '.join(favourites)}")

    cast, browser = find_cast(args.device)
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
