#!/usr/bin/env python3
"""Build the Microsoft Store package (.msix) from the PyInstaller folder.

  pyinstaller --noconfirm EasyUniTrack.spec
  python tools/build_msix.py --identity-name 12345Publisher.EasyUniTrack ^
      --publisher "CN=XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX" --publisher-display-name "Inkpaw Studio"

The three values come from Partner Center > Apps > EasyUniTrack > Product management > Product identity.
Without them this builds a test package with a placeholder identity (fine for checking the packaging, not
for the Store). The Store signs the package for you, so no certificate is needed to submit it.

Output: dist/EasyUniTrack-<version>.msix  (needs makeappx.exe from the Windows SDK, present on GitHub's Windows runners)
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
PLACEHOLDER = {"identity_name": "EasyUniTrack.Dev", "publisher": "CN=EasyUniTrack Dev",
               "publisher_display_name": "EasyUniTrack Dev"}

# name -> (width, height) of each image the manifest refers to
ASSETS = {"StoreLogo": (50, 50), "Square44x44Logo": (44, 44), "Square71x71Logo": (71, 71),
          "Square150x150Logo": (150, 150), "Wide310x150Logo": (310, 150)}


PRE_RELEASES = {"alpha": 1, "beta": 2, "rc": 3}    # in the order they come before a release


def package_version(version: str) -> str:
    """MSIX versions are four numbers. The Store reserves the last one, so it must be 0.

    A pre-release (for a Store package flight) gets a number just below its release, because Partner Center
    refuses a second package with the same version, and flight testers only move on to a higher one. Its label
    and number go in the third part, so alpha < beta < rc < the release:
    4.0.0-beta.1 -> 3.9999.2001.0, 4.0.0-rc.1 -> 3.9999.3001.0, then 4.0.0 -> 4.0.0.0;
    4.1.0-beta.2 -> 4.0.62002.0, then 4.1.0 -> 4.1.0.0."""
    # Plain ASCII digits without leading zeros, so two spellings (beta.1, beta.01) can't make one package version
    num = r"(0|[1-9][0-9]*)"
    m = re.match(rf"^{num}\.{num}\.{num}(?:-(alpha|beta|rc)\.([1-9][0-9]*))?$", version.strip())
    if not m:
        if re.match(r"^[0-9]+\.[0-9]+\.[0-9]+-", version.strip()):
            sys.exit(f"Name the pre-release alpha, beta or rc with a number (no leading zeros), for example "
                     f"{version.split('-')[0]}-beta.1, to build it for the Store.")
        sys.exit(f"Can't turn '{version}' into a package version.")
    major, minor, patch = (int(x) for x in m.groups()[:3])
    if not m.group(4):
        result = f"{major}.{minor}.{patch}.0"
    else:
        rank, pre = PRE_RELEASES[m.group(4)], int(m.group(5))
        if pre > 999:
            sys.exit("A pre-release for the Store needs a number from 1 to 999, for example 4.0.0-beta.1.")
        if patch:
            sys.exit("Store flights are for new major or minor versions (4.0.0-beta.1, 4.1.0-beta.1), not patches.")
        if minor:
            result = f"{major}.{minor - 1}.{60000 + rank * 1000 + pre}.0"   # above any real patch of the minor before
        else:
            result = f"{major - 1}.9999.{rank * 1000 + pre}.0"              # above any real minor of the major before
    if int(result.split(".")[0]) < 1:                 # the Store needs the first number to be at least 1
        sys.exit(f"{version} would be package version {result}, but the Store needs the first number to be at least 1.")
    return result


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
    ap.add_argument("--app-dir", type=Path, default=ROOT / "dist" / "EasyUniTrack", help="the PyInstaller output folder")
    for key, default in PLACEHOLDER.items():
        ap.add_argument("--" + key.replace("_", "-"), default=default)
    args = ap.parse_args()

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    manifest = render_manifest(args.identity_name, args.publisher, args.publisher_display_name, version)
    if not (args.app_dir / "EasyUniTrack.exe").exists():
        sys.exit(f"{args.app_dir}\\EasyUniTrack.exe not found. Run: pyinstaller --noconfirm EasyUniTrack.spec")

    staging = ROOT / "build" / "msix"
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(args.app_dir, staging)
    (staging / "AppxManifest.xml").write_text(manifest, encoding="utf-8")
    make_assets(staging / "Assets")

    out = ROOT / "dist" / f"EasyUniTrack-{version}.msix"
    out.unlink(missing_ok=True)
    subprocess.run([find_makeappx(), "pack", "/d", str(staging), "/p", str(out), "/o"], check=True)
    print(f"Built {out} ({out.stat().st_size // 1024 // 1024} MB), identity {args.identity_name}")


if __name__ == "__main__":
    main()
