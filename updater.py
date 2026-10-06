"""
Update checks against GitHub Releases.

How releases work:
  1. Bump the version (python tools/bump_version.py minor) and push a tag like v3.2.0.
  2. The "Release" GitHub Action builds Trackademic-Setup-<version>.exe, a portable zip
     and SHA256SUMS.txt, and publishes them as a GitHub Release.
  3. Installed copies check the latest release (at most every few hours, can be turned off),
     and on Windows can download the installer, verify its checksum and run it silently.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

UPDATE_REPO = os.environ.get("TRACKADEMIC_UPDATE_REPO", "Mysteryman4k/lifeplanner")
API_URL = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
CHECK_INTERVAL = 6 * 3600          # seconds between automatic checks
# Only download from GitHub's own hosts
ALLOWED_HOSTS = {"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com",
                 "api.github.com"}

_cache = {"at": 0.0, "data": None}
_lock = threading.Lock()


def parse_version(v: str):
    """'v3.2.0' -> (3, 2, 0). Pre-release suffixes (3.2.0-beta.1) sort before the final release."""
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$", (v or "").strip())
    if not m:
        return None
    major, minor, patch, pre = m.groups()
    return (int(major), int(minor), int(patch), 0 if pre else 1, pre or "")


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return bool(a and b and a > b)


def is_installed_build() -> bool:
    """True for the packaged Windows app (the only build that can update itself)."""
    return bool(getattr(sys, "frozen", False)) and os.name == "nt"


def _get(url: str, timeout: float = 8.0) -> bytes:
    host = urlparse(url).hostname or ""
    if urlparse(url).scheme != "https" or host not in ALLOWED_HOSTS:
        raise ValueError(f"Refusing to download from {host or url}")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Trackademic-updater", "Accept": "application/vnd.github+json, application/octet-stream"})
    with urllib.request.urlopen(req, timeout=timeout) as r:      # redirects to GitHub's CDN are followed
        final_host = urlparse(r.geturl()).hostname or ""
        if final_host not in ALLOWED_HOSTS:
            raise ValueError(f"Download redirected to an unexpected host: {final_host}")
        return r.read()


def fetch_latest() -> dict:
    data = json.loads(_get(API_URL))
    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    return {
        "version": (data.get("tag_name") or "").lstrip("v"),
        "name": data.get("name") or data.get("tag_name"),
        "notes": (data.get("body") or "").strip(),
        "url": data.get("html_url"),
        "published_at": data.get("published_at"),
        "assets": assets,
    }


def check(current_version: str, force: bool = False, fetch=None) -> dict:
    """Latest release info compared with the running version. Cached between checks."""
    fetch = fetch or fetch_latest
    with _lock:
        fresh = _cache["data"] is not None and time.time() - _cache["at"] < CHECK_INTERVAL
        if force or not fresh:
            try:
                _cache["data"] = fetch()
                _cache["error"] = None
            except Exception as e:                                # offline, rate-limited, no releases yet
                _cache["error"] = str(e)
                if _cache["data"] is None:
                    return {"current": current_version, "available": False,
                            "error": "Couldn't reach GitHub to check for updates."}
            _cache["at"] = time.time()
        latest = _cache["data"]
    available = is_newer(latest["version"], current_version)
    installer = installer_asset(latest)
    return {
        "current": current_version,
        "latest": latest["version"],
        "available": available,
        "notes": latest["notes"][:4000],
        "url": latest["url"],
        "published_at": latest["published_at"],
        "can_install": available and is_installed_build() and installer is not None,
    }


def installer_asset(latest: dict):
    name = f"Trackademic-Setup-{latest['version']}.exe"
    return (name, latest["assets"][name]) if name in latest["assets"] else None


def download_installer(latest: dict) -> Path:
    """Download the installer and check it against SHA256SUMS.txt from the same release."""
    asset = installer_asset(latest)
    if not asset or "SHA256SUMS.txt" not in latest["assets"]:
        raise ValueError("This release doesn't include an installer and checksum file.")
    name, url = asset
    sums = _get(latest["assets"]["SHA256SUMS.txt"]).decode()
    expected = next((line.split()[0].lower() for line in sums.splitlines()
                     if line.strip().endswith(name)), None)
    if not expected:
        raise ValueError("The checksum for the installer is missing.")
    blob = _get(url, timeout=120)
    if hashlib.sha256(blob).hexdigest() != expected:
        raise ValueError("The downloaded installer failed its checksum, so it wasn't run.")
    path = Path(tempfile.gettempdir()) / name
    path.write_bytes(blob)
    return path


def run_installer(path: Path):
    """Start the installer detached; it closes this app, updates it and starts it again."""
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     creationflags=flags, close_fds=True)


def latest_cached():
    return _cache["data"]
