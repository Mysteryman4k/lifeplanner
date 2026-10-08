"""Checks that only mean something on real Windows (run by CI on windows-latest; skipped elsewhere)."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows only")

import reminders  # noqa: E402
import system_integration  # noqa: E402


def test_notification_script_runs_on_windows():
    """Loads the Windows notification APIs, builds the toast and its notifier; everything but showing it."""
    assert reminders._windows_toast("Tom & Jerry <b>", "Line 1\nLine 2 'quoted' @", reminders.APP_ID, dry_run=True)


def test_start_with_windows_round_trip(monkeypatch, tmp_path):
    import winreg
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "Trackademic.exe"))

    def current():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, system_integration.RUN_KEY) as key:
                return winreg.QueryValueEx(key, system_integration.RUN_VALUE)[0]
        except OSError:
            return None

    before = current()
    try:
        assert system_integration.autostart_supported()
        assert system_integration.set_autostart(True) is True
        assert current() == f'"{tmp_path / "Trackademic.exe"}" --minimized'
        assert system_integration.set_autostart(False) is False
        assert current() is None
        assert system_integration.set_autostart(False) is False        # turning off twice is fine
    finally:
        if before is not None:                                          # leave the machine as it was
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, system_integration.RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, system_integration.RUN_VALUE, 0, winreg.REG_SZ, before)


def test_suggested_currency_reads_the_windows_region():
    import app
    assert len(app.suggested_currency()) == 3
