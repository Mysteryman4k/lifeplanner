#!/usr/bin/env python3
"""Build the Microsoft Store package (.msix) from the PyInstaller folder.

  pyinstaller --noconfirm Trackademic.spec
  python tools/build_msix.py --identity-name 12345Publisher.Trackademic ^
      --publisher "CN=XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX" --publisher-display-name "Inkpaw Studio"

The three values come from Partner Center > Apps > Trackademic > Product management > Product identity.
Without them this builds a test package with a placeholder identity (fine for checking the packaging, not
for the Store). The Store signs the package for you, so no certificate is needed to submit it.

Output: dist/Trackademic-<version>.msix  (needs makeappx.exe from the Windows SDK, present on GitHub's Windows runners)
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from string import Template
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER = {"identity_name": "Trackademic.Dev", "publisher": "CN=Trackademic Dev",
               "publisher_display_name": "Trackademic Dev"}

# name -> (width, height) of each image the manifest refers to
ASSETS = {"StoreLogo": (50, 50), "Square44x44Logo": (44, 44), "Square71x71Logo": (71, 71),
          "Square150x150Logo": (150, 150), "Wide310x150Logo": (310, 150)}


def package_version(version: str) -> str:
    """MSIX versions are four numbers. The Store reserves the last one, so it must be 0."""
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", version.strip())
    if not m:
        sys.exit(f"Can't turn '{version}' into a package version.")
    return ".".join(m.groups()) + ".0"


def render_manifest(identity_name: str, publisher: str, publisher_display_name: str, version: str) -> str:
    template = (ROOT / "msix" / "AppxManifest.xml.template").read_text(encoding="utf-8")
    values = {"IDENTITY_NAME": identity_name, "PUBLISHER": publisher,
              "PUBLISHER_DISPLAY_NAME": publisher_display_name, "PACKAGE_VERSION": package_version(version)}
    # the values sit inside "..." attributes or element text, so escape the characters XML cares about
    values = {k: escape(v, {'"': "&quot;"}) for k, v in values.items()}
    return Template(template).substitute(values)


def make_assets(folder: Path):
    from PIL import Image
    icon = Image.open(ROOT / "static" / "icon-512.png").convert("RGBA")
    folder.mkdir(parents=True, exist_ok=True)
    for name, (w, h) in ASSETS.items():
        side = min(w, h)
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        small = icon.resize((side, side), Image.LANCZOS)
        canvas.paste(small, ((w - side) // 2, (h - side) // 2), small)
        canvas.save(folder / f"{name}.png")


def find_makeappx() -> str:
    found = shutil.which("makeappx.exe")
    if found:
        return found
    kits = Path(r"C:\Program Files (x86)\Windows Kits\10\bin")
    candidates = sorted(kits.glob("*/x64/makeappx.exe"), reverse=True) if kits.exists() else []
    if not candidates:
        sys.exit("makeappx.exe not found. Install the Windows SDK (it ships with Visual Studio and GitHub's Windows runners).")
    return str(candidates[0])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app-dir", type=Path, default=ROOT / "dist" / "Trackademic", help="the PyInstaller output folder")
    for key, default in PLACEHOLDER.items():
        ap.add_argument("--" + key.replace("_", "-"), default=default)
    args = ap.parse_args()

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    manifest = render_manifest(args.identity_name, args.publisher, args.publisher_display_name, version)
    if not (args.app_dir / "Trackademic.exe").exists():
        sys.exit(f"{args.app_dir}\\Trackademic.exe not found. Run: pyinstaller --noconfirm Trackademic.spec")

    staging = ROOT / "build" / "msix"
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(args.app_dir, staging)
    (staging / "AppxManifest.xml").write_text(manifest, encoding="utf-8")
    make_assets(staging / "Assets")

    out = ROOT / "dist" / f"Trackademic-{version}.msix"
    out.unlink(missing_ok=True)
    subprocess.run([find_makeappx(), "pack", "/d", str(staging), "/p", str(out), "/o"], check=True)
    print(f"Built {out} ({out.stat().st_size // 1024 // 1024} MB), identity {args.identity_name}")


if __name__ == "__main__":
    main()
