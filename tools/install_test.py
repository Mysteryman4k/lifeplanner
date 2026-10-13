#!/usr/bin/env python3
"""Install, upgrade and uninstall test for the Windows installer (runs on GitHub's Windows machines).

What a real user does, checked automatically:
  1. install the previous published release and open it (fills the window cache, like a real user)
  2. install the new build over it, the way "Update now" does, and open it again:
     it must be the new version AND show the new screens, not cached old ones (the 3.5.0 bug)
  3. the Start-menu shortcut exists and carries EasyUniTrack's app id (needed for notifications)
  4. uninstall: the app and its "Start with Windows" entry are removed, the user's data is kept

  python tools/install_test.py dist/EasyUniTrack-Setup-3.5.2.exe --version 3.5.2
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = "Mysteryman4k/lifeplanner"
APP_ID = "Mysteryman4k.Trackademic"     # internal id kept from the old name
INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "EasyUniTrack"
EXE = INSTALL_DIR / "EasyUniTrack.exe"
# Before 3.6.0 the app was called Trackademic: releases from then install here
OLD_INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Trackademic"
OLD_EXE = OLD_INSTALL_DIR / "Trackademic.exe"
START_MENU = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
SMOKE = Path(__file__).with_name("smoke_desktop.py")
FAILURES = []


def step(msg):
    print(f"\n=== {msg}", flush=True)


def check(ok, msg):
    print(("✓ " if ok else "✗ ") + msg, flush=True)
    if not ok:
        FAILURES.append(msg)
    return ok


def github(path):
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/{path}",
                                 headers={"Accept": "application/vnd.github+json"})
    if os.environ.get("GH_TOKEN"):
        req.add_header("Authorization", f"Bearer {os.environ['GH_TOKEN']}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def previous_release(new_version):
    """The newest published, non-pre-release version older than the one being tested."""
    for rel in github("releases?per_page=10"):
        tag = rel["tag_name"].lstrip("v")
        if rel["prerelease"] or rel["draft"] or tag == new_version:
            continue
        asset = next((a for a in rel["assets"] if a["name"].startswith(("EasyUniTrack-Setup-", "Trackademic-Setup-"))), None)
        if asset:
            return tag, asset["browser_download_url"]
    return None, None


def kill_app():
    for exe in ("EasyUniTrack.exe", "Trackademic.exe"):          # Trackademic: releases before 3.6.0
        subprocess.run(["taskkill", "/IM", exe, "/F", "/T"], capture_output=True)
    time.sleep(1)


def run_installer(path):
    # Silent, like the in-app update. The installer opens the app when it finishes; close it.
    r = subprocess.run([str(path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"], timeout=300)
    time.sleep(5)
    kill_app()
    return r.returncode == 0


def launch(data, version, exe=EXE):
    r = subprocess.run([sys.executable, str(SMOKE), "--once", "--max-seconds", "60", "--data-dir", str(data),
                        "--expect-version", version, str(exe)], timeout=180)
    return r.returncode == 0


def run_value_exists(name="EasyUniTrack"):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, name)
            return True
    except OSError:
        return False


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("installer", type=Path)
    ap.add_argument("--version", required=True)
    args = ap.parse_args()
    if os.name != "nt":
        sys.exit("This test needs Windows.")
    data = Path(tempfile.mkdtemp(prefix="easyunitrack-install-test-"))

    prev, url = previous_release(args.version)
    prev_exe = None
    if prev:
        step(f"Install the previous release ({prev}) and open it")
        old = data.parent / url.rsplit("/", 1)[-1]
        urllib.request.urlretrieve(url, old)
        check(run_installer(old), f"{prev} installed")
        prev_exe = EXE if EXE.exists() else OLD_EXE                # releases before 3.6.0 were "Trackademic"
        check(launch(data, prev, prev_exe), f"{prev} opens")
        if prev_exe == OLD_EXE:
            import winreg                                          # as if "Start with Windows" was on in the old app
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.SetValueEx(key, "Trackademic", 0, winreg.REG_SZ, f'"{OLD_EXE}" --minimized')
    else:
        print("No previous release found; testing a fresh install only.")

    step(f"Install {args.version}" + (f" over {prev}" if prev else ""))
    check(run_installer(args.installer), f"{args.version} installed")
    check(EXE.exists(), f"app installed at {EXE}")
    check(launch(data, args.version), f"{args.version} opens with its own screens (same data and window cache as before)")
    if prev_exe == OLD_EXE:
        step("Moved off the old name (Trackademic)")
        check(not OLD_INSTALL_DIR.exists(), f"old app folder removed ({OLD_INSTALL_DIR})")
        check(next(iter(START_MENU.rglob("Trackademic.lnk")), None) is None, "old Start-menu shortcut removed")
        check(not run_value_exists("Trackademic"), 'old "Start with Windows" entry removed')
        check(run_value_exists(), '"Start with Windows" carried over to the new name')
        old_data = Path(os.environ["APPDATA"]) / "Trackademic" / "planner.db"
        new_data = Path(os.environ["APPDATA"]) / "EasyUniTrack" / "planner.db"
        check(new_data.exists(), "data copied to the new folder")
        check(old_data.exists(), "the old data folder is left in place")

    step("Start-menu shortcut")
    lnk = next(iter(START_MENU.rglob("EasyUniTrack.lnk")), None)
    check(lnk is not None, "Start-menu shortcut exists")
    apps = subprocess.run(["powershell", "-NoProfile", "-Command",
                           "Get-StartApps | Where-Object Name -eq 'EasyUniTrack' | Select-Object -ExpandProperty AppID"],
                          capture_output=True, text=True).stdout
    check(APP_ID in apps, f"shortcut carries the app id {APP_ID} (needed for notifications), got {apps.strip()!r}")

    step("Uninstall")
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:         # as if "Start with Windows" was on
        winreg.SetValueEx(key, "EasyUniTrack", 0, winreg.REG_SZ, f'"{EXE}" --minimized')
    uninstaller = next(iter(INSTALL_DIR.glob("unins*.exe")), None)
    if check(uninstaller is not None, "uninstaller present"):
        subprocess.run([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=300)
        for _ in range(60):                    # the uninstaller hands over to a copy of itself; wait for it
            if not EXE.exists():
                break
            time.sleep(1)
        check(not EXE.exists(), "app removed")
        check(not run_value_exists(), '"Start with Windows" entry removed')
        # The installer opened the app once with the normal data folder, so it exists and must survive
        user_data = Path(os.environ["APPDATA"]) / "EasyUniTrack" / "planner.db"
        check(user_data.exists(), f"the user's data is kept ({user_data})")

    if FAILURES:
        sys.exit("\nInstall test FAILED:\n  - " + "\n  - ".join(FAILURES))
    print("\nInstall test passed.")


if __name__ == "__main__":
    main()
