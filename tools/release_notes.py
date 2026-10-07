#!/usr/bin/env python3
"""Print (or save) the CHANGELOG.md section for a version, used as the GitHub release notes.

  python tools/release_notes.py 3.2.0                     # print
  python tools/release_notes.py 3.2.0 release-notes.md    # save as UTF-8 (what the Release workflow does)

Always UTF-8: Windows consoles default to cp1252, which can't encode characters like "→".
"""
import re
import sys
from pathlib import Path


def notes_for(version: str) -> str:
    text = (Path(__file__).resolve().parent.parent / "CHANGELOG.md").read_text(encoding="utf-8")
    version = version.lstrip("v")
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.S | re.M)
    if not m or not m.group(1).strip():
        sys.exit(f"CHANGELOG.md has no entry for {version}. Add one before tagging the release.")
    return m.group(1).strip() + "\n"


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    notes = notes_for(sys.argv[1])
    if len(sys.argv) == 3:
        Path(sys.argv[2]).write_text(notes, encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(notes)
