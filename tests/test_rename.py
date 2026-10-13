"""The app was called Trackademic before 3.6.0: existing data and backups must carry over to EasyUniTrack."""
import importlib
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_app(monkeypatch, **env):
    for key in ("TRACKADEMIC_DATA_DIR", "LIFEPLANNER_DATA_DIR"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))
    import app
    return importlib.reload(app)


def test_backup_made_under_the_old_name_still_restores(tmp_path, monkeypatch):
    A = load_app(monkeypatch, TRACKADEMIC_DATA_DIR=tmp_path)
    c = TestClient(A.app)
    c.post("/api/tasks", json={"title": "Essay"})
    backup = c.get("/api/export").json()
    backup["app"] = "Trackademic"
    c.post("/api/tasks", json={"title": "Added later"})
    assert c.post("/api/import", json=backup).status_code == 200
    assert [t["title"] for t in c.get("/api/tasks").json()] == ["Essay"]


@pytest.mark.skipif(sys.platform == "darwin", reason="data root is under the real home folder on macOS")
def test_data_in_the_old_folder_is_copied_to_the_new_one(tmp_path, monkeypatch):
    # Every place the app could look for the user's data folder points into tmp_path
    for key in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(key, str(tmp_path))
    old = tmp_path / "Trackademic"
    A = load_app(monkeypatch, TRACKADEMIC_DATA_DIR=old)            # an existing Trackademic user
    TestClient(A.app).post("/api/tasks", json={"title": "From Trackademic"})

    monkeypatch.delenv("TRACKADEMIC_DATA_DIR")
    A = load_app(monkeypatch)                                       # first start after the update
    assert A.DB_PATH == tmp_path / "EasyUniTrack" / "planner.db"
    assert [t["title"] for t in TestClient(A.app).get("/api/tasks").json()] == ["From Trackademic"]
    with sqlite3.connect(old / "planner.db") as conn:               # the old folder is left as it was
        assert conn.execute("SELECT title FROM tasks").fetchall() == [("From Trackademic",)]
