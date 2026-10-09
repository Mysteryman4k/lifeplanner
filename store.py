"""
Microsoft Store (MSIX) build support.

When Trackademic is installed from the Microsoft Store it runs as a packaged app. Four things differ:
  - the Store handles updates, so the built-in GitHub updater is switched off
  - "Start with Windows" uses the package's startup task instead of the Run registry key
  - notifications use the package's own app id (no Start-menu shortcut tricks)
  - Windows keeps the app's AppData files inside the package's own folder (transparent to the app)

TRACKADEMIC_STORE=1 / 0 forces Store mode on or off (used by tests).
"""
import asyncio
import os
import sys

STARTUP_TASK_ID = "TrackademicStartup"      # must match the <desktop:StartupTask TaskId> in the manifest
APP_ENTRY_ID = "App"                        # the Application Id in the manifest


def _package_name(function: str):
    """Ask Windows for the current package's full name or family name; None when not packaged."""
    import ctypes
    from ctypes import wintypes
    length = wintypes.UINT(0)
    getter = getattr(ctypes.windll.kernel32, function)
    if getter(ctypes.byref(length), None) != 122:                 # ERROR_INSUFFICIENT_BUFFER: packaged
        return None
    buf = ctypes.create_unicode_buffer(length.value)
    return buf.value if getter(ctypes.byref(length), buf) == 0 else None


def is_store_build() -> bool:
    forced = os.environ.get("TRACKADEMIC_STORE")
    if forced in ("0", "1"):
        return forced == "1"
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return False
    try:
        return _package_name("GetCurrentPackageFullName") is not None
    except Exception:
        return False


def app_user_model_id():
    """The id Windows gives this package's notifications and taskbar entry, e.g. 'Publisher.Trackademic_abc!App'."""
    try:
        family = _package_name("GetCurrentPackageFamilyName")
    except Exception:
        family = None
    return f"{family}!{APP_ENTRY_ID}" if family else None


# ── Start with Windows (startup task) ───────────────────────────────

def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def _startup_task():
    from winrt.windows.applicationmodel import StartupTask      # pip install winrt-Windows.ApplicationModel
    return await StartupTask.get_async(STARTUP_TASK_ID)


def startup_supported() -> bool:
    try:
        return _run(_startup_task()) is not None
    except Exception:
        return False


def startup_enabled() -> bool:
    try:
        from winrt.windows.applicationmodel import StartupTaskState
        return _run(_startup_task()).state in (StartupTaskState.ENABLED, StartupTaskState.ENABLED_BY_POLICY)
    except Exception:
        return False


def set_startup(enabled: bool) -> bool:
    """Turn the startup task on or off. Windows may refuse (the user turned it off in Settings > Apps > Startup)."""
    try:
        task = _run(_startup_task())
        if enabled:
            _run(task.request_enable_async())
        else:
            task.disable()
    except Exception:
        pass
    return startup_enabled()


# ── Notifications ───────────────────────────────────────────────────

def show_toast(title: str, body: str) -> bool:
    """Show a notification as the packaged app. False if it couldn't (caller falls back to PowerShell)."""
    try:
        from winrt.windows.data.xml.dom import XmlDocument
        from winrt.windows.ui.notifications import ToastNotification, ToastNotificationManager
        from xml.sax.saxutils import escape
        xml = XmlDocument()
        xml.load_xml("<toast><visual><binding template='ToastGeneric'>"
                     f"<text>{escape(title)}</text><text>{escape(body)}</text></binding></visual></toast>")
        ToastNotificationManager.create_toast_notifier().show(ToastNotification(xml))
        return True
    except Exception:
        return False
