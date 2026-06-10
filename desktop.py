#!/usr/bin/env python3
"""LifePlanner Desktop App — native window with embedded web view."""
import sys
import os
import threading
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(APP_DIR, "static", "icon.png")
PORT = 8585
VERSION = "2.1"

# High-DPI + Wayland
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
if "WAYLAND_DISPLAY" in os.environ or os.environ.get("XDG_SESSION_TYPE") == "wayland":
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland")

# MUST set before any QApplication is created (required by QtWebEngine)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication, QSplashScreen
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QFont, QColor, QLinearGradient

QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

def create_splash_pixmap():
    """Generate splash screen image with logo and branding."""
    w, h = 480, 320
    pix = QPixmap(w, h)
    pix.fill(QColor("#14161f"))

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)

    # Load and draw logo centered
    if os.path.exists(ICON_PATH):
        logo = QPixmap(ICON_PATH).scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        lx = (w - logo.width()) // 2
        painter.drawPixmap(lx, 50, logo)

    # App name
    name_font = QFont("Inter, -apple-system, Segoe UI, sans-serif", 32, QFont.Bold)
    painter.setFont(name_font)
    painter.setPen(QColor("#e4e6f0"))
    painter.drawText(0, 175, w, 50, Qt.AlignCenter, "LifePlanner")

    # Version
    ver_font = QFont("Inter, -apple-system, sans-serif", 11)
    painter.setFont(ver_font)
    painter.setPen(QColor("#7c8097"))
    painter.drawText(0, 215, w, 20, Qt.AlignCenter, f"v{VERSION}")

    # Tagline
    tag_font = QFont("Inter, -apple-system, sans-serif", 11)
    painter.setFont(tag_font)
    painter.setPen(QColor("#6366f1"))
    painter.drawText(0, 240, w, 20, Qt.AlignCenter, "Plan. Track. Achieve.")

    # Copyright
    copy_font = QFont("Inter, -apple-system, sans-serif", 9)
    painter.setFont(copy_font)
    painter.setPen(QColor("#555974"))
    painter.drawText(0, 280, w, 20, Qt.AlignCenter, "© 2026 Mysteryman4k. All rights reserved.")

    painter.end()
    return pix

def start_server():
    os.chdir(APP_DIR)
    import uvicorn
    from app import app
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")

def main():
    app = QApplication(sys.argv)

    # Splash screen
    splash_pix = create_splash_pixmap()
    splash = QSplashScreen(splash_pix)
    if os.path.exists(ICON_PATH):
        app.setWindowIcon(QIcon(ICON_PATH))
    splash.show()
    app.processEvents()

    # Start server in background
    server_ready = threading.Event()
    def run_server():
        start_server()
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Wait for server with splash visible
    import urllib.request
    for i in range(40):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/")
            server_ready.set()
            break
        except Exception:
            time.sleep(0.15)
            app.processEvents()

    if not server_ready.is_set():
        splash.close()
        print("Error: Server failed to start")
        sys.exit(1)

    # Create main window
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

    # Close splash after window appears
    QTimer.singleShot(800, splash.close)
    webview.start()

if __name__ == "__main__":
    main()
