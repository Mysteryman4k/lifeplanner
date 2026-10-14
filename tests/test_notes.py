"""v4 stage 3: notes inside subjects, notes in backups, and the pre-upgrade backup."""
import importlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACKADEMIC_DATA_DIR", str(tmp_path))
    import app
    return importlib.reload(app)


@pytest.fixture()
def A(tmp_path, monkeypatch):
    return load(tmp_path, monkeypatch)


@pytest.fixture()
def c(A):
    return TestClient(A.app)


def subject(c, name="Data Structures"):
    return c.post("/api/subjects", json={"name": name, "color": "#3B6EA8"}).json()


def test_notes_crud(c):
    s = subject(c)
    n = c.post("/api/notes", json={"title": "  Dijkstra  ", "body": "## Steps\n- pick the closest", "subject_id": s["id"]}).json()
    assert n["title"] == "Dijkstra" and n["source"] == "manual" and n["subject_id"] == s["id"]
    assert [x["id"] for x in c.get(f"/api/notes?subject_id={s['id']}").json()] == [n["id"]]
    u = c.put(f"/api/notes/{n['id']}", json={"body": "updated"}).json()
    assert u["body"] == "updated" and u["title"] == "Dijkstra"
    assert c.delete(f"/api/notes/{n['id']}").status_code == 200
    assert c.get("/api/notes").json() == []
    assert c.put(f"/api/notes/{n['id']}", json={"body": "x"}).status_code == 404


@pytest.mark.parametrize("body,status", [
    ({"title": "   "}, 422), ({"title": "x" * 201}, 422), ({"title": "ok", "subject_id": 999}, 400),
    ({"title": "ok", "task_id": 999}, 400), ({"title": "ok", "source": "robot"}, 422),
])
def test_note_validation(c, body, status):
    assert c.post("/api/notes", json=body).status_code == status


def test_a_title_cant_be_blanked(c):
    n = c.post("/api/notes", json={"title": "Keep me"}).json()
    assert c.put(f"/api/notes/{n['id']}", json={"title": "  "}).status_code in (400, 422)


def test_deleting_a_subject_or_task_keeps_its_notes(c):
    s = subject(c)
    t = c.post("/api/tasks", json={"title": "Lab"}).json()
    n = c.post("/api/notes", json={"title": "From chat", "subject_id": s["id"], "task_id": t["id"], "source": "chat"}).json()
    c.delete(f"/api/subjects/{s['id']}")
    c.delete(f"/api/tasks/{t['id']}")
    kept = c.get("/api/notes").json()
    assert [(x["id"], x["subject_id"], x["task_id"]) for x in kept] == [(n["id"], None, None)]


def test_notes_are_in_backups_and_restore(c):
    s = subject(c)
    c.post("/api/notes", json={"title": "Heaps", "body": "a tree", "subject_id": s["id"]})
    backup = c.get("/api/export").json()
    assert [n["title"] for n in backup["notes"]] == ["Heaps"]
    assert all(r["key"] != "last_run_version" for r in backup["settings"])        # belongs to this PC
    c.post("/api/notes", json={"title": "Added later"})
    assert c.post("/api/import", json=backup).status_code == 200
    assert [n["title"] for n in c.get("/api/notes").json()] == ["Heaps"]


def test_an_older_backup_without_notes_still_restores(c):
    c.post("/api/notes", json={"title": "Mine"})
    backup = c.get("/api/export").json()
    backup.pop("notes")                                       # as made by 3.x
    assert c.post("/api/import", json=backup).status_code == 200
    assert c.get("/api/notes").json() == []


# ── pre-upgrade backup ──

def backups(tmp_path):
    return sorted(p.name for p in (tmp_path / "backups").glob("before-upgrade-*.db")) if (tmp_path / "backups").exists() else []


def test_a_fresh_install_makes_no_upgrade_backup(tmp_path, monkeypatch):
    load(tmp_path, monkeypatch)
    assert backups(tmp_path) == []


def test_upgrading_keeps_a_copy_of_the_data_as_it_was(tmp_path, monkeypatch):
    A = load(tmp_path, monkeypatch)
    TestClient(A.app).post("/api/tasks", json={"title": "Made in the old version"})
    with sqlite3.connect(tmp_path / "planner.db") as conn:          # pretend an older version ran last
        conn.execute("UPDATE settings SET value=? WHERE key='last_run_version'", (json.dumps("3.5.2"),))
    load(tmp_path, monkeypatch)                                     # the new version starts
    made = backups(tmp_path)
    assert len(made) == 1
    with sqlite3.connect(tmp_path / "backups" / made[0]) as conn:
        assert conn.execute("SELECT title FROM tasks").fetchall() == [("Made in the old version",)]
        assert json.loads(conn.execute("SELECT value FROM settings WHERE key='last_run_version'").fetchone()[0]) == "3.5.2"
    load(tmp_path, monkeypatch)                                     # same version again: no new copy
    assert len(backups(tmp_path)) == 1


def test_upgrading_from_a_version_that_didnt_record_itself(tmp_path, monkeypatch):
    """3.x never stored last_run_version: its data still gets a copy on the first 4.0 start."""
    A = load(tmp_path, monkeypatch)
    TestClient(A.app).post("/api/tasks", json={"title": "Old"})
    with sqlite3.connect(tmp_path / "planner.db") as conn:
        conn.execute("DELETE FROM settings WHERE key='last_run_version'")
    load(tmp_path, monkeypatch)
    assert len(backups(tmp_path)) == 1


def test_old_upgrade_backups_are_pruned(A, tmp_path):
    folder = tmp_path / "backups"
    folder.mkdir(exist_ok=True)
    for i in range(14):
        (folder / f"before-upgrade-2026-01-{i + 1:02d}_120000.db").write_bytes(b"x")
    A.auto_backup()
    assert len(list(folder.glob("before-upgrade-*.db"))) == A.KEEP_AUTO_BACKUPS
