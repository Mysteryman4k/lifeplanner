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
    """Updating from Trackademic: an old "Start with Windows" entry becomes an EasyUniTrack one,
    unless the user had switched it off in Task Manager."""
    import winreg
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "EasyUniTrack.exe"))
    monkeypatch.delenv("TRACKADEMIC_DATA_DIR", raising=False)       # only real (non-test) runs move it
    run, approved = system_integration.RUN_KEY, system_integration.APPROVED_KEY
    names = (system_integration.RUN_VALUE, *system_integration.OLD_RUN_VALUES)

    def read(subkey, name):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as key:
                return winreg.QueryValueEx(key, name)
        except OSError:
            return None

    def write(subkey, name, value):                                 # value: (data, type) or None to delete
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_SET_VALUE) as key:
            if value is None:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(key, name, 0, value[1], value[0])

    old_entry = (r'"C:\old\Trackademic.exe" --minimized', winreg.REG_SZ)
    disabled = (bytes([3]) + bytes(11), winreg.REG_BINARY)          # how Task Manager marks "Disabled"
    before = {(k, n): read(k, n) for k in (run, approved) for n in names}   # this machine's real entries
    try:
        for k, n in before:
            write(k, n, None)
        write(run, "Trackademic", old_entry)
        monkeypatch.setenv("TRACKADEMIC_DATA_DIR", str(tmp_path))
        system_integration.migrate_autostart()                      # a test run never touches it
        assert read(run, "Trackademic")[0] == old_entry[0] and read(run, system_integration.RUN_VALUE) is None
        monkeypatch.delenv("TRACKADEMIC_DATA_DIR")

        system_integration.migrate_autostart()                      # was on: moves to the new name
        assert read(run, "Trackademic") is None
        assert read(run, system_integration.RUN_VALUE)[0] == f'"{tmp_path / "EasyUniTrack.exe"}" --minimized'

        write(run, system_integration.RUN_VALUE, None)              # was off: stays off
        system_integration.migrate_autostart()
        assert read(run, system_integration.RUN_VALUE) is None

        write(run, "Trackademic", old_entry)                        # switched off in Task Manager: stays off
        write(approved, "Trackademic", disabled)
        system_integration.migrate_autostart()
        assert read(run, "Trackademic") is None and read(approved, "Trackademic") is None
        assert read(run, system_integration.RUN_VALUE) is None
    finally:
        for (k, n), value in before.items():                        # leave the machine as it was
            write(k, n, value)
