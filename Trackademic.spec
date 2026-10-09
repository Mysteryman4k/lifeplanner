# -*- mode: python ; coding: utf-8 -*-
# Build:  pyinstaller --noconfirm Trackademic.spec   ->  dist/Trackademic/Trackademic(.exe)
#
# "onedir" build: a folder with Trackademic.exe and its files. It starts much faster than a
# single-file .exe (nothing is unpacked on each launch) and is what the installer ships.
# Your data is stored separately in %APPDATA%\Trackademic, so it's kept across updates.

import os
import sys

# Windows "Properties > Details" info, generated from the VERSION file
VERSION = open('VERSION', encoding='utf-8').read().strip()
_nums = tuple(int(x) for x in VERSION.split('-')[0].split('.')) + (0,)
os.makedirs('build', exist_ok=True)
with open('build/version_info.txt', 'w', encoding='utf-8') as f:
    f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={_nums}, prodvers={_nums}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Mysteryman4k'),
      StringStruct('FileDescription', 'Trackademic'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', 'Trackademic'),
      StringStruct('LegalCopyright', '(c) 2026 Mysteryman4k'),
      StringStruct('OriginalFilename', 'Trackademic.exe'),
      StringStruct('ProductName', 'Trackademic'),
      StringStruct('ProductVersion', '{VERSION}')])]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
""")

a = Analysis(
    ['desktop.py'],
    pathex=[],
    binaries=[],
    datas=[('static', 'static'), ('VERSION', '.')],
    hiddenimports=['uvicorn.loops.auto', 'uvicorn.protocols.http.auto', 'uvicorn.lifespan.on', 'updater', 'reminders', 'system_integration', 'store'],
    hookspath=[],
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'tkinter', 'pytest', 'playwright'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Trackademic',
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=['static/icon.ico'],
    version='build/version_info.txt' if sys.platform == 'win32' else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='Trackademic',
)
