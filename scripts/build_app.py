"""Builds dist/Radio-Caster-<version>.zip: the Radio Caster.app of the radio-caster-app cask.

The app is only a launcher for the radio-caster command from the formula, so it has
no Python in it and needs rebuilding only when this script changes.

  uv run python scripts/build_app.py
"""

import plistlib
import subprocess
import tempfile
from pathlib import Path

from AppKit import (
    NSBezierPath,
    NSBitmapImageRep,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSGraphicsContext,
    NSPNGFileType,
    NSString,
)

from radio_caster import __version__

DIST = Path(__file__).resolve().parent.parent / "dist"

LAUNCHER = """#!/bin/sh
# Shows Radio Caster's window, starting the menu bar app if it isn't running.
PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v radio-caster >/dev/null; then
  osascript -e 'display alert "Radio Caster is not installed" message "brew install fenio/tap/radio-caster"'
  exit 1
fi
exec radio-caster open
"""


def build(app):
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "Resources").mkdir()
    with open(contents / "Info.plist", "wb") as f:
        plistlib.dump(
            {
                "CFBundleName": "Radio Caster",
                "CFBundleDisplayName": "Radio Caster",
                "CFBundleIdentifier": "pl.fenski.radio-caster",
                "CFBundleExecutable": "launcher",
                "CFBundleIconFile": "AppIcon",
                "CFBundlePackageType": "APPL",
                "CFBundleShortVersionString": __version__,
                "CFBundleVersion": __version__,
                "LSUIElement": True,  # no Dock icon for the moment it runs
            },
            f,
        )
    script = contents / "MacOS" / "launcher"
    script.write_text(LAUNCHER)
    script.chmod(0o755)
    make_icon(contents / "Resources" / "AppIcon.icns")


def make_icon(dest):
    """The 📻 emoji on a rounded tile in the window's accent colour, as an .icns."""
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "AppIcon.iconset"
        iconset.mkdir()
        for points in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = points * scale
                rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
                    None, px, px, 8, 4, True, False, "NSDeviceRGBColorSpace", 0, 0
                )
                NSGraphicsContext.saveGraphicsState()
                NSGraphicsContext.setCurrentContext_(NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep))
                inset, size = px * 0.1, px * 0.8
                NSColor.colorWithSRGBRed_green_blue_alpha_(0.91, 0.27, 0.17, 1).setFill()
                NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    ((inset, inset), (size, size)), size * 0.22, size * 0.22
                ).fill()
                emoji = NSString.stringWithString_("📻")
                attrs = {NSFontAttributeName: NSFont.systemFontOfSize_(size * 0.62)}
                w, h = emoji.sizeWithAttributes_(attrs)
                emoji.drawAtPoint_withAttributes_(((px - w) / 2, (px - h) / 2), attrs)
                NSGraphicsContext.restoreGraphicsState()
                name = f"icon_{points}x{points}{'@2x' if scale == 2 else ''}.png"
                rep.representationUsingType_properties_(NSPNGFileType, {}).writeToFile_atomically_(
                    str(iconset / name), True
                )
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(dest)], check=True)


def main():
    DIST.mkdir(exist_ok=True)
    out = DIST / f"Radio-Caster-{__version__}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        app = Path(tmp) / "Radio Caster.app"
        build(app)
        out.unlink(missing_ok=True)
        subprocess.run(["ditto", "-c", "-k", "--keepParent", str(app), str(out)], check=True)
    print(out)


if __name__ == "__main__":
    main()
