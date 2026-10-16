"""The portable zip must start in its own window even though Windows marks every unzipped file as downloaded.
The window runs on .NET Framework, which won't load a marked DLL unless EasyUniTrack.exe.config (next to the exe)
allows it. 4.0.0-beta.1's portable zip crashed at start without it. The real check runs in CI:
tools/mark_downloaded.py, then the start-up smoke test, which fails if the app had to open in the browser."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import desktop  # noqa: E402


def test_the_exe_config_allows_the_apps_own_downloaded_dlls():
    import xml.etree.ElementTree as ET
    config = ET.parse(ROOT / "EasyUniTrack.exe.config").getroot()      # must be valid XML, or .NET ignores it
    assert config.tag == "configuration"
    assert config.find("runtime/loadFromRemoteSources").get("enabled") == "true"
    spec = (ROOT / "EasyUniTrack.spec").read_text(encoding="utf-8")
    assert "name='EasyUniTrack'," in spec                      # .NET reads <exe name>.config, so the names match
    # copied next to the exe (not into _internal, where .NET doesn't look)
    assert "os.path.join(DISTPATH, 'EasyUniTrack', 'EasyUniTrack.exe.config')" in spec


def test_the_browser_fallback_is_recorded_so_the_start_up_test_fails(monkeypatch):
    import app
    opened = []
    monkeypatch.setattr(desktop, "wait_until_ready", lambda url: True)
    monkeypatch.setattr(desktop, "run_in_browser", opened.append)
    monkeypatch.setitem(app.STARTUP, "window", None)
    monkeypatch.setitem(app.WINDOW, "show", None)
    monkeypatch.setitem(app.WINDOW, "pick_folder", lambda: "C:/from/the/failed/window")
    assert app.get_startup_status()["window"] is None
    desktop.fall_back_to_browser("http://127.0.0.1:1/", "the window couldn't start (test)")
    assert opened == ["http://127.0.0.1:1/"]
    assert app.get_startup_status()["window"] == "browser"      # tools/smoke_desktop.py fails on this
    assert app.WINDOW["show"]                                   # opening EasyUniTrack again opens the tab again
    assert app.WINDOW["pick_folder"] is None                    # folder paths are typed instead


def test_the_fallback_says_why_it_can_not_open(monkeypatch, capsys):
    import app
    monkeypatch.setattr(desktop, "wait_until_ready", lambda url: False)
    monkeypatch.setattr(desktop, "run_in_browser", lambda url: pytest.fail("opened a browser with no server"))
    monkeypatch.setitem(app.STARTUP, "window", None)
    monkeypatch.setitem(app.WINDOW, "show", None)
    monkeypatch.setitem(app.WINDOW, "pick_folder", None)
    with pytest.raises(SystemExit):
        desktop.fall_back_to_browser("http://127.0.0.1:1/", "the window couldn't start (test)")
    out = capsys.readouterr().out
    assert "the window couldn't start (test)" in out and "didn't start within 30 seconds" in out


def test_mark_downloaded_marks_every_file(tmp_path):
    if sys.platform != "win32":
        pytest.skip("alternate data streams are an NTFS feature")
    import subprocess
    src = tmp_path / "app"
    (src / "_internal").mkdir(parents=True)
    (src / "a.exe").write_bytes(b"x")
    (src / "_internal" / "b.dll").write_bytes(b"y")
    subprocess.run([sys.executable, str(ROOT / "tools" / "mark_downloaded.py"), str(src), str(tmp_path / "out")], check=True)
    for f in ("a.exe", "_internal/b.dll"):
        assert "ZoneId=3" in open(f"{tmp_path / 'out' / f}:Zone.Identifier", encoding="ascii").read()
