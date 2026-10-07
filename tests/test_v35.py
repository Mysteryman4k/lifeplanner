"""Tests for 3.5.0: repeating tasks, task types, restore from backup, reminders, start with Windows."""
import datetime as dt
import importlib
import os
import sqlite3
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import reminders  # noqa: E402
import system_integration  # noqa: E402


@pytest.fixture()
def A(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACKADEMIC_DATA_DIR", str(tmp_path))
    import app
    importlib.reload(app)
    return app


@pytest.fixture()
def c(A):
    return TestClient(A.app)


def d(n):
    return (dt.date.today() + dt.timedelta(days=n)).isoformat()


# ── Repeating tasks ───────────────────────────────────────────────────

@pytest.mark.parametrize("due,pattern,expected", [
    ("2026-03-10", "daily", "2026-03-11"),
    ("2026-03-10", "weekly", "2026-03-17"),
    ("2026-03-10", "fortnightly", "2026-03-24"),
    ("2026-01-31", "monthly", "2026-02-28"),
    ("2028-01-31", "monthly", "2028-02-29"),     # leap year
    ("2026-12-15", "monthly", "2027-01-15"),
    ("2026-12-31", "monthly", "2027-01-31"),
])
def test_next_due_date(A, due, pattern, expected):
    assert A.next_due_date(due, pattern) == expected


def test_completing_a_repeating_task_adds_the_next_one_once(c):
    t = c.post("/api/tasks", json={"title": "Weekly quiz", "due_date": d(1), "recurrence_pattern": "weekly",
                                   "priority": "high", "estimated_hours": 2}).json()
    assert t["is_recurring"] is True and t["recurrence_pattern"] == "weekly"

    done = c.put(f"/api/tasks/{t['id']}", json={"status": "completed"}).json()
    nxt = done["next_task"]
    assert nxt["due_date"] == d(8)
    assert nxt["title"] == "Weekly quiz" and nxt["priority"] == "high" and nxt["estimated_hours"] == 2
    assert nxt["status"] == "not_started" and nxt["progress"] == 0 and nxt["recurrence_pattern"] == "weekly"
    assert done["recurrence_pattern"] == "" and done["is_recurring"] is False   # the finished one stops repeating

    # Un-completing and completing again must not add another copy
    c.put(f"/api/tasks/{t['id']}", json={"status": "not_started", "progress": 0})
    again = c.put(f"/api/tasks/{t['id']}", json={"status": "completed"}).json()
    assert "next_task" not in again
    assert len([x for x in c.get("/api/tasks").json() if x["title"] == "Weekly quiz"]) == 2


def test_repeating_task_completed_late_skips_to_the_future(c):
    t = c.post("/api/tasks", json={"title": "Gym", "due_date": d(-10), "recurrence_pattern": "daily"}).json()
    nxt = c.put(f"/api/tasks/{t['id']}", json={"progress": 100}).json()["next_task"]
    assert nxt["due_date"] == d(0)


def test_repeating_task_without_a_date_starts_today(c):
    t = c.post("/api/tasks", json={"title": "Read", "recurrence_pattern": "daily"}).json()
    assert t["due_date"] == d(0)


def test_turning_repeat_off(c):
    t = c.post("/api/tasks", json={"title": "x", "due_date": d(0), "recurrence_pattern": "monthly"}).json()
    off = c.put(f"/api/tasks/{t['id']}", json={"recurrence_pattern": ""}).json()
    assert off["is_recurring"] is False
    assert "next_task" not in c.put(f"/api/tasks/{t['id']}", json={"status": "completed"}).json()


def test_bad_repeat_rejected(c):
    assert c.post("/api/tasks", json={"title": "x", "recurrence_pattern": "hourly"}).status_code == 422


# ── Task types ────────────────────────────────────────────────────────

def test_rename_and_recolour_task_type(c):
    t = c.post("/api/tasks", json={"title": "Essay", "category_id": 1}).json()
    r = c.put("/api/categories/1", json={"name": "Essay or report", "color": "#123456"})
    assert r.status_code == 200 and r.json()["name"] == "Essay or report" and r.json()["color"] == "#123456"
    assert c.get(f"/api/tasks/{t['id']}").json()["category_name"] == "Essay or report"
    assert c.put("/api/categories/1", json={"name": "Exam"}).status_code == 400          # name taken
    assert c.put("/api/categories/1", json={"color": "red"}).status_code == 422
    assert c.put("/api/categories/999", json={"name": "x"}).status_code == 404


def test_deleting_a_task_type_keeps_its_tasks(c):
    t = c.post("/api/tasks", json={"title": "Read ch 3", "category_id": 4}).json()
    c.delete("/api/categories/4")
    kept = c.get(f"/api/tasks/{t['id']}").json()
    assert kept["category_id"] is None


# ── Restore from backup ───────────────────────────────────────────────

def test_backup_round_trip(A, c):
    s = c.post("/api/subjects", json={"name": "SIT313"}).json()
    u = c.post(f"/api/subjects/{s['id']}/units", json={"name": "Week 5"}).json()
    c.post("/api/tasks", json={"title": "Prac", "subject_id": s["id"], "unit_id": u["id"], "category_id": 2})
    c.post("/api/jobs", json={"company": "Atlassian", "role": "Intern"})
    c.post("/api/transactions", json={"type": "expense", "amount": 12.5, "category": "Food", "date": d(0)})
    c.put("/api/settings/money", json={"currency": "AUD"})
    backup = c.get("/api/export").json()

    # Change everything after the backup
    c.post("/api/tasks", json={"title": "Made after the backup"})
    c.delete(f"/api/subjects/{s['id']}")
    c.put("/api/settings/money", json={"currency": "EUR"})

    preview = c.post("/api/import/preview", json=backup).json()
    assert preview["counts"]["tasks"] == 1 and preview["counts"]["job_applications"] == 1

    r = c.post("/api/import", json=backup)
    assert r.status_code == 200, r.text
    assert r.json()["safety_backup"].startswith("before-restore-")
    assert (A.BACKUP_DIR / r.json()["safety_backup"]).exists()

    tasks = c.get("/api/tasks").json()
    assert [t["title"] for t in tasks] == ["Prac"]
    assert tasks[0]["subject_name"] == "SIT313" and tasks[0]["unit_name"] == "Week 5"
    assert c.get("/api/settings/money").json()["currency"] == "AUD"
    assert len(c.get("/api/jobs").json()) == 1
    # New items still get fresh ids after a restore
    assert c.post("/api/tasks", json={"title": "after"}).json()["id"] > tasks[0]["id"]


def test_safety_backup_has_the_data_from_before_the_restore(A, c):
    c.post("/api/tasks", json={"title": "Only in the old data"})
    empty = c.get("/api/export").json()
    empty["tasks"] = []
    safety = c.post("/api/import", json=empty).json()["safety_backup"]
    conn = sqlite3.connect(A.BACKUP_DIR / safety)
    assert conn.execute("SELECT title FROM tasks").fetchall() == [("Only in the old data",)]
    conn.close()
    assert c.get("/api/tasks").json() == []


def test_restore_older_backup_missing_columns(c):
    backup = {"app": "LifePlanner", "version": "2.0.0", "categories": [{"id": 1, "name": "Assignment", "color": "#b45309"}],
              "tasks": [{"id": 5, "title": "Old task", "status": "overdue", "progress": 0, "category_id": 1,
                         "column_from_the_future": "ignored"}]}
    assert c.post("/api/import", json=backup).status_code == 200
    t = c.get("/api/tasks").json()[0]
    assert t["title"] == "Old task" and t["status"] == "not_started"


@pytest.mark.parametrize("bad", [
    {"hello": "world"},
    {"app": "Trackademic", "tasks": "nope"},
    {"app": "Trackademic", "tasks": [], "jobs_applications": [], "transactions": [1, 2]},
    {"app": "SomethingElse", "tasks": []},
])
def test_invalid_backup_rejected_and_nothing_changes(c, bad):
    c.post("/api/tasks", json={"title": "Keep me"})
    assert c.post("/api/import", json=bad).status_code == 400
    assert [t["title"] for t in c.get("/api/tasks").json()] == ["Keep me"]


def test_broken_links_roll_back(c):
    c.post("/api/tasks", json={"title": "Keep me"})
    backup = {"app": "Trackademic", "tasks": [{"id": 1, "title": "x", "subject_id": 42}], "subjects": []}
    r = c.post("/api/import", json=backup)
    assert r.status_code == 400
    assert [t["title"] for t in c.get("/api/tasks").json()] == ["Keep me"]


def test_auto_backup_once_a_day_and_pruned(A):
    A.auto_backup()
    A.auto_backup()
    assert len(A.list_backups("auto")) == 1
    for i in range(15):
        (A.BACKUP_DIR / f"auto-2020-01-{i + 1:02d}_000000.db").write_bytes(b"")
    A.auto_backup()
    files = A.list_backups("auto")
    assert len(files) == A.KEEP_AUTO_BACKUPS
    assert files[0].name.startswith(f"auto-{dt.date.today().isoformat()}")     # today's is kept


# ── Reminders ─────────────────────────────────────────────────────────

def test_digest(A, c):
    with A.db() as conn:
        assert reminders.build_digest(conn, dt.date.today()) is None
    c.post("/api/tasks", json={"title": "Essay", "due_date": d(0), "priority": "urgent"})
    c.post("/api/tasks", json={"title": "Lab", "due_date": d(-2)})
    c.post("/api/tasks", json={"title": "Done already", "due_date": d(0), "status": "completed"})
    c.post("/api/tasks", json={"title": "Next week", "due_date": d(7)})
    c.post("/api/jobs", json={"company": "Canva", "role": "Grad", "follow_up_date": d(0)})
    c.post("/api/jobs", json={"company": "Rejected Co", "role": "x", "follow_up_date": d(0), "status": "rejected"})
    with A.db() as conn:
        dg = reminders.build_digest(conn, dt.date.today())
    assert dg["counts"] == {"due_today": 1, "overdue": 1, "follow_ups": 1}
    assert dg["title"] == "1 task due today, 1 overdue, 1 follow-up"
    assert "Essay" in dg["body"] and "Lab" in dg["body"] and "Canva" in dg["body"]
    assert "Rejected Co" not in dg["body"] and "Done already" not in dg["body"]


@pytest.mark.parametrize("settings,last,now,expected", [
    ({"daily": True, "time": "08:30"}, "", "2026-10-07 08:29", False),
    ({"daily": True, "time": "08:30"}, "", "2026-10-07 08:30", True),
    ({"daily": True, "time": "08:30"}, "", "2026-10-07 21:00", True),        # opened late: catch up
    ({"daily": True, "time": "08:30"}, "2026-10-07", "2026-10-07 21:00", False),
    ({"daily": True, "time": "08:30"}, "2026-10-06", "2026-10-07 09:00", True),
    ({"daily": False, "time": "08:30"}, "", "2026-10-07 09:00", False),
])
def test_due_to_send(settings, last, now, expected):
    assert reminders.due_to_send(settings, last, dt.datetime.strptime(now, "%Y-%m-%d %H:%M")) is expected


def test_reminder_settings(c):
    assert c.get("/api/settings/reminders").json() == {"daily": True, "time": "08:30"}
    assert c.put("/api/settings/reminders", json={"daily": True, "time": "19:05"}).json()["time"] == "19:05"
    assert c.get("/api/settings/reminders").json()["time"] == "19:05"
    for bad in ("7pm", "24:00", "9:00"):
        assert c.put("/api/settings/reminders", json={"daily": True, "time": bad}).status_code == 422


def test_test_reminder_uses_todays_digest(A, c, monkeypatch):
    sent = []
    monkeypatch.setattr(reminders, "notify", lambda t, b: sent.append((t, b)) or True)
    r = c.post("/api/reminders/test").json()
    assert r["shown"] is True and sent[0][0] == "Nothing due today"
    c.post("/api/tasks", json={"title": "Essay", "due_date": d(0)})
    c.post("/api/reminders/test")
    assert sent[1][0] == "1 task due today" and "Essay" in sent[1][1]


def test_scheduler_sends_once(A, c, monkeypatch):
    sent = []
    monkeypatch.setattr(reminders, "notify", lambda t, b: sent.append(t) or True)
    c.put("/api/settings/reminders", json={"daily": True, "time": "00:00"})
    c.post("/api/tasks", json={"title": "Essay", "due_date": d(0)})
    import threading
    import time
    stop = threading.Event()
    thread = reminders.start_scheduler(A.get_reminder_settings, A.reminder_last_sent, A.set_reminder_last_sent,
                                       A.todays_digest, interval=0.05, stop=stop)
    time.sleep(0.5)
    stop.set()
    thread.join(2)
    assert sent == ["1 task due today"]
    assert A.reminder_last_sent() == dt.date.today().isoformat()


def test_notification_text_is_escaped_for_windows(monkeypatch):
    captured = {}

    def fake_run(cmd, **kw):
        import base64
        captured["script"] = base64.b64decode(cmd[-1]).decode("utf-16-le")

        class R:
            returncode = 0
        return R()
    monkeypatch.setattr(reminders.subprocess, "run", fake_run)
    assert reminders._windows_toast("Tom & Jerry <b>", "'@ quote", "App.Id")
    assert "Tom &amp; Jerry &lt;b&gt;" in captured["script"]
    assert "CreateToastNotifier('App.Id')" in captured["script"]


# ── Start with Windows / single instance ──────────────────────────────

def test_autostart_unsupported_outside_installed_windows_app(c):
    assert c.get("/api/settings/autostart").json() == {"supported": False, "enabled": False}
    assert c.put("/api/settings/autostart", json={"enabled": True}).status_code == 400


def test_single_instance_lock(tmp_path):
    assert system_integration.find_running_instance(tmp_path, "Trackademic") is None
    system_integration.claim_instance(tmp_path, 1)          # nothing listens on port 1
    assert system_integration.find_running_instance(tmp_path, "Trackademic") is None


def test_window_show_without_a_window(c):
    assert c.post("/api/window/show").json() == {"ok": False}


def test_window_show_calls_the_desktop_hook(A, c):
    import threading
    called = threading.Event()
    A.WINDOW["show"] = called.set
    assert c.post("/api/window/show").json() == {"ok": True}
    assert called.wait(2)


# ── After an update the window must load the new screens, not cached old ones (bug in 3.5.0) ──

def test_page_links_are_versioned_and_static_files_revalidate(A, c):
    r = c.get("/")
    assert r.headers["cache-control"] == "no-cache"
    for name in ("app.js", "icons.js", "theme.js", "styles.css", "intro.css"):
        assert f"/static/{name}?v={A.APP_VERSION}\"" in r.text, name
    js = c.get(f"/static/app.js?v={A.APP_VERSION}")
    assert js.status_code == 200 and js.headers["cache-control"] == "no-cache"
    assert "<!-- intro:start -->" in r.text
