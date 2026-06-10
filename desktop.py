#!/usr/bin/env python3
"""LifePlanner Desktop App — native window with embedded web view."""
import sys
import os
import threading
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(APP_DIR, "static", "icon.png")
PORT = 8585

# High-DPI + Wayland
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
if "WAYLAND_DISPLAY" in os.environ or os.environ.get("XDG_SESSION_TYPE") == "wayland":
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland")

# MUST set before any QApplication is created (required by QtWebEngine)
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

def start_server():
    os.chdir(APP_DIR)
    import uvicorn
    from app import app
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")

def main():
    # Start server
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Wait for server
    import urllib.request
    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/")
            break
        except Exception:
            time.sleep(0.2)

    # Setup Qt app instance
    app = QApplication.instance() or QApplication(sys.argv)

    from PyQt5.QtGui import QIcon
    if os.path.exists(ICON_PATH):
        app.setWindowIcon(QIcon(ICON_PATH))

    # Create native window (import after Qt is ready)
    import webview
    window = webview.create_window(
        title="LifePlanner",
        url=f"http://127.0.0.1:{PORT}/",
        width=1280,
        height=820,
        min_size=(900, 600),
        resizable=True,
        text_select=True,
    )

    webview.start()

if __name__ == "__main__":
    main()
