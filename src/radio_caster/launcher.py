"""Starting the menu bar app from Spotlight, and keeping it to a single instance.

"Radio Caster.app" (the radio-caster-app cask, built by scripts/build_app.py) runs
`radio-caster open`: it shows the window of the running app, or starts the app first.
"""

import fcntl
import os
import subprocess
import sys
from pathlib import Path

import objc
from Foundation import NSDistributedNotificationCenter, NSObject

from .core import ICON_CACHE

STATE = ICON_CACHE.parent  # ~/Library/Caches/radio-caster
LOCK = STATE / "menubar.lock"  # held by the running app
WINDOW_REQUEST = STATE / "open-window"  # asks an app that is starting up to show its window
OPEN_WINDOW = "pl.fenski.radio-caster.open-window"
SERVICE = "sh.brew.radio-caster"  # launchd label of `brew services start radio-caster`
DELIVER_IMMEDIATELY = 4  # NSNotificationSuspensionBehaviorDeliverImmediately, even while not active


# --- In the menu bar app ------------------------------------------------------------


class _Observer(NSObject):
    def initWithHandler_(self, handler):
        self = objc.super(_Observer, self).init()
        if self is None:
            return None
        self.handler = handler
        return self

    def openWindow_(self, _notification):
        self.handler()


def listen(handler):
    """Calls handler (on the main thread) when `radio-caster open` asks for the window."""
    observer = _Observer.alloc().initWithHandler_(handler)
    NSDistributedNotificationCenter.defaultCenter().addObserver_selector_name_object_suspensionBehavior_(
        observer, "openWindow:", OPEN_WINDOW, None, DELIVER_IMMEDIATELY
    )
    return observer  # keep a reference, the notification center doesn't


def acquire_lock():
    """The lock file for the app's lifetime, or None when another instance holds it."""
    STATE.mkdir(parents=True, exist_ok=True)
    f = open(LOCK, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        return None
    return f


def take_window_request():
    try:
        WINDOW_REQUEST.unlink()
        return True
    except FileNotFoundError:
        return False


# --- `radio-caster open` -------------------------------------------------------------


def is_running():
    lock = acquire_lock()
    if lock is None:
        return True
    lock.close()
    return False


def open_app(executable):
    if is_running():
        NSDistributedNotificationCenter.defaultCenter().postNotificationName_object_userInfo_deliverImmediately_(
            OPEN_WINDOW, None, None, True
        )
        return
    STATE.mkdir(parents=True, exist_ok=True)
    WINDOW_REQUEST.touch()
    domain = f"gui/{os.getuid()}"
    if subprocess.run(["launchctl", "print", f"{domain}/{SERVICE}"], capture_output=True).returncode == 0:
        # Started with `brew services`: restart it there, so it stays one process.
        subprocess.run(["launchctl", "kickstart", f"{domain}/{SERVICE}"], check=True)
    else:
        subprocess.Popen(
            [executable, "menubar"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


def executable():
    """This command's path as run, e.g. /opt/homebrew/bin/radio-caster, which survives upgrades."""
    return str(Path(sys.argv[0]).absolute())

