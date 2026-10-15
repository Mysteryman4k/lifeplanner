# ruff: noqa: F811  (shared pytest fixtures)
"""v4 stage 11b: long chats keep their thread through a running summary of older messages, and old AI records
are cleared (suggested code changes and their backups, the record of task changes, and saved chats when the
student chooses a limit)."""
import os
import time

import pytest

import ai.chats as chats
from ai.prompts import SUMMARISE
from test_ai_chat import fake, ready  # noqa: F401  (fixtures)
from test_ai_setup import A, agree, c, vault  # noqa: F401  (fixtures)


def msgs(*texts):
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": t} for i, t in enumerate(texts)]


# ── the summary of older messages ──

def test_summarise_folds_messages_into_the_summary(c, fake):
    ready(c)
    r = c.post("/api/ai/summarise", json={"previous": "The student is revising heaps.",
                                          "messages": msgs("What is a min-heap?", "The smallest on top. " + "x" * 5000)})
    assert r.status_code == 200 and r.json() == {"summary": "Hello from the fake tutor.", "tokens": 17}
    assert fake.last["system"] == SUMMARISE and fake.last["tools"] is None
    asked = fake.last["messages"][0]["content"]
    assert asked.startswith("Summary so far:\nThe student is revising heaps.")
    assert "Student: What is a min-heap?" in asked and "Assistant: The smallest on top." in asked
    assert " […]" in asked and len(asked) < 4000                        # long messages are shortened


def test_many_messages_are_shortened_more():
    from ai.prompts import summarise_request
    few = summarise_request("", msgs("a" * 5000, "b"))
    many = summarise_request("", msgs(*["c" * 5000] * 200))
    assert few.count("a") >= 3000 and "a" * 3001 not in few                 # up to 3,000 characters each
    assert len(many) < 80_000 and "c" * 301 not in many                     # 200 messages: about 300 each


def test_summarise_is_gated(c, fake):
    body = {"messages": msgs("hi")}
    assert c.post("/api/ai/summarise", json=body).status_code == 403          # terms not agreed
    agree(c)
    assert c.post("/api/ai/summarise", json=body).status_code == 400          # no provider yet
    ready(c)
    assert c.post("/api/ai/summarise", json={**body, "kind": "code"}).status_code == 403   # code workspace off
    assert c.post("/api/ai/summarise", json={"messages": []}).status_code == 422
    fake.fail = "Ollama isn't running on this PC."
    r = c.post("/api/ai/summarise", json=body)
    assert r.status_code == 502 and r.json()["detail"] == "Ollama isn't running on this PC."


def test_an_empty_summary_is_an_error(c, fake):
    ready(c)
    fake.script = [[]]                                                       # the model says nothing
    assert c.post("/api/ai/summarise", json={"messages": msgs("hi")}).status_code == 502


def test_the_summary_goes_with_each_question(c, fake):
    ready(c)
    att = {"name": "notes.pdf", "text": "Heaps are trees."}
    c.post("/api/ai/chat", json={"messages": msgs("And a max-heap?"), "summary": "The student learnt min-heaps.",
                                 "attachment": att})
    system = fake.last["system"]
    assert "Summary of the earlier part of this chat" in system and "The student learnt min-heaps." in system
    assert system.index("The student learnt min-heaps.") < system.index("You can manage the student's tasks") \
        < system.index("[start of attached file]")                           # instructions, then the file last
    c.post("/api/ai/chat", json={"messages": msgs("hi")})
    assert "Summary of the earlier part" not in fake.last["system"]
    assert c.post("/api/ai/chat", json={"messages": msgs("hi"), "summary": "x" * 8001}).status_code == 422


def test_saved_chats_keep_the_summary(c, A):
    agree(c)
    saved = c.post("/api/ai/chats", json={"messages": msgs("hi", "hello"), "summary": "Earlier: heaps."}).json()
    assert c.get(f"/api/ai/chats/{saved['id']}").json()["summary"] == "Earlier: heaps."
    assert c.get("/api/export").json()["conversations"][0]["summary"] == "Earlier: heaps."
    with A.db() as conn:
        conn.execute("ALTER TABLE conversations DROP COLUMN summary")
    A.init_db()                                                               # older databases get the column
    assert c.get(f"/api/ai/chats/{saved['id']}").json()["summary"] == ""


# ── clearing old records ──

def add_change(A, folder_id, status="applied", days_old=0, backup=""):
    with A.db() as conn:
        cid = conn.execute("INSERT INTO file_changes (folder_id, path, summary, status, new_content, backup, created_at) "
                           "VALUES (?, 'a.py', '', ?, 'x', ?, datetime('now', 'localtime', ?))",
                           (folder_id, status, backup, f"-{days_old} days")).lastrowid
    return cid


def add_action(A, status="done", days_old=0):
    with A.db() as conn:
        return conn.execute("INSERT INTO ai_actions (status, summary, data, created_at) VALUES (?, '', '[]', "
                            "datetime('now', 'localtime', ?))", (status, f"-{days_old} days")).lastrowid


