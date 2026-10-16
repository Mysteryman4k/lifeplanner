"""The portable zip must start even though Windows marks every unzipped file as downloaded: .NET (used by the
window) is loaded with EasyUniTrack's config, which allows its own marked DLLs. 4.0.0-beta.1's portable zip crashed
at start without it. The real check runs in CI: tools/mark_downloaded.py, then the start-up smoke test."""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import desktop  # noqa: E402


def fake_pythonnet(monkeypatch, fail=None):
    calls = []

    def load(runtime, **params):
        if fail:
            raise fail
        calls.append((runtime, params))
    monkeypatch.setitem(sys.modules, "pythonnet", types.SimpleNamespace(load=load))
    return calls


def test_the_config_allows_the_apps_own_downloaded_dlls():
    config = (ROOT / desktop.DOTNET_CONFIG).read_text(encoding="utf-8")
    assert '<loadFromRemoteSources enabled="true" />' in config
    assert f"('{desktop.DOTNET_CONFIG}', '.')" in (ROOT / "EasyUniTrack.spec").read_text(encoding="utf-8")   # bundled


def test_the_packaged_app_loads_dotnet_with_it(monkeypatch, tmp_path):
    (tmp_path / desktop.DOTNET_CONFIG).write_text("<configuration/>")
    calls = fake_pythonnet(monkeypatch)
    desktop.prepare_dotnet(windows=True, frozen=True, bundle=tmp_path)
    assert calls == [("netfx", {"domain": "EasyUniTrack", "config_file": str(tmp_path / desktop.DOTNET_CONFIG)})]


def test_only_the_packaged_windows_app(monkeypatch, tmp_path):
    (tmp_path / desktop.DOTNET_CONFIG).write_text("<configuration/>")
    calls = fake_pythonnet(monkeypatch)
    desktop.prepare_dotnet(windows=False, frozen=True, bundle=tmp_path)     # macOS and Linux don't use .NET
    desktop.prepare_dotnet(windows=True, frozen=False, bundle=tmp_path)     # running from source
    assert calls == []


def test_problems_are_logged_not_fatal(monkeypatch, tmp_path, capsys):
    calls = fake_pythonnet(monkeypatch)
    desktop.prepare_dotnet(windows=True, frozen=True, bundle=tmp_path)      # the config is missing
    assert calls == [] and "is missing" in capsys.readouterr().out
    (tmp_path / desktop.DOTNET_CONFIG).write_text("<configuration/>")
    fake_pythonnet(monkeypatch, fail=RuntimeError("no .NET Framework"))
    desktop.prepare_dotnet(windows=True, frozen=True, bundle=tmp_path)      # pywebview then tries by itself
    assert "couldn't prepare .NET" in capsys.readouterr().out


def test_mark_downloaded_marks_every_file(tmp_path):
    if sys.platform != "win32":
        import pytest
        pytest.skip("alternate data streams are an NTFS feature")
    import subprocess
    src = tmp_path / "app"
    (src / "_internal").mkdir(parents=True)
    (src / "a.exe").write_bytes(b"x")
    (src / "_internal" / "b.dll").write_bytes(b"y")
    subprocess.run([sys.executable, str(ROOT / "tools" / "mark_downloaded.py"), str(src), str(tmp_path / "out")], check=True)
    for f in ("a.exe", "_internal/b.dll"):
        assert "ZoneId=3" in open(f"{tmp_path / 'out' / f}:Zone.Identifier", encoding="ascii").read()
