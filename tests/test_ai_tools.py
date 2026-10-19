# ruff: noqa: F811, E501  (shared pytest fixtures; recorded provider data is kept on one line)
"""v4 stage 4: task actions through the study assistant, with Undo and Keep/Delete confirmations."""
import json

import httpx
import pytest

from test_ai_chat import events, ready
from test_ai_setup import A, agree, c, vault  # noqa: F401  (fixtures)


@pytest.fixture()
def fake(monkeypatch):
    from ai.providers.fake import FakeProvider
    import ai.routes
    p = FakeProvider()
    p.script = []
    monkeypatch.setattr(ai.routes, "get_provider", lambda *a, **k: p)
    return p


def calls(*items):
    return {"type": "tool_calls", "calls": [{"id": f"c{i}", "name": n, "args": a} for i, (n, a) in enumerate(items)]}


def chat(c, text="hi"):
    return events(c.post("/api/ai/chat", json={"messages": [{"role": "user", "content": text}]}))


def tasks(c):
    return {t["title"]: t for t in c.get("/api/tasks").json()}


def test_adding_a_task_shows_an_undoable_card(c, fake):
    ready(c)
    fake.script = [[calls(("add_task", {"title": "Draft lab report", "due_date": "2026-11-02", "priority": "high"}))],
                   [{"type": "text", "text": "Added it."}]]
    ev = chat(c, "add a lab report task")
    action = next(e for e in ev if e["type"] == "action")
    assert action["summary"] == "Add “Draft lab report” (due 2026-11-02)"
    t = tasks(c)["Draft lab report"]
    assert t["priority"] == "high" and t["due_date"] == "2026-11-02"
    assert "Done: Add" in json.dumps(fake.rounds[1]["messages"])      # the model is told it worked
    assert fake.rounds[0]["tools"] and "manage the student's tasks" in fake.rounds[0]["system"]
    assert c.post("/api/ai/undo", json={"action_id": action["action_id"]}).json() == {"status": "undone"}
    assert "Draft lab report" not in tasks(c)
    assert c.post("/api/ai/undo", json={"action_id": action["action_id"]}).status_code == 409    # only once


def test_update_and_undo_restore_exactly(c, fake):
    ready(c)
    s = c.post("/api/subjects", json={"name": "Networks", "color": "#3B6EA8"}).json()
    t = c.post("/api/tasks", json={"title": "Read ch 3", "priority": "low", "due_date": "2026-11-01"}).json()
    fake.script = [[calls(("update_task", {"id": t["id"], "title": "Read chapter 3", "subject": "networks",
                                           "priority": "urgent"}))], [{"type": "text", "text": "ok"}]]
    action = next(e for e in chat(c) if e["type"] == "action")
    changed = tasks(c)["Read chapter 3"]
    assert changed["priority"] == "urgent" and changed["subject_id"] == s["id"]
    c.post("/api/ai/undo", json={"action_id": action["action_id"]})
    back = c.get(f"/api/tasks/{t['id']}").json()
    assert (back["title"], back["priority"], back["subject_id"], back["due_date"]) == ("Read ch 3", "low", None, "2026-11-01")


def test_completing_a_repeating_task_and_undoing_removes_the_next_one(c, fake):
    ready(c)
    t = c.post("/api/tasks", json={"title": "Weekly reading", "due_date": "2026-11-02", "recurrence_pattern": "weekly"}).json()
    fake.script = [[calls(("complete_task", {"id": t["id"]}))], [{"type": "text", "text": "Done!"}]]
    action = next(e for e in chat(c) if e["type"] == "action")
    titles = [x["title"] for x in c.get("/api/tasks").json()]
    assert titles.count("Weekly reading") == 2                         # the next occurrence was added
    c.post("/api/ai/undo", json={"action_id": action["action_id"]})
    left = [x for x in c.get("/api/tasks").json() if x["title"] == "Weekly reading"]
    assert len(left) == 1 and left[0]["status"] != "completed" and left[0]["recurrence_pattern"] == "weekly"


