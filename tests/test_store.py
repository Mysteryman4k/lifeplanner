"""Microsoft Store build: Store mode switches off the updater, and the package manifest is valid."""
import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import store  # noqa: E402
import updater  # noqa: E402


def load_builder():
    spec = importlib.util.spec_from_file_location("build_msix", ROOT / "tools" / "build_msix.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_store_mode_can_be_forced(monkeypatch):
    monkeypatch.setenv("TRACKADEMIC_STORE", "1")
    assert store.is_store_build() is True
    monkeypatch.setenv("TRACKADEMIC_STORE", "0")
    assert store.is_store_build() is False


def test_normal_builds_are_not_store_builds(monkeypatch):
    monkeypatch.delenv("TRACKADEMIC_STORE", raising=False)
    assert store.is_store_build() is False             # not frozen / not packaged


def test_store_build_leaves_updates_to_the_store(monkeypatch):
    monkeypatch.setenv("TRACKADEMIC_STORE", "1")
    called = []
    result = updater.check("3.5.2", force=True, fetch=lambda: called.append(1))
    assert result == {"current": "3.5.2", "available": False, "store_managed": True}
    assert not called                                  # never even asks GitHub


def test_store_build_api(monkeypatch):
    monkeypatch.setenv("TRACKADEMIC_STORE", "1")
    import app
    c = TestClient(app.app)
    assert c.get("/api/info").json()["store"] is True
    assert c.get("/api/update/check?force=true").json()["store_managed"] is True
    assert c.post("/api/update/install").status_code == 400


def test_manifest_is_valid_and_matches_the_code():
    b = load_builder()
    xml = b.render_manifest('Inkpaw.Track"ademic', "CN=ABC & Co", "Inkpaw <Studio>", "3.5.2")
    root = ET.fromstring(xml)                          # escaping worked, so it still parses
    ns = {"m": "http://schemas.microsoft.com/appx/manifest/foundation/windows10",
          "d": "http://schemas.microsoft.com/appx/manifest/desktop/windows10"}
    ident = root.find("m:Identity", ns)
    assert ident.get("Name") == 'Inkpaw.Track"ademic' and ident.get("Publisher") == "CN=ABC & Co"
    assert ident.get("Version") == "3.5.2.0"
    assert root.find("m:Properties/m:PublisherDisplayName", ns).text == "Inkpaw <Studio>"
    app = root.find("m:Applications/m:Application", ns)
    assert app.get("Id") == store.APP_ENTRY_ID and app.get("Executable") == "Trackademic.exe"
    assert app.find(".//d:StartupTask", ns).get("TaskId") == store.STARTUP_TASK_ID


def test_manifest_images_are_all_listed():
    b = load_builder()
    manifest = b.render_manifest("A.B", "CN=A", "A", "3.5.2")
    for name in b.ASSETS:
        assert f"Assets\\{name}.png" in manifest, name


@pytest.mark.parametrize("version,expected", [("3.5.2", "3.5.2.0"), ("4.0.0-beta.1", "4.0.0.0")])
def test_package_version(version, expected):
    assert load_builder().package_version(version) == expected
