# Radio Caster

Cast internet radio to a Chromecast (or any Google Cast speaker/display) from the
macOS menu bar or the command line.

- **Menu bar** quick access: current song, favourites, stop and volume
- **Main window** (*Open Radio Caster…* in the menu): now playing with artwork and a volume
  slider, your favourites, and search across ~50k stations from the
  [radio-browser.info](https://www.radio-browser.info) directory with one-click *Play* and *Add*
- **Favourites** in a simple JSON file, with station artwork shown on the speaker's display
- **Now playing**: the current song in the menu bar (built-in support for Radio 357 and
  Radio Nowy Świat, plus the ICY metadata many streams carry)
- Volume and stop controls; the station's logo becomes the menu bar icon while it plays

## Install

```sh
brew install --cask fenio/tap/radio-caster-app   # Radio Caster.app, plus the radio-caster formula
brew services start radio-caster                 # optional: run it at login
```

*Radio Caster* in Spotlight or Applications starts the menu bar app and shows its window
(`radio-caster open` does the same). Without the app: `brew install fenio/tap/radio-caster`.

## Command line

```
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
```

## Speakers

With several Cast devices (including speaker groups), pick one from the menu bar's
*Speaker* submenu, the window's footer, or `radio-caster speaker <name>`. The choice is
saved and shared by the app and the command line. Switching while a station plays
moves it to the new speaker. `-d "Living Room"` or the `RADIOCASTER_DEVICE`
environment variable overrides it for a single command.

## Favourites

Stored in `~/.config/radio-caster/stations.json`, created with two Polish stations on
first run. Add stations from the menu's search, with `radio-caster add`, or by hand:

```json
{
  "id": "jazz",
  "name": "Jazz Radio",
  "stream": "http://jazzradio.ice.infomaniak.ch/jazzradio-high.mp3",
  "artwork": "https://example.com/cover.png",
  "tagline": "Shown under the name on the speaker",
  "icon": "https://example.com/icon-180.png",
  "now_playing": "icy",
  "content_type": "audio/mpeg"
}
```

The menu bar app reloads the file when it changes.

## Development

```sh
uv run radio-caster menubar
```