def test_deleting_always_asks_first(c, fake):
    ready(c)
    t = c.post("/api/tasks", json={"title": "Old task", "priority": "high", "notes": "keep these notes"}).json()
    fake.script = [[calls(("delete_task", {"id": t["id"]}))], [{"type": "text", "text": "Waiting for you."}]]
    ev = chat(c)
    card = next(e for e in ev if e["type"] == "confirm")
    assert card["danger"] is True and card["items"] == ["Delete “Old task”"]
    assert "Old task" in tasks(c)                                       # nothing happened yet
    assert "Waiting for the student to confirm" in json.dumps(fake.rounds[1]["messages"])
    assert c.post("/api/ai/confirm", json={"action_id": card["action_id"], "approve": True}).json()["status"] == "done"
    assert "Old task" not in tasks(c)
    assert c.post("/api/ai/confirm", json={"action_id": card["action_id"], "approve": True}).status_code == 409
    c.post("/api/ai/undo", json={"action_id": card["action_id"]})       # undo the approved delete
    back = c.get(f"/api/tasks/{t['id']}").json()
    assert back["title"] == "Old task" and back["notes"] == "keep these notes" and back["priority"] == "high"


def test_undoing_a_delete_relinks_its_notes(c, fake):
    ready(c)
    t = c.post("/api/tasks", json={"title": "Essay"}).json()
    note = c.post("/api/notes", json={"title": "Essay plan", "body": "intro", "task_id": t["id"]}).json()
    fake.script = [[calls(("delete_task", {"id": t["id"]}))], [{"type": "text", "text": "ok"}]]
    card = next(e for e in chat(c) if e["type"] == "confirm")
    c.post("/api/ai/confirm", json={"action_id": card["action_id"], "approve": True})
    assert next(n for n in c.get("/api/notes").json() if n["id"] == note["id"])["task_id"] is None
    assert c.post("/api/ai/undo", json={"action_id": card["action_id"]}).json() == {"status": "undone"}
    assert next(n for n in c.get("/api/notes").json() if n["id"] == note["id"])["task_id"] == t["id"]


def test_undo_steps_are_saved_before_the_task_changes(c, fake):
    """If the app closes part-way through a delete, the next start offers Undo for what was done."""
    import app as A
    from ai.tools import TaskTools
    ready(c)
    t = c.post("/api/tasks", json={"title": "Lab 3", "priority": "high"}).json()
    log, store = A.ActionLog(), A.TaskStore()
    action_id = log.pending([{"id": "c0", "name": "delete_task", "args": {"id": t["id"]}}], ["Delete “Lab 3”"])

    def crash(task_id):
        A.delete_task(task_id)
        raise SystemExit("closed")                                       # the app stops right after the delete
    store.delete = crash
    with pytest.raises(SystemExit):
        TaskTools(store, log).confirm(action_id, True)
    A.init_db()                                                         # next start
    assert c.post("/api/ai/undo", json={"action_id": action_id}).json() == {"status": "undone"}
    assert c.get(f"/api/tasks/{t['id']}").json()["title"] == "Lab 3"


def test_undo_restores_a_task_whose_subject_was_deleted(c, fake):
    ready(c)
    s = c.post("/api/subjects", json={"name": "Physics", "color": "#3B6EA8"}).json()
    t = c.post("/api/tasks", json={"title": "Prac report", "subject_id": s["id"]}).json()
    fake.script = [[calls(("delete_task", {"id": t["id"]}))], [{"type": "text", "text": "ok"}]]
    card = next(e for e in chat(c) if e["type"] == "confirm")
    c.post("/api/ai/confirm", json={"action_id": card["action_id"], "approve": True})
    c.delete(f"/api/subjects/{s['id']}")
    assert c.post("/api/ai/undo", json={"action_id": card["action_id"]}).json() == {"status": "undone"}
    back = c.get(f"/api/tasks/{t['id']}").json()
    assert back["title"] == "Prac report" and back["subject_id"] is None


