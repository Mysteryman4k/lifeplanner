#!/usr/bin/env python3
"""Copy a built app folder and mark every file the way Windows marks files unzipped from a download (a
Zone.Identifier stream with ZoneId=3), so CI can check the portable zip starts. Windows (NTFS) only.

  python tools/mark_downloaded.py dist/EasyUniTrack dist-downloaded/EasyUniTrack

4.0.0-beta.1's portable zip crashed at start for exactly this reason: .NET refused the marked Python.Runtime.dll.
"""
import shutil
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst)
    marked = 0
    for f in dst.rglob("*"):
        if f.is_file():
            with open(f"{f}:Zone.Identifier", "w", encoding="ascii") as stream:   # an NTFS alternate data stream
                stream.write("[ZoneTransfer]\r\nZoneId=3\r\n")
            marked += 1
    print(f"Marked {marked} files in {dst} as downloaded from the internet")


if __name__ == "__main__":
    main()
