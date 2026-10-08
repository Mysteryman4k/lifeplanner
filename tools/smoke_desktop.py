#!/usr/bin/env python3
"""Start-up smoke test for the real desktop app.

Launches the app (the packaged Trackademic.exe, or `python desktop.py`), waits until the
window has actually loaded the app past the intro, then closes it. Fails if that takes too long,
which is exactly how 3.3.0 broke (stuck on the intro) without any unit test noticing.

  python tools/smoke_desktop.py dist/Trackademic/Trackademic.exe
  python tools/smoke_desktop.py python desktop.py
  python tools/smoke_desktop.py --max-seconds 20 --runs 2 dist/Trackademic/Trackademic.exe
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


def kill_tree(proc: subprocess.Popen):
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def pick_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def status(port: int):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/diag/startup", timeout=2) as r:
            return json.load(r)
    except Exception:
        return None


def run_once(cmd, port: int, max_seconds: float, intro: bool, second_copy: bool = False,
             data: Path = None, expect_version: str = None) -> bool:
    data = Path(data) if data else Path(tempfile.mkdtemp(prefix="trackademic-smoke-"))
    data.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "TRACKADEMIC_DATA_DIR": str(data), "TRACKADEMIC_PORT": str(port)}
    if not intro:                                      # pre-seed the "intro off" setting
        import sqlite3
        db = sqlite3.connect(data / "planner.db")
        db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT OR REPLACE INTO settings VALUES ('startup', '{\"intro\": false}')")
        db.commit()
        db.close()
    out_path = data / "stdout.txt"
    label = "intro on" if intro else "intro off"
    print(f"\n▶ Launching ({label}): {' '.join(cmd)}")
    with open(out_path, "w", encoding="utf-8") as out:
        proc = subprocess.Popen(cmd, env=env, stdout=out, stderr=subprocess.STDOUT)
    started = time.time()
    ok, last, slow = False, None, False
    try:
        while time.time() - started < max_seconds:
            if proc.poll() is not None:
                print(f"✗ The app exited early with code {proc.returncode}")
                break
            last = status(port)
            if last and last.get("client_ready"):
                ok = True
                break
            time.sleep(0.25)
        elapsed = time.time() - started
        if ok:
            print(f"✓ App on screen after {elapsed:.1f}s (version {last['version']}, "
                  f"{last['seconds_to_ready']}s after the server started)")
            slow = elapsed > 10
            if expect_version and last["version"] != expect_version:
                print(f"✗ Expected version {expect_version} but {last['version']} started")
                ok = False
            elif last.get("screens_current") is False:        # key only exists from 3.5.2
                print(f"✗ The window ran cached screens from an old version (loaded app.js {last['app_js_versions']}), "
                      f"not {last['version']}")
                ok = False
        elif proc.poll() is None:
            stage = "the server never answered" if last is None else "the server is up but the window never showed the app"
            print(f"✗ Not on screen after {max_seconds:.0f}s: {stage}")
        if ok and second_copy:
            ok = check_second_copy(cmd, env, proc, port)
    finally:
        kill_tree(proc)
    if not ok or slow:
        if slow:
            print("  (slower than expected; start-up log below)")
        for name in ("trackademic.log", "stdout.txt"):
            f = data / name
            if f.exists() and f.read_text(encoding="utf-8", errors="replace").strip():
                print(f"--- {name} ---")
                print(f.read_text(encoding="utf-8", errors="replace")[-4000:])
    return ok


def check_second_copy(cmd, env, first, port) -> bool:
    """Opening Trackademic again should bring the open window forward and quit, not start a second app."""
    env2 = {**env, "TRACKADEMIC_PORT": str(pick_port())}
    started = time.time()
    second = subprocess.Popen(cmd, env=env2, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        second.wait(timeout=15)
    except subprocess.TimeoutExpired:
        kill_tree(second)
        print("✗ Opening a second copy started another app instead of using the open one")
        return False
    if first.poll() is not None or not status(port):
        print("✗ The open app closed when a second copy was opened")
        return False
    print(f"✓ Opening it again used the open window ({time.time() - started:.1f}s)")
    return True


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-seconds", type=float, default=25, help="fail if the app isn't on screen by then")
    ap.add_argument("--data-dir", help="reuse this data folder (keeps the window cache between runs)")
    ap.add_argument("--expect-version", help="fail unless this version starts")
    ap.add_argument("--once", action="store_true", help="one launch with the intro off (for install tests)")
    ap.add_argument("command", nargs=argparse.REMAINDER, help="how to start the app")
    args = ap.parse_args()
    if not args.command:
        ap.error("give the command that starts the app")
    cmd = [sys.executable if c == "python" else c for c in args.command]
    if args.once:
        results = [run_once(cmd, pick_port(), args.max_seconds, intro=False,
                            data=args.data_dir, expect_version=args.expect_version)]
    else:
        results = [run_once(cmd, pick_port(), args.max_seconds, intro=True, expect_version=args.expect_version),
                   run_once(cmd, pick_port(), args.max_seconds, intro=False, second_copy=True,
                            expect_version=args.expect_version)]
    if all(results):
        print("\nStart-up smoke test passed.")
    else:
        sys.exit("\nStart-up smoke test FAILED.")


if __name__ == "__main__":
    main()
