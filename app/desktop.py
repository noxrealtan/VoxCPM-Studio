#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fenêtre native pour VoxCPM Studio (macOS et Windows).

L'interface existante (web/index.html servie par le serveur local embarqué)
est affichée dans une vraie fenêtre d'application :
  - macOS    : PyObjC + WKWebView (Dock, menu ⌘Q, alerte de fermeture).
  - Windows  : pywebview + WebView2 (barre des tâches, Alt+F4, dialogue Tk).
Repli navigateur si la couche graphique n'est pas disponible.
"""
import sys
import threading

from .state import STATE, log


def desktop_available():
    """La couche graphique native est-elle utilisable sur cette plateforme ?"""
    if sys.platform == "darwin":
        try:
            import AppKit  # noqa: F401
            import WebKit  # noqa: F401
            return True
        except Exception:
            return False
    if sys.platform == "win32":
        try:
            import webview  # noqa: F401
            return True
        except Exception:
            return False
    return False


def _active_jobs():
    with STATE.lock:
        return sum(1 for j in STATE.jobs.values()
                   if j["status"] in ("queued", "running"))


def run_desktop(port):
    """Ouvre la fenêtre native (bloquant jusqu'à la fermeture)."""
    if sys.platform == "darwin":
        _run_mac(port)
    else:
        _run_windows(port)


# ---------------------------------------------------------------------------
# macOS (PyObjC + WKWebView)
# ---------------------------------------------------------------------------
def _run_mac(port):
    import AppKit
    import Foundation
    import WebKit

    from .http_api import server_url

    url = server_url(port)

    class AppDelegate(Foundation.NSObject):
        def applicationDidFinishLaunching_(self, note):
            frame = Foundation.NSMakeRect(0, 0, 1180, 800)
            style = (AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable |
                     AppKit.NSWindowStyleMaskMiniaturizable | AppKit.NSWindowStyleMaskResizable)
            win = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                frame, style, AppKit.NSBackingStoreBuffered, False)
            win.setTitle_("VoxCPM Studio")
            win.center()

            conf = WebKit.WKWebViewConfiguration.alloc().init()
            webview = WebKit.WKWebView.alloc().initWithFrame_configuration_(frame, conf)
            webview.loadRequest_(Foundation.NSURLRequest.requestWithURL_(
                Foundation.NSURL.URLWithString_(url)))
            win.setContentView_(webview)
            win.makeKeyAndOrderFront_(None)
            win.setReleasedWhenClosed_(False)
            self.window = win
            self.webview = webview

        def applicationShouldTerminateAfterLastWindowClosed_(self, sender):
            """Fermer la fenetre = quitter l'application."""
            return True

        def applicationShouldTerminate_(self, sender):
            """Empêche la fermeture pendant une génération (proposition d'attendre)."""
            active = _active_jobs()
            if not active:
                return AppKit.NSTerminateNow
            alert = AppKit.NSAlert.alloc().init()
            alert.setMessageText_("Une génération est en cours")
            alert.setInformativeText_(
                "%d génération(s) en cours ou en attente. Fermer quand même ?" % active)
            alert.addButtonWithTitle_("Fermer quand même")
            alert.addButtonWithTitle_("Attendre")
            if alert.runModal() == AppKit.NSAlertFirstButtonReturn:
                return AppKit.NSTerminateNow
            return AppKit.NSTerminateCancel

    app = AppKit.NSApplication.sharedApplication()
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)
    menu = AppKit.NSMenu.alloc().init()
    item = menu.addItemWithTitle_action_keyEquivalent_("VoxCPM Studio", None, "")
    submenu = AppKit.NSMenu.alloc().init()
    submenu.addItemWithTitle_action_keyEquivalent_(
        "Quitter VoxCPM Studio", "terminate:", "q")
    menu.setSubmenu_forItem_(submenu, item)
    app.setMainMenu_(menu)
    app.activateIgnoringOtherApps_(True)
    log("Fenetre native ouverte : %s" % url)
    app.run()


# ---------------------------------------------------------------------------
# Windows (pywebview + WebView2, déjà présent sur Windows 10/11 à jour)
# ---------------------------------------------------------------------------
def _run_windows(port):
    import webview

    from .http_api import server_url

    url = server_url(port)

    def on_closing():
        """Alt+F4 / croix : propose d'attendre si une génération est en cours.
        Retourne False pour annuler la fermeture (event `closing` pywebview)."""
        active = _active_jobs()
        if not active:
            return None  # fermeture autorisée
        try:
            import ctypes
            res = ctypes.windll.user32.MessageBoxW(
                0,
                "%d génération(s) en cours ou en attente.\n\n"
                "Attendre la fin ? (Oui = rester ouvert, Non = fermer quand même)" % active,
                "VoxCPM Studio", 0x4 | 0x20)  # MB_YESNO | MB_ICONQUESTION
            if res == 6:  # IDYES
                return False
        except Exception:
            pass
        return None

    log("Fenetre native ouverte : %s" % url)
    win = webview.create_window(
        "VoxCPM Studio", url,
        width=1180, height=820, min_size=(900, 620))
    win.events.closing += on_closing
    webview.start()


def run_browser(port):
    """Repli : ouvre l'URL dans le navigateur par défaut."""
    import webbrowser

    from .http_api import server_url

    url = server_url(port)
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    log("Interface disponible (navigateur) : %s" % url)