def test_a_change_is_only_claimed_once(c, fake):
    """Two clicks at once: the second sees the change is already being applied."""
    import app as A
    ready(c)
    fake.script = [[calls(*[("add_task", {"title": f"Part {i}"}) for i in range(1, 5)])], [{"type": "text", "text": "ok"}]]
    card = next(e for e in chat(c) if e["type"] == "confirm")
    log = A.ActionLog()
    log.take_pending(card["action_id"])                                 # first click claims it
    with pytest.raises(A.HTTPException) as e:
        log.take_pending(card["action_id"])                             # second click is refused
    assert e.value.status_code == 409
    A.init_db()                                                         # the app stopped before any change
    assert c.post("/api/ai/undo", json={"action_id": card["action_id"]}).json() == {"status": "undone"}


def test_keep_leaves_the_task_alone(c, fake):
    ready(c)
    t = c.post("/api/tasks", json={"title": "Keep me"}).json()
    fake.script = [[calls(("delete_task", {"id": t["id"]}))], [{"type": "text", "text": "ok"}]]
    card = next(e for e in chat(c) if e["type"] == "confirm")
    assert c.post("/api/ai/confirm", json={"action_id": card["action_id"], "approve": False}).json() == {"status": "rejected"}
    assert "Keep me" in tasks(c)
    assert c.post("/api/ai/undo", json={"action_id": card["action_id"]}).status_code == 409


def test_more_than_three_changes_ask_first_together(c, fake):
    ready(c)
    fake.script = [[calls(*[("add_task", {"title": f"Step {i}"}) for i in range(1, 6)])], [{"type": "text", "text": "ok"}]]
    ev = chat(c, "break my assignment into 5 steps")
    assert [e["summary"] for e in ev if e["type"] == "action"] == [f"Add “Step {i}”" for i in (1, 2, 3)]
    card = next(e for e in ev if e["type"] == "confirm")
    assert card["items"] == ["Add “Step 4”", "Add “Step 5”"] and card["danger"] is False
    assert sorted(t for t in tasks(c) if t.startswith("Step")) == ["Step 1", "Step 2", "Step 3"]
    r = c.post("/api/ai/confirm", json={"action_id": card["action_id"], "approve": True}).json()
    assert r == {"status": "done", "done": 2, "failed": []}
    assert sorted(t for t in tasks(c) if t.startswith("Step")) == [f"Step {i}" for i in range(1, 6)]
    c.post("/api/ai/undo", json={"action_id": card["action_id"]})       # undo the batch together
    assert sorted(t for t in tasks(c) if t.startswith("Step")) == ["Step 1", "Step 2", "Step 3"]


@pytest.mark.parametrize("said", ["COMP2001", "comp2001", "Data Structures", "  comp2001   data structures "])
def test_a_subject_by_its_unit_code_or_part_of_its_name(c, fake, said):
    ready(c)
    s = c.post("/api/subjects", json={"name": "COMP2001 Data Structures", "color": "#3B6EA8"}).json()
    c.post("/api/subjects", json={"name": "MATH1131 Calculus", "color": "#A83B3B"})
    fake.script = [[calls(("add_task", {"title": "Lab report", "subject": said}))], [{"type": "text", "text": "ok"}]]
    assert any(e["type"] == "action" for e in chat(c))
    assert tasks(c)["Lab report"]["subject_id"] == s["id"]
    assert "The student's subjects: COMP2001 Data Structures; MATH1131 Calculus." in fake.rounds[0]["system"]


