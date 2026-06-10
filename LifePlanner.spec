# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['desktop.py'],
    pathex=[],
    binaries=[],
    datas=[('static/index.html', 'static'), ('static/icon.png', 'static'), ('static/icon.svg', 'static'), ('static/icon-16.png', 'static'), ('static/icon-32.png', 'static'), ('static/icon-48.png', 'static'), ('static/icon-64.png', 'static'), ('static/icon-128.png', 'static'), ('static/icon-192.png', 'static'), ('static/icon-256.png', 'static'), ('static/icon-512.png', 'static')],
    hiddenimports=['uvicorn', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto', 'fastapi', 'PyQt5.QtWebEngineWidgets', 'PyQt5.QtWebEngineCore', 'webview.platforms.qt', 'pydantic'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LifePlanner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['static/icon.png'],
)
