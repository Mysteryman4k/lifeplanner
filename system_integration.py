"""
Windows integration for the installed app:
  - Start with Windows (a per-user "Run" entry that opens Trackademic minimised)
  - Single instance: opening Trackademic again (or clicking a notification) brings the
    running window to the front instead of starting a second copy
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

import store

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "Trackademic"


def autostart_supported() -> bool:
    """Only the installed Windows app has a stable .exe path to start at sign-in."""
    if store.is_store_build():
        return store.startup_supported()
    return os.name == "nt" and bool(getattr(sys, "frozen", False))


def autostart_enabled() -> bool:
    if not autostart_supported():
        return False
    if store.is_store_build():
        return store.startup_enabled()
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_VALUE)
            return True
    except OSError:
        return False


def set_autostart(enabled: bool) -> bool:
    if not autostart_supported():
        return False
    if store.is_store_build():                                 # packaged apps use a startup task, not the Run key
        return store.set_startup(enabled)
    import winreg
    # CreateKeyEx, not OpenKey: the Run key doesn't exist on fresh accounts
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, f'"{sys.executable}" --minimized')
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass
    return autostart_enabled()


# ── Single instance ──────────────────────────────────────────────────

def _lock_file(data_dir: Path) -> Path:
    return Path(data_dir) / "instance.json"


def find_running_instance(data_dir: Path, app_name: str):
    """Port of an already-running Trackademic using the same data, or None."""
    try:
        info = json.loads(_lock_file(data_dir).read_text(encoding="utf-8"))
        port = int(info["port"])
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/info", timeout=1.5) as r:
            if json.load(r).get("name") == app_name:
                return port
    except Exception:
        pass
    return None


def bring_to_front(port: int) -> bool:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/window/show", method="POST")
        with urllib.request.urlopen(req, timeout=3):
            return True
    except Exception:
        return False


def claim_instance(data_dir: Path, port: int):
    try:
        _lock_file(data_dir).write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")
    except OSError:
        pass
