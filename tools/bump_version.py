#!/usr/bin/env python3
"""Bump the app version and start a changelog entry.

  python tools/bump_version.py patch      3.2.0 -> 3.2.1   (bug fixes)
  python tools/bump_version.py minor      3.2.0 -> 3.3.0   (new features)
  python tools/bump_version.py major      3.2.0 -> 4.0.0   (big changes)
  python tools/bump_version.py 3.4.0      set an exact version

Then fill in CHANGELOG.md, commit, and publish with:
  git tag v<version> && git push origin main --tags
"""
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
CHANGELOG = ROOT / "CHANGELOG.md"


def bump(current: str, part: str) -> str:
    major, minor, patch = (int(x) for x in current.split("-")[0].split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?", part):
        return part
    sys.exit(f"Unknown version part: {part!r} (use major, minor, patch or an exact version)")


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    current = VERSION_FILE.read_text().strip()
    new = bump(current, sys.argv[1])
    VERSION_FILE.write_text(new + "\n")
    text = CHANGELOG.read_text(encoding="utf-8")
    entry = f"## [{new}] - {date.today().isoformat()}\n\n### Added\n\n- \n\n### Fixed\n\n- \n\n"
    text = text.replace("## [Unreleased]\n\n", f"## [Unreleased]\n\n{entry}", 1)
    CHANGELOG.write_text(text, encoding="utf-8")
    print(f"Version {current} -> {new}")
    print("Next: fill in CHANGELOG.md, then")
    print(f'  git commit -am "Release v{new}" && git tag v{new} && git push origin main --tags')


if __name__ == "__main__":
    main()