@pytest.mark.parametrize("said", ["COMP", "Data", "2001", "Structures Data"])
def test_a_subject_that_isnt_one_subjects_whole_words_goes_back_to_the_model(c, fake, said):
    ready(c)
    c.post("/api/subjects", json={"name": "COMP2001 Data Structures", "color": "#3B6EA8"})
    c.post("/api/subjects", json={"name": "COMP3001 Data Mining", "color": "#3B6EA8"})
    fake.script = [[calls(("add_task", {"title": "Lab report", "subject": said}))], [{"type": "text", "text": "Which one?"}]]
    assert not [e for e in chat(c) if e["type"] == "action"]
    assert "Lab report" not in tasks(c)
    assert "use one of: COMP2001 Data Structures, COMP3001 Data Mining" in json.dumps(fake.rounds[1]["messages"])


def test_list_tasks_and_mistakes_go_back_to_the_model(c, fake):
    ready(c)
    c.post("/api/tasks", json={"title": "Stats quiz"})
    fake.script = [[calls(("list_tasks", {"search": "quiz"}), ("update_task", {"id": 9999, "title": "x"}),
                          ("add_task", {"title": "Bad subject", "subject": "Astrology"}), ("add_task", {"title": ""}),
                          ("make_coffee", {}))], [{"type": "text", "text": "Sorry."}]]
    ev = chat(c)
    assert not [e for e in ev if e["type"] in ("action", "confirm")]
    told = json.dumps(fake.rounds[1]["messages"])
    assert "Stats quiz" in told and "no task with id 9999" in told and "isn't one of the student's subjects" in told
    assert "needs a title" in told and "no tool called make_coffee" in told
    assert "Bad subject" not in tasks(c)


def test_tool_rounds_are_limited(c, fake):
    ready(c)
    fake.script = [[calls(("list_tasks", {}))] for _ in range(8)]
    ev = chat(c)
    assert any(e["type"] == "error" and "too many steps" in e["message"] for e in ev) and ev[-1]["type"] == "done"
    assert len(fake.rounds) == 5


def test_no_tools_for_notes_mode_or_models_without_tool_support(c, fake):
    ready(c)
    c.post("/api/ai/chat", json={"mode": "notes", "messages": [{"role": "user", "content": "Write notes on heaps"}]})
    assert fake.rounds[-1]["tools"] is None
    fake.supports_tools = lambda model: False
    chat(c)
    assert fake.rounds[-1]["tools"] is None and "manage the student's tasks" not in fake.rounds[-1]["system"]


def test_confirm_and_undo_need_the_terms(c):
    assert c.post("/api/ai/confirm", json={"action_id": 1, "approve": True}).status_code == 403
    assert c.post("/api/ai/undo", json={"action_id": 1}).status_code == 403


def test_unknown_actions_are_404(c, fake):
    ready(c)
    assert c.post("/api/ai/undo", json={"action_id": 424242}).status_code == 404


# ── real provider formats ──

def sse(*objs):
    return "".join(f"data: {json.dumps(o)}\n\n" for o in objs)


