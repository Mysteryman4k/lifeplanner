# ruff: noqa: F811  (shared pytest fixtures)
"""v4 stage 10: saved chats (kept, listed, reopened, in backups, removed by Remove all AI data), the Quiz me and
Check my attempt modes, and the Videos action."""
import pytest

from test_ai_chat import fake, ready  # noqa: F401  (fixtures)
from test_ai_setup import A, agree, c, vault  # noqa: F401  (fixtures)


def chat_body(*pairs, **extra):
    msgs = []
    for q, a in pairs:
        msgs += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
    return {"messages": msgs, **extra}


def test_save_list_open_and_delete(c):
    agree(c)
    new = c.post("/api/ai/chats", json=chat_body(("What is a heap? It's for my data structures unit and I need it", "A tree..."),
                                                 mode="practise", tokens=42)).json()
    assert new["title"] == "What is a heap? It's for my data structures unit and I need …"
    later = c.post("/api/ai/chats", json=chat_body(("Big-O of merge sort", "n log n"), title="Merge sort")).json()
    listed = c.get("/api/ai/chats").json()
    assert [x["id"] for x in listed][0] in (later["id"], new["id"]) and {x["title"] for x in listed} >= {"Merge sort"}
    assert next(x for x in listed if x["id"] == new["id"])["count"] == 2
    body = chat_body(("What is a heap?", "A tree..."), ("And a min-heap?", "The smallest on top."), mode="practise", tokens=99)
    body["messages"][1]["meta"] = {"cards": [{"kind": "action", "id": 7, "summary": "Add “Revise heaps”", "status": "done"}]}
    assert c.put(f"/api/ai/chats/{new['id']}", json=body).status_code == 200
    got = c.get(f"/api/ai/chats/{new['id']}").json()
    assert got["mode"] == "practise" and got["tokens"] == 99 and len(got["messages"]) == 4
    assert got["messages"][1]["meta"]["cards"][0]["summary"] == "Add “Revise heaps”"
    assert [m["content"] for m in got["messages"]][2] == "And a min-heap?"
    c.delete(f"/api/ai/chats/{new['id']}")
    assert c.get(f"/api/ai/chats/{new['id']}").status_code == 404
    assert c.put(f"/api/ai/chats/{new['id']}", json=body).status_code == 404


def test_chats_need_the_terms(c):
    assert c.get("/api/ai/chats").status_code == 403
    assert c.post("/api/ai/chats", json=chat_body(("hi", "hello"))).status_code == 403


def test_bad_saves_are_refused(c):
    agree(c)
    assert c.post("/api/ai/chats", json={"messages": []}).status_code == 422
    assert c.post("/api/ai/chats", json=chat_body(("hi", "x"), kind="other")).status_code == 422
    big = chat_body(("hi", "x"))
    big["messages"][1]["meta"] = {"cards": ["x" * 300_000]}
    assert c.post("/api/ai/chats", json=big).status_code == 422


def test_links_to_a_deleted_task_or_folder_dont_stop_a_save(c):
    agree(c)
    t = c.post("/api/tasks", json={"title": "Essay"}).json()
    saved = c.post("/api/ai/chats", json=chat_body(("help", "ok"), task_id=t["id"], folder_id=999)).json()
    got = c.get(f"/api/ai/chats/{saved['id']}").json()
    assert got["task_id"] == t["id"] and got["folder_id"] is None
    c.delete(f"/api/tasks/{t['id']}")
    assert c.get(f"/api/ai/chats/{saved['id']}").json()["task_id"] is None


def test_chats_are_in_backups(c):
    agree(c)
    c.post("/api/ai/chats", json=chat_body(("What is recursion?", "A function calling itself.")))
    backup = c.get("/api/export").json()
    assert [r["title"] for r in backup["conversations"]] == ["What is recursion?"]
    assert [r["content"] for r in backup["messages"]] == ["What is recursion?", "A function calling itself."]
    c.delete(f"/api/ai/chats/{backup['conversations'][0]['id']}")
    assert c.post("/api/import", json=backup).status_code == 200
    agree(c)                                                            # the agreement isn't in backups
    assert [x["title"] for x in c.get("/api/ai/chats").json()] == ["What is recursion?"]


def test_remove_all_ai_data_removes_chats_and_code_data(c, A, tmp_path_factory):
    proj = tmp_path_factory.mktemp("proj")
    (proj / "a.py").write_text("x = 1\n")
    ready(c)
    c.put("/api/ai/settings", json={"code_enabled": True})
    c.post("/api/code/folders", json={"path": str(proj)})
    c.post("/api/ai/chats", json=chat_body(("hi", "hello")))
    c.post("/api/notes", json={"title": "Keep me", "body": "notes are the student's"})
    backups = A.DB_PATH.parent / "code-backups"
    backups.mkdir()
    (backups / "1-a.py").write_text("old")
    assert c.delete("/api/ai/all").status_code == 200
    agree(c)
    c.put("/api/ai/settings", json={"code_enabled": True})
    assert c.get("/api/ai/chats").json() == [] and c.get("/api/code/folders").json() == []
    assert not backups.exists() and (proj / "a.py").exists()                # the folder itself is untouched
    assert [n["title"] for n in c.get("/api/notes").json()] == ["Keep me"]


@pytest.mark.parametrize("mode,expect", [("quiz", "Mode: Quiz me"), ("check", "Mode: Check my attempt")])
def test_quiz_and_check_modes(c, fake, mode, expect):
    ready(c)
    assert c.post("/api/ai/chat", json={"mode": mode, "messages": [{"role": "user", "content": "hi"}]}).status_code == 200
    assert expect in fake.last["system"] and "not an answer writer" in fake.last["system"]


def test_the_videos_action(c, fake):
    ready(c)
    c.post("/api/ai/chat", json={"action": "videos", "messages": [{"role": "user", "content": "Find videos on this"}]})
    assert "Task: suggest videos" in fake.last["system"] and "Don't make up video titles" in fake.last["system"]
    c.post("/api/ai/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert "Task: suggest videos" not in fake.last["system"]
    assert c.post("/api/ai/chat", json={"action": "essay", "messages": [{"role": "user", "content": "hi"}]}).status_code == 422
