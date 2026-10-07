#!/usr/bin/env python3
"""Trackademic desktop app — runs the local server and opens it in a native window.

Uses pywebview, which picks the right engine for each system:
  Windows -> Edge WebView2 (built into Windows 10/11)
  macOS   -> WebKit
  Linux   -> GTK or Qt WebKit (whichever is installed)
"""
import base64
import json
import os
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)
STARTED = time.time()


def log(message: str):
    """Timestamped start-up log line (goes to trackademic.log in the packaged app)."""
    print(f"[{time.time() - STARTED:6.2f}s] {message}", flush=True)


def _redirect_output_when_windowed():
    """The packaged app has no console (sys.stdout is None), which crashes uvicorn's logging.
    Send output to a log file in the data folder instead — handy for bug reports too."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    from app import DB_PATH
    log = open(DB_PATH.parent / "trackademic.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or log
    sys.stderr = sys.stderr or log


def free_port(preferred: int = 8585) -> int:
    """Use the usual port if it's free, otherwise any free port (avoids clashing with another app)."""
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if os.name != "nt":   # match uvicorn: a port whose old connections are still closing is usable
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("No free port available")


def start_server(port: int):
    import uvicorn
    from app import app
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", use_colors=False)
    uvicorn.Server(config).run()


def wait_until_ready(url: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "api/info", timeout=1):
                return True
        except Exception:
            time.sleep(0.1)
    return False


# Display font for each text style (must match FONTS in static/theme.js)
STYLE_FONTS = {
    "rounded": ("Outfit", "outfit-latin-wght-normal.woff2"),
    "modern": ("Plus Jakarta Sans", "plus-jakarta-sans-latin-wght-normal.woff2"),
    "expressive": ("Bricolage Grotesque", "bricolage-grotesque-latin-wght-normal.woff2"),
    "techy": ("Space Grotesk", "space-grotesk-latin-wght-normal.woff2"),
    "classic": ("Fraunces", "fraunces-latin-wght-normal.woff2"),
}
INTRO_SECONDS = 2.7      # length of the intro animation
QUICK_SECONDS = 0.45     # minimum time for the plain loading screen
FALLBACK_SECONDS = 4.0   # if the window hasn't switched to the app this long after the intro, the splash does it itself


def build_splash_html(static_dir, appearance: dict, intro: bool, version: str, app_url: str = "about:blank") -> str:
    """The start-up screen, self-contained (inline CSS, font and theme) so it shows instantly,
    before the local server is running. Uses the same colours and font as the user's theme."""
    static_dir = Path(static_dir)
    font_name, font_file = STYLE_FONTS.get(appearance.get("font"), STYLE_FONTS["rounded"])
    font_b64 = base64.b64encode((static_dir / "fonts" / font_file).read_bytes()).decode()
    html = (static_dir / "splash.html").read_text(encoding="utf-8")
    for key, value in {
        "{{FONT_NAME}}": font_name,
        "{{FONT_B64}}": font_b64,
        "{{INTRO_CSS}}": (static_dir / "intro.css").read_text(encoding="utf-8"),
        "{{THEME_JS}}": (static_dir / "theme.js").read_text(encoding="utf-8"),
        "{{PREF}}": json.dumps(appearance),
        "{{MODE_CLASS}}": "play" if intro else "quick",
        "{{BAR_AFTER_MS}}": str(int((INTRO_SECONDS if intro else 0.2) * 1000)),
        "{{VERSION}}": version,
        "{{APP_URL_JSON}}": json.dumps(app_url),
        "{{FALLBACK_MS}}": str(int(((INTRO_SECONDS if intro else QUICK_SECONDS) + FALLBACK_SECONDS) * 1000)),
    }.items():
        html = html.replace(key, value)
    return html


def system_prefers_dark() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
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
    _redirect_output_when_windowed()
    from app import APP_NAME, APP_VERSION
    print(f"--- {APP_NAME} {APP_VERSION} starting {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)

    forced = os.environ.get("TRACKADEMIC_PORT")       # tests pin the port so they can find the app
    port = int(forced) if forced else free_port()
    url = f"http://127.0.0.1:{port}/"
    threading.Thread(target=start_server, args=(port,), daemon=True).start()   # starts while the splash plays
    log(f"server starting on port {port}")

    try:
        import webview
    except Exception:
        if not wait_until_ready(url):
            print("Error: the local server didn't start.", file=sys.stderr)
            sys.exit(1)
        run_in_browser(url)
        return

    from app import STATIC, get_appearance, get_startup_settings
    appearance = get_appearance()
    intro = get_startup_settings()["intro"]
    dark = appearance["mode"] == "dark" or (appearance["mode"] == "system" and system_prefers_dark())
    query = urllib.parse.urlencode({"from": "splash", "ap": json.dumps(appearance)})
    app_url = f"{url}?{query}#/today"

    webview.settings["ALLOW_DOWNLOADS"] = True                   # for "Download backup"
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True    # job ad / GitHub links open in your browser
    window = webview.create_window(
        title=APP_NAME,
        html=build_splash_html(STATIC, appearance, intro, APP_VERSION, app_url),
        width=1280,
        height=820,
        min_size=(380, 600),
        background_color="#140F16" if dark else "#FFF7F2",
        text_select=True,
    )

    def hand_over(win):
        """Wait for the server and the intro, then switch the window to the app.

        Deliberately makes no evaluate_js() calls: on Windows (WebView2) those can block
        forever, which is what froze 3.3.0 on the intro. load_url() only needs the window shown.
        """
        try:
            if not wait_until_ready(url):
                log("ERROR: the local server didn't start within 30 seconds")
                win.load_html("<body style='font:16px system-ui;padding:40px'>Trackademic couldn't start. "
                              "Please close it and try again.</body>")
                return
            log("server ready")
            remaining = (INTRO_SECONDS if intro else QUICK_SECONDS) - (time.time() - STARTED)
            if remaining > 0:
                time.sleep(remaining)
            log("opening the app")
            win.load_url(app_url)
            log("app requested")
        except Exception as e:                      # never die silently: the splash falls back by itself
            log(f"ERROR during start-up hand-off: {e!r}")

    log("showing splash")
    webview.start(hand_over, window, private_mode=False)
    log("window closed")


if __name__ == "__main__":
    main()
