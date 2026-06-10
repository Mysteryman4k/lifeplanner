#!/usr/bin/env python3
"""LifePlanner Desktop App — native window with embedded web view."""
import sys
import os
import threading
import time

VENV = os.path.dirname(os.path.abspath(__file__)) + "/venv"
if VENV not in sys.path:
    sys.path.insert(0, VENV + "/lib/python3.12/site-packages")

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(APP_DIR, "static", "icon.png")
PORT = 8585

# Enable high-DPI and Wayland
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
if "WAYLAND_DISPLAY" in os.environ or os.environ.get("XDG_SESSION_TYPE") == "wayland":
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland")

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

    # Setup Qt before webview
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtGui import QIcon, QFont
    from PyQt5.QtCore import Qt

    app = QApplication.instance() or QApplication(sys.argv)
    app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    # Modern dark stylesheet for Qt widgets
    app.setStyleSheet("""
        QToolTip {
            background: #1a1d27; color: #e4e6f0; border: 1px solid #2a2d3a;
            padding: 6px 10px; border-radius: 6px; font-size: 12px;
        }
        QMenu {
            background: #1a1d27; color: #e4e6f0; border: 1px solid #2a2d3a;
            border-radius: 8px; padding: 6px;
        }
        QMenu::item {
            padding: 6px 24px; border-radius: 4px;
        }
        QMenu::item:selected {
            background: rgba(99,102,241,0.2);
        }
    """)

    if os.path.exists(ICON_PATH):
        app.setWindowIcon(QIcon(ICON_PATH))

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
        text_select=True,
        easy_drag=False,
    )

    webview.start()

if __name__ == "__main__":
    main()
