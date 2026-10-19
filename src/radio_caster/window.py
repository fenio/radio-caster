"""The main window: an HTML page (ui/index.html) in a native window.

The page sends actions as JSON through `window.webkit.messageHandlers.radioCaster`,
and the app pushes its state back by calling the page's `render(state)`.
"""

import json
from pathlib import Path

import objc
from AppKit import (
    NSApp,
    NSBackingStoreBuffered,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSURL, NSObject
from WebKit import WKWebView, WKWebViewConfiguration

PAGE = Path(__file__).resolve().parent / "ui" / "index.html"


class _Bridge(NSObject, protocols=[objc.protocolNamed("WKScriptMessageHandler")]):
    def initWithHandler_(self, handler):
        self = objc.super(_Bridge, self).init()
        if self is None:
            return None
        self.handler = handler
        return self

    def userContentController_didReceiveScriptMessage_(self, controller, message):
        self.handler(json.loads(message.body()))


class MainWindow:
    def __init__(self, on_message):
        self.ready = False  # set by the app when the page reports it has loaded
        self.last_state = None
        self.focus_search_when_ready = False

        config = WKWebViewConfiguration.alloc().init()
        self.bridge = _Bridge.alloc().initWithHandler_(on_message)
        config.userContentController().addScriptMessageHandler_name_(self.bridge, "radioCaster")

        frame = NSMakeRect(0, 0, 440, 680)
        style = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable
            | NSWindowStyleMaskResizable
        )
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, style, NSBackingStoreBuffered, False
        )
        self.window.setTitle_("Radio Caster")
        self.window.setReleasedWhenClosed_(False)
        self.window.setMinSize_((360, 420))
        self.window.center()
        self.window.setFrameAutosaveName_("RadioCasterMain")

        self.webview = WKWebView.alloc().initWithFrame_configuration_(frame, config)
        self.window.setContentView_(self.webview)
        url = NSURL.fileURLWithPath_(str(PAGE))
        self.webview.loadFileURL_allowingReadAccessToURL_(url, url.URLByDeletingLastPathComponent())

    @property
    def visible(self):
        return bool(self.window.isVisible())

    def show(self, focus_search=False):
        NSApp.activateIgnoringOtherApps_(True)
        self.window.makeKeyAndOrderFront_(None)
        if focus_search:
            if self.ready:
                self.run_js("focusSearch()")
            else:
                self.focus_search_when_ready = True

    def page_ready(self):
        self.ready = True
        self.last_state = None
        if self.focus_search_when_ready:
            self.focus_search_when_ready = False
            self.run_js("focusSearch()")

    def render(self, state):
        payload = json.dumps(state, ensure_ascii=False)
        if self.ready and payload != self.last_state:
            self.last_state = payload
            self.run_js(f"render({payload})")

    def run_js(self, code):
        self.webview.evaluateJavaScript_completionHandler_(code, None)


def install_edit_menu():
    """Without a main menu, ⌘C/⌘V/⌘A don't work in the window's text fields."""
    main = NSMenu.alloc().init()
    app_item = NSMenuItem.alloc().init()
    main.addItem_(app_item)
    app_menu = NSMenu.alloc().init()
    app_menu.addItemWithTitle_action_keyEquivalent_("Close Window", "performClose:", "w")
    app_item.setSubmenu_(app_menu)

    edit_item = NSMenuItem.alloc().init()
    main.addItem_(edit_item)
    edit = NSMenu.alloc().initWithTitle_("Edit")
    for title, action, key in [
        ("Undo", "undo:", "z"),
        ("Redo", "redo:", "Z"),
        ("Cut", "cut:", "x"),
        ("Copy", "copy:", "c"),
        ("Paste", "paste:", "v"),
        ("Select All", "selectAll:", "a"),
    ]:
        edit.addItemWithTitle_action_keyEquivalent_(title, action, key)
    edit_item.setSubmenu_(edit)
    NSApp.setMainMenu_(main)
