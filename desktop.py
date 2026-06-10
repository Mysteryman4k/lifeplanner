#!/usr/bin/env python3
"""LifePlanner Desktop App — native window with embedded web view."""
import sys
import os
import threading
import time
import signal

# Ensure we use the venv
VENV = os.path.dirname(os.path.abspath(__file__)) + "/venv"
if VENV not in sys.path:
    sys.path.insert(0, VENV + "/lib/python3.12/site-packages")

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(APP_DIR, "static", "icon.png")
PORT = 8585

# Fix Qt on Wayland
if "WAYLAND_DISPLAY" in os.environ or os.environ.get("XDG_SESSION_TYPE") == "wayland":
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland")

def start_server():
    """Run the FastAPI server in a background thread."""
    os.chdir(APP_DIR)
    import uvicorn
    from app import app
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")

def main():
    # Start server thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Wait for server to be ready
    import urllib.request
    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/")
            break
        except Exception:
            time.sleep(0.2)

    # Create native window
    import webview
    window = webview.create_window(
        title="LifePlanner",
        url=f"http://127.0.0.1:{PORT}/",
        width=1280,
        height=820,
        min_size=(900, 600),
        resizable=True,
        fullscreen=False,
    )

    # Set window icon via Qt
    if os.path.exists(ICON_PATH):
        try:
            from PyQt5.QtGui import QIcon
            from PyQt5.QtWidgets import QApplication
            app_instance = QApplication.instance()
            if app_instance:
                app_instance.setWindowIcon(QIcon(ICON_PATH))
        except Exception:
            pass

    webview.start()

if __name__ == "__main__":
    main()
