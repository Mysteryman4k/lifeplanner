#!/usr/bin/env python3
"""Print the CHANGELOG.md section for a version (used as the GitHub release notes).

  python tools/release_notes.py 3.2.0
"""
import re
import sys
from pathlib import Path

text = (Path(__file__).resolve().parent.parent / "CHANGELOG.md").read_text(encoding="utf-8")
version = sys.argv[1].lstrip("v")
m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.S | re.M)
if not m or not m.group(1).strip():
    sys.exit(f"CHANGELOG.md has no entry for {version}. Add one before tagging the release.")
print(m.group(1).strip())
