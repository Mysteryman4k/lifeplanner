"""Version handling and the update checker (GitHub is mocked — no network needed)."""
import hashlib
import importlib
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import updater  # noqa: E402


def test_version_file_is_semver():
    v = (ROOT / "VERSION").read_text().strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?", v), v


def test_changelog_has_entry_for_current_version():
    v = (ROOT / "VERSION").read_text().strip()
    assert f"## [{v}]" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("latest,current,newer", [
    ("3.2.1", "3.2.0", True), ("v3.10.0", "3.9.9", True), ("4.0.0", "3.99.99", True),
    ("3.2.0", "3.2.0", False), ("3.1.9", "3.2.0", False),
    ("3.2.0", "3.2.0-beta.1", True), ("3.2.0-beta.1", "3.2.0", False), ("garbage", "3.2.0", False),
])
def test_is_newer(latest, current, newer):
    assert updater.is_newer(latest, current) is newer


def fake_release(version, with_installer=True):
    assets = {}
    if with_installer:
        assets[f"Trackademic-Setup-{version}.exe"] = f"https://github.com/x/y/releases/download/v{version}/setup.exe"
        assets["SHA256SUMS.txt"] = f"https://github.com/x/y/releases/download/v{version}/SHA256SUMS.txt"
    return {"version": version, "name": f"v{version}", "notes": "- New stuff", "url": "https://github.com/x/y/releases",
            "published_at": "2026-10-06T00:00:00Z", "assets": assets}


def test_check_reports_available_update(monkeypatch):
    monkeypatch.setattr(updater, "_cache", {"at": 0.0, "data": None})
    r = updater.check("3.2.0", force=True, fetch=lambda: fake_release("3.3.0"))
    assert r["available"] and r["latest"] == "3.3.0" and r["notes"] == "- New stuff"
    assert r["can_install"] is False          # tests don't run as the packaged Windows app


def test_check_survives_being_offline(monkeypatch):
    monkeypatch.setattr(updater, "_cache", {"at": 0.0, "data": None})
    def boom():
        raise OSError("no network")
    r = updater.check("3.2.0", force=True, fetch=boom)
    assert r["available"] is False and "error" in r


def test_downloads_only_from_github():
    with pytest.raises(ValueError):
        updater._get("https://evil.example.com/Trackademic-Setup.exe")
    with pytest.raises(ValueError):
        updater._get("http://github.com/insecure")


def test_installer_checksum_is_verified(monkeypatch):
    rel = fake_release("3.3.0")
    good = b"installer bytes"
    sums = f"{hashlib.sha256(good).hexdigest()}  Trackademic-Setup-3.3.0.exe\n".encode()
    files = {rel["assets"]["SHA256SUMS.txt"]: sums, rel["assets"]["Trackademic-Setup-3.3.0.exe"]: good}
    monkeypatch.setattr(updater, "_get", lambda url, timeout=8.0: files[url])
    assert updater.download_installer(rel).read_bytes() == good

    files[rel["assets"]["Trackademic-Setup-3.3.0.exe"]] = b"tampered"
    with pytest.raises(ValueError, match="checksum"):
        updater.download_installer(rel)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACKADEMIC_DATA_DIR", str(tmp_path))
    import app as A
    importlib.reload(A)
    monkeypatch.setattr(updater, "_cache", {"at": 0.0, "data": None})
    monkeypatch.setattr(updater, "fetch_latest", lambda: fake_release("99.0.0"))
    return TestClient(A.app), A


def test_update_endpoints(client):
    c, A = client
    assert c.get("/api/info").json()["version"] == (ROOT / "VERSION").read_text().strip()
    r = c.get("/api/update/check", params={"force": True}).json()
    assert r["available"] and r["latest"] == "99.0.0"
    # Turning off automatic checks stops background checks but not "Check now"
    assert c.put("/api/settings/updates", json={"auto_check": False}).status_code == 200
    assert c.get("/api/update/check").json().get("disabled") is True
    assert c.get("/api/update/check", params={"force": True}).json()["available"] is True
    # Self-install is refused outside the packaged Windows app
    assert c.post("/api/update/install").status_code == 400
