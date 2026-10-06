#!/usr/bin/env python3
"""Trackademic desktop app — runs the local server and opens it in a native window.

Uses pywebview, which picks the right engine for each system:
  Windows -> Edge WebView2 (built into Windows 10/11)
  macOS   -> WebKit
  Linux   -> GTK or Qt WebKit (whichever is installed)
"""
import os
import socket
import sys
import threading
import time
import urllib.request

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)


def free_port(preferred: int = 8585) -> int:
    """Use the usual port if it's free, otherwise any free port (avoids clashing with another app)."""
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("No free port available")


def start_server(port: int):
    import uvicorn
    from app import app
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    uvicorn.Server(config).run()


def wait_until_ready(url: str, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "api/info", timeout=1):
                return True
        except Exception:
            time.sleep(0.1)
    return False


def run_in_browser(url: str):
    """Fallback when pywebview isn't available: open the app in the default browser."""
    import webbrowser
    print(f"Opening {url} in your browser. Close this window to stop the app.")
    webbrowser.open(url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


def main():
    from app import APP_NAME

    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    threading.Thread(target=start_server, args=(port,), daemon=True).start()
    if not wait_until_ready(url):
        print("Error: the local server didn't start.", file=sys.stderr)
        sys.exit(1)

    try:
        import webview
    except Exception:
        run_in_browser(url)
        return

    webview.settings["ALLOW_DOWNLOADS"] = True                   # for "Download backup"
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True    # job ad / GitHub links open in your browser
    webview.create_window(
        title=APP_NAME,
        url=url,
        width=1280,
        height=820,
        min_size=(380, 600),
        background_color="#FFF7F2",
        text_select=True,
    )
    webview.start(private_mode=False)


if __name__ == "__main__":
    main()
