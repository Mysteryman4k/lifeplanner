"""Microsoft Store build: Store mode switches off the updater, and the package manifest is valid."""
import importlib
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


def test_store_build_api(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACKADEMIC_DATA_DIR", str(tmp_path))          # never touch the real data folder
    monkeypatch.setenv("TRACKADEMIC_STORE", "1")
    import app
    importlib.reload(app)
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
    assert app.get("Id") == store.APP_ENTRY_ID and app.get("Executable") == "EasyUniTrack.exe"
    assert app.find(".//d:StartupTask", ns).get("TaskId") == store.STARTUP_TASK_ID


def test_manifest_images_are_all_listed():
    b = load_builder()
    manifest = b.render_manifest("A.B", "CN=A", "A", "3.5.2")
    for name in b.ASSETS:
        assert f"Assets\\{name}.png" in manifest, name


def test_store_mode_never_enables_autostart_for_source_runs(monkeypatch):
    import system_integration
    monkeypatch.setenv("TRACKADEMIC_STORE", "1")
    monkeypatch.delattr(sys, "frozen", raising=False)
    called = []
    monkeypatch.setattr(store, "startup_supported", lambda: called.append(1) or True)
    assert system_integration.autostart_supported() is False
    assert system_integration.set_autostart(True) is False
    assert not called                                  # the Store path isn't even tried


def test_not_a_sign_in_launch_outside_the_store(monkeypatch):
    monkeypatch.setenv("TRACKADEMIC_STORE", "0")
    assert store.launched_at_sign_in() is False


@pytest.mark.parametrize("version,expected", [
    ("3.5.2", "3.5.2.0"), ("4.0.0", "4.0.0.0"),
    # A pre-release for a Store flight sits just below its release: Partner Center refuses a repeated version,
    # and testers only move on to a higher one. The label and number are in the third part
    ("4.0.0-beta.1", "3.9999.2001.0"), ("4.0.0-beta.12", "3.9999.2012.0"), ("4.0.0-rc.1", "3.9999.3001.0"),
    ("4.0.0-alpha.3", "3.9999.1003.0"), ("4.1.0-rc.2", "4.0.63002.0"),
])
def test_package_version(version, expected):
    assert load_builder().package_version(version) == expected


def test_pre_release_package_versions_sort_between_the_releases():
    b = load_builder()
    order = ["3.6.1", "3.99.0", "4.0.0-alpha.1", "4.0.0-beta.1", "4.0.0-beta.2", "4.0.0-beta.999", "4.0.0-rc.1",
             "4.0.0-rc.2", "4.0.0", "4.0.5", "4.1.0-beta.1", "4.1.0-rc.1", "4.1.0", "5.0.0-beta.1", "5.0.0"]
    numbers = [tuple(int(x) for x in b.package_version(v).split(".")) for v in order]
    assert numbers == sorted(numbers) and len(set(numbers)) == len(numbers)       # beta then rc: never the same
    assert all(0 <= n <= 65535 for v in numbers for n in v)


@pytest.mark.parametrize("version", [
    "4.0.0-beta", "4.0.0-preview.1", "4.0.1-beta.1", "4.0.0-beta.0", "4.0.0-beta.1000", "four",
    "4.0.0-beta.01", "04.0.0", "4.0.0-beta.١",           # one spelling per version: no leading zeros, ASCII digits
    "0.5.0", "1.0.0-beta.1", "0.1.0-beta.1", "0.0.0-beta.1",  # the Store needs the first number to be at least 1
])
def test_versions_the_store_cant_take(version):
    with pytest.raises(SystemExit):
        load_builder().package_version(version)


class _WindowCreated(Exception):
    pass


@pytest.mark.parametrize("sign_in,argv,expected", [
    (True, [], True),                     # Store startup task at sign-in
    (False, ["--minimized"], True),       # Run key at sign-in (GitHub version)
    (False, [], False),                   # opened normally
])
def test_desktop_starts_minimised_when_windows_opens_it_at_sign_in(tmp_path, monkeypatch, sign_in, argv, expected):
    monkeypatch.setenv("TRACKADEMIC_DATA_DIR", str(tmp_path))
    import types

    import app
    importlib.reload(app)
    import desktop
    import system_integration
    monkeypatch.setattr(sys, "argv", ["EasyUniTrack.exe", *argv])
    monkeypatch.setattr(store, "launched_at_sign_in", lambda: sign_in)
    # Keep main() from starting anything real: no server, no lock file, no background jobs
    monkeypatch.setattr(desktop, "set_windows_app_id", lambda: None)
    monkeypatch.setattr(desktop, "start_server", lambda port: None)
    monkeypatch.setattr(system_integration, "find_running_instance", lambda *a: None)
    monkeypatch.setattr(system_integration, "claim_instance", lambda *a: None)
    monkeypatch.setattr(app, "auto_backup", lambda: None)
    monkeypatch.setattr(app, "start_reminders", lambda: None)
    created = {}

    def create_window(**kwargs):
        created.update(kwargs)
        raise _WindowCreated

    monkeypatch.setitem(sys.modules, "webview", types.SimpleNamespace(settings={}, create_window=create_window))
    with pytest.raises(_WindowCreated):
        desktop.main()
    assert created["minimized"] is expected