def test_anthropic_tool_use_round_trip(c, A):
    ready(c, "anthropic", "claude-haiku-5-5")
    c.put("/api/ai/key", json={"provider": "anthropic", "key": "sk-ant-12345678"})
    bodies = []
    first = sse({"type": "message_start", "message": {"usage": {"input_tokens": 20}}},
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Adding it. "}},
                {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "tu_1", "name": "add_task"}},
                {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"title": "Ess'}},
                {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": 'ay plan"}'}},
                {"type": "message_delta", "usage": {"output_tokens": 9}})
    second = sse({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Done."}})

    def handler(req):
        bodies.append(json.loads(req.content))
        return httpx.Response(200, text=first if len(bodies) == 1 else second)
    A.AI_TRANSPORT["value"] = httpx.MockTransport(handler)
    ev = chat(c, "add an essay plan task")
    assert "".join(e.get("text", "") for e in ev) == "Adding it. \n\nDone."      # its own paragraph after the tool call
    assert any(e["type"] == "action" for e in ev) and "Essay plan" in tasks(c)
    assert bodies[0]["tools"][0]["input_schema"]
    assistant, results = bodies[1]["messages"][-2:]
    assert assistant["content"][1] == {"type": "tool_use", "id": "tu_1", "name": "add_task", "input": {"title": "Essay plan"}}
    assert results["content"][0]["tool_use_id"] == "tu_1" and "Done: Add" in results["content"][0]["content"]


def test_openai_tool_calls_round_trip_including_ollama_style_arguments(c, A):
    ready(c, "ollama", "qwen2.5:7b")
    bodies = []
    first = sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_a", "function": {"name": "add_task", "arguments": '{"title": "Revise'}}]}}]},
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": ' trees"}'}}]}}]},
                {"choices": [{"delta": {"tool_calls": [{"index": 1, "id": "call_b", "function": {"name": "add_task", "arguments": {"title": "Revise graphs"}}}]}}]})
    second = sse({"choices": [{"delta": {"content": "Added both."}}]})

    def handler(req):
        if req.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion", "tools"]})
        bodies.append(json.loads(req.content))
        return httpx.Response(200, text=first if len(bodies) == 1 else second)
    A.AI_TRANSPORT["value"] = httpx.MockTransport(handler)
    ev = chat(c, "add revision tasks")
    assert [e["summary"] for e in ev if e["type"] == "action"] == ["Add “Revise trees”", "Add “Revise graphs”"]
    assert bodies[0]["tools"][0]["function"]["name"] == "list_tasks"
    msgs = bodies[1]["messages"]
    assert msgs[-3]["tool_calls"][0]["id"] == "call_a" and msgs[-2]["role"] == "tool" and msgs[-1]["tool_call_id"] == "call_b"


def test_the_model_is_told_to_look_tasks_up_and_the_weekday(c, fake):
    """gpt-oss once listed made-up tasks instead of calling list_tasks; "next Friday" needs the weekday."""
    from datetime import date
    ready(c)
    fake.script = [[{"type": "text", "text": "ok"}]]
    chat(c, "what's on my list?")
    system = " ".join(fake.rounds[0]["system"].split())
    assert "call it before you mention, list or change any task, and never make tasks up" in system
    assert f"today is {date.today():%A} {date.today().isoformat()}" in system


@pytest.mark.parametrize("due", ["2026\u201111\u201103", "2026\u201311\u201303", " 2026-11-03 "])
def test_a_date_with_typographic_dashes_is_understood(c, fake, due):
    """gpt-oss writes dates with non-breaking hyphens; without this the model needs another (slow) round."""
    ready(c)
    fake.script = [[calls(("add_task", {"title": "Revise heaps", "due_date": due}))], [{"type": "text", "text": "ok"}]]
    assert any(e["type"] == "action" for e in chat(c))
    assert tasks(c)["Revise heaps"]["due_date"] == "2026-11-03"


def test_subjects_that_differ_only_in_case(c, fake):
    ready(c)
    upper = c.post("/api/subjects", json={"name": "Physics", "color": "#3B6EA8"}).json()
    c.post("/api/subjects", json={"name": "physics", "color": "#3B6EA8"})
    fake.script = [[calls(("add_task", {"title": "Prac", "subject": "Physics"}),
                          ("add_task", {"title": "Exam", "subject": "PHYSICS"}))], [{"type": "text", "text": "ok"}]]
    chat(c)
    assert tasks(c)["Prac"]["subject_id"] == upper["id"]           # exactly as written
    assert "Exam" not in tasks(c)                                   # either one: the model is shown both names
    assert "isn't one of the student's subjects" in json.dumps(fake.rounds[1]["messages"])


def test_text_after_a_tool_call_starts_a_new_paragraph(c, fake):
    """DeepSeek says what it's about to do, looks the tasks up, then answers: "planner.I can see" ran together."""
    ready(c)
    fake.script = [[{"type": "text", "text": "I'll look at your planner."}, calls(("list_tasks", {}))],
                   [{"type": "text", "text": "I can see "}, {"type": "text", "text": "no tasks."}]]
    text = "".join(e.get("text", "") for e in chat(c) if e["type"] == "text")
    assert text == "I'll look at your planner.\n\nI can see no tasks."
