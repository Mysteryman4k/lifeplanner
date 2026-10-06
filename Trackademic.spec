# -*- mode: python ; coding: utf-8 -*-
# Build:  pyinstaller Trackademic.spec   ->  dist/Trackademic(.exe)
# Your data is stored in %APPDATA%\Trackademic (Windows) or ~/.local/share/Trackademic (Linux),
# so it is kept between launches and updates.

a = Analysis(
    ['desktop.py'],
    pathex=[],
    binaries=[],
    datas=[('static', 'static')],
    hiddenimports=['uvicorn.loops.auto', 'uvicorn.protocols.http.auto', 'uvicorn.lifespan.on'],
    hookspath=[],
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Trackademic',
    debug=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=False,
    icon=['static/icon.ico'],
)
