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
    monkeypatch.setattr(sys, "executable", str(tmp_path / "EasyUniTrack.exe"))

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
        assert current() == f'"{tmp_path / "EasyUniTrack.exe"}" --minimized'
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


def test_start_with_windows_moves_over_from_the_old_name(monkeypatch, tmp_path):
    """Updating from Trackademic: an old "Start with Windows" entry becomes an EasyUniTrack one."""
    import winreg
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "EasyUniTrack.exe"))
    names = (system_integration.RUN_VALUE, *system_integration.OLD_RUN_VALUES)

    def read(name):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, system_integration.RUN_KEY) as key:
                return winreg.QueryValueEx(key, name)[0]
        except OSError:
            return None

    def write(name, value):
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, system_integration.RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if value is None:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    before = {name: read(name) for name in names}                  # this machine's real entries
    try:
        write("Trackademic", r'"C:\old\Trackademic.exe" --minimized')
        write(system_integration.RUN_VALUE, None)
        system_integration.migrate_autostart()
        assert read("Trackademic") is None
        assert read(system_integration.RUN_VALUE) == f'"{tmp_path / "EasyUniTrack.exe"}" --minimized'

        write(system_integration.RUN_VALUE, None)                   # it was off: stays off
        system_integration.migrate_autostart()
        assert read(system_integration.RUN_VALUE) is None
    finally:
        for name, value in before.items():                          # leave the machine as it was
            write(name, value)
