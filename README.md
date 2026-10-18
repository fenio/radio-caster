# Radio Caster

Cast internet radio to a Chromecast (or any Google Cast speaker/display) from the
macOS menu bar or the command line.

- **Favourites** in a simple JSON file, with station artwork shown on the speaker's display
- **Search** ~50k stations from the [radio-browser.info](https://www.radio-browser.info) directory
- **Now playing**: the current song in the menu bar (built-in support for Radio 357 and
  Radio Nowy Świat, plus the ICY metadata many streams carry)
- Volume and stop controls; the station's logo becomes the menu bar icon while it plays

## Install

```sh
brew install fenio/tap/radio-caster
brew services start radio-caster   # run the menu bar app now and at login
```

## Command line

```
radio-caster list               list favourites
radio-caster <id>               play a favourite, e.g. radio-caster 357
radio-caster now                show what's on all favourites
radio-caster search <query>     search the radio-browser.info directory
radio-caster add <query> <n>    add the n-th search result to favourites
radio-caster stop               stop playback
radio-caster vol 40             set volume to 40%
radio-caster devices            list Cast devices on the network
radio-caster menubar            run the menu bar app
```

With several Cast devices, pick one with `-d "Living Room"` or the
`RADIOCASTER_DEVICE` environment variable; otherwise the first one found is used.

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