def ids(A, table):
    with A.db() as conn:
        return sorted(r[0] for r in conn.execute(f"SELECT id FROM {table}"))


def test_old_code_changes_and_their_backups_are_cleared(A, tmp_path, monkeypatch):
    monkeypatch.setattr(chats, "KEEP_CHANGES", 2)
    backups = A.DB_PATH.parent / "code-backups"
    backups.mkdir()
    with A.db() as conn:
        folder = conn.execute("INSERT INTO code_folders (path, name) VALUES (?, 'proj')", (str(tmp_path),)).lastrowid
    old_files = []
    for name in ("1-a.py", "2-a.py", "stray.py", "fresh-stray.py"):
        (backups / name).write_text("old")
        old_files.append(backups / name)
    for f in old_files[:3]:
        os.utime(f, (time.time() - 7200, time.time() - 7200))               # an orphan is cleared once an hour old
    old = add_change(A, folder, days_old=120, backup=str(backups / "1-a.py"))
    busy = add_change(A, folder, status="applying", days_old=120)            # part-way through: left alone
    recent_old = add_change(A, folder, days_old=100, backup=str(backups / "2-a.py"))
    new = add_change(A, folder)
    removed = chats.clean_up_records(A.db, A.DB_PATH.parent)
    # Older than 90 days and not among the newest 2: the first one goes, with its backup
    assert ids(A, "file_changes") == [busy, recent_old, new] and removed["changes"] == 1
    assert not (backups / "1-a.py").exists() and (backups / "2-a.py").exists()
    assert not (backups / "stray.py").exists() and (backups / "fresh-stray.py").exists()   # a new one may be mid-Apply
    assert removed["backups"] == 2
    assert old not in ids(A, "file_changes")


def test_old_task_change_records_are_cleared(A, monkeypatch):
    monkeypatch.setattr(chats, "KEEP_ACTIONS", 1)
    old = add_action(A, days_old=200)
    waiting = add_action(A, status="pending", days_old=200)                  # still waiting for a yes
    undone = add_action(A, status="undone", days_old=95)
    new = add_action(A)
    assert chats.clean_up_records(A.db, A.DB_PATH.parent)["actions"] == 2
    assert ids(A, "ai_actions") == [waiting, new] and old not in ids(A, "ai_actions") and undone not in ids(A, "ai_actions")


def old_chat(c, A, title, days_old):
    saved = c.post("/api/ai/chats", json={"title": title, "messages": msgs("hi", "hello")}).json()
    with A.db() as conn:
        conn.execute("UPDATE conversations SET updated_at=datetime('now', 'localtime', ?) WHERE id=?",
                     (f"-{days_old} days", saved["id"]))
    return saved["id"]


def test_chats_are_kept_until_the_student_chooses_a_limit(c, A):
    agree(c)
    ancient = old_chat(c, A, "Ancient", 400)
    month = old_chat(c, A, "Last month", 40)
    today = old_chat(c, A, "Today", 0)
    assert chats.clean_up_records(A.db, A.DB_PATH.parent)["chats"] == 0      # the default: kept
    assert c.get("/api/ai/state").json()["keep_chats_days"] == 0
    r = c.put("/api/ai/settings", json={"keep_chats_days": 365})
    assert r.status_code == 200 and r.json()["removed_chats"] == 1 and r.json()["keep_chats_days"] == 365
    r = c.put("/api/ai/settings", json={"keep_chats_days": 30})
    assert r.json()["removed_chats"] == 1
    assert [x["id"] for x in c.get("/api/ai/chats").json()] == [today]
    with A.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM messages WHERE conversation_id IN (?, ?)", (ancient, month)).fetchone()[0] == 0
    assert "removed_chats" not in c.put("/api/ai/settings", json={"keep_chats_days": 0}).json()
    assert c.put("/api/ai/settings", json={"keep_chats_days": 45}).status_code == 422


def test_clearing_runs_when_the_app_starts(A, monkeypatch):
    calls = []
    monkeypatch.setattr(A, "auto_backup", lambda: calls.append("backup"))
    monkeypatch.setattr(A, "clean_up_ai_records", lambda: calls.append("clean") or {})
    A.start_up_jobs()
    assert calls == ["backup", "clean"]

    def broken():
        raise OSError("disk")
    monkeypatch.setattr(A, "clean_up_ai_records", broken)
    A.start_up_jobs()                                                         # a problem never stops the app


def test_the_real_start_up_clean_up_uses_the_chat_setting(c, A):
    agree(c)
    c.put("/api/ai/settings", json={"keep_chats_days": 90})
    gone = old_chat(c, A, "Old", 100)
    A.clean_up_ai_records()
    assert gone not in [x["id"] for x in c.get("/api/ai/chats").json()]


@pytest.mark.parametrize("days", chats.KEEP_CHATS)
def test_every_keep_chats_choice_is_accepted(c, days):
    agree(c)
    assert c.put("/api/ai/settings", json={"keep_chats_days": days}).status_code == 200
