# ruff: noqa: F811  (shared pytest fixtures)
"""v4 stage 7: proposed changes. The assistant proposes, the student applies; backups, exact Undo, stale changes
refused, writes kept inside the folder, and small changes only in an Assignment folder."""
import pytest

from test_ai_chat import events, ready
from test_ai_setup import A, agree, c, vault  # noqa: F401  (fixtures)

ORIGINAL = b"def add(a, b):\r\n    return a - b\r\n\r\nprint(add(2, 3))"          # CRLF, no final newline


@pytest.fixture()
def fake(monkeypatch):
    from ai.providers.fake import FakeProvider
    import ai.routes
    p = FakeProvider()
    p.script = []
    monkeypatch.setattr(ai.routes, "get_provider", lambda *a, **k: p)
    return p


@pytest.fixture()
def proj(tmp_path_factory):
    root = tmp_path_factory.mktemp("lab")
    (root / "calc.py").write_bytes(ORIGINAL)
    (root / ".env").write_text("KEY=1\n")
    return root


def setup(c, proj, mode="personal"):
    ready(c)
    c.put("/api/ai/settings", json={"code_enabled": True})
    return c.post("/api/code/folders", json={"path": str(proj), "mode": mode}).json()


def propose(c, fake, folder, *calls, text="Done."):
    fake.script = [[{"type": "tool_calls", "calls": [{"id": f"c{i}", "name": "propose_change", "args": a}
                                                       for i, a in enumerate(calls)]}],
                   [{"type": "text", "text": text}]]
    r = c.post("/api/ai/chat", json={"mode": "code", "code": {"folder_id": folder["id"], "files": ["calc.py"]},
                                     "messages": [{"role": "user", "content": "fix it"}]})
    return events(r)


def cards(ev):
    return [e for e in ev if e["type"] == "change"]


def test_apply_writes_the_change_and_undo_restores_exact_bytes(c, fake, proj, A):
    f = setup(c, proj)
    ev = propose(c, fake, f, {"path": "calc.py", "find": "    return a - b", "replace": "    return a + b",
                              "summary": "Add instead of subtract"})
    card = cards(ev)[0]
    assert card["path"] == "calc.py" and card["summary"] == "Add instead of subtract" and not card["new_file"]
    assert {"t": "-", "s": "    return a - b"} in card["diff"] and {"t": "+", "s": "    return a + b"} in card["diff"]
    assert (proj / "calc.py").read_bytes() == ORIGINAL                      # nothing written yet
    assert "don't say it's applied" in str(fake.rounds[-1]["messages"])
    r = c.post(f"/api/code/changes/{card['change_id']}/apply").json()
    assert r == {"status": "applied", "path": "calc.py", "created": False}
    assert (proj / "calc.py").read_bytes() == ORIGINAL.replace(b"a - b", b"a + b")   # CRLF and no final newline kept
    backups = list((A.DB_PATH.parent / "code-backups").iterdir())
    assert len(backups) == 1 and backups[0].read_bytes() == ORIGINAL
    assert c.post(f"/api/code/changes/{card['change_id']}/apply").status_code == 409   # not twice
    assert c.post(f"/api/code/changes/{card['change_id']}/undo").json()["status"] == "undone"
    assert (proj / "calc.py").read_bytes() == ORIGINAL
    assert c.post(f"/api/code/changes/{card['change_id']}/undo").status_code == 409


def test_a_file_changed_since_the_proposal_is_refused(c, fake, proj):
    f = setup(c, proj)
    card = cards(propose(c, fake, f, {"path": "calc.py", "find": "a - b", "replace": "a + b", "summary": "fix"}))[0]
    (proj / "calc.py").write_bytes(ORIGINAL + b"\r\n# my edit\r\n")
    r = c.post(f"/api/code/changes/{card['change_id']}/apply")
    assert r.status_code == 409 and "fresh change" in r.json()["detail"]
    assert (proj / "calc.py").read_bytes() == ORIGINAL + b"\r\n# my edit\r\n"
    assert c.post(f"/api/code/changes/{card['change_id']}/apply").status_code == 409     # stays refused


def test_undo_refuses_to_overwrite_later_edits(c, fake, proj):
    f = setup(c, proj)
    card = cards(propose(c, fake, f, {"path": "calc.py", "find": "a - b", "replace": "a + b", "summary": "fix"}))[0]
    c.post(f"/api/code/changes/{card['change_id']}/apply")
    (proj / "calc.py").write_bytes(b"my own rewrite\n")
    r = c.post(f"/api/code/changes/{card['change_id']}/undo")
    assert r.status_code == 409 and "lose those edits" in r.json()["detail"]
    assert (proj / "calc.py").read_bytes() == b"my own rewrite\n"


def test_a_new_file_is_created_and_undo_removes_it(c, fake, proj):
    f = setup(c, proj)
    card = cards(propose(c, fake, f, {"path": "tests/test_calc.py", "replace": "from calc import add\n",
                                      "summary": "Add a test"}))[0]
    assert card["new_file"] and {"t": "+", "s": "from calc import add"} in card["diff"]
    assert c.post(f"/api/code/changes/{card['change_id']}/apply").json()["created"] is True
    assert (proj / "tests" / "test_calc.py").read_text() == "from calc import add\n"
    c.post(f"/api/code/changes/{card['change_id']}/undo")
    assert not (proj / "tests" / "test_calc.py").exists()


def test_two_edits_to_one_file_make_one_card(c, fake, proj):
    f = setup(c, proj)
    ev = propose(c, fake, f, {"path": "calc.py", "find": "a - b", "replace": "a + b", "summary": "fix the sum"},
                 {"path": "calc.py", "find": "print(add(2, 3))", "replace": "print(add(2, 3))  # 5", "summary": "note"})
    ids = {e["change_id"] for e in cards(ev)}
    assert len(ids) == 1
    c.post(f"/api/code/changes/{ids.pop()}/apply")
    assert (proj / "calc.py").read_bytes() == ORIGINAL.replace(b"a - b", b"a + b").replace(b"3))", b"3))  # 5")


@pytest.mark.parametrize("args,why", [
    ({"path": "../outside.py", "replace": "x = 1\n"}, "outside"),
    ({"path": "C:/Windows/x.py", "replace": "x = 1\n"}, "outside"),
    ({"path": ".env", "find": "KEY=1", "replace": "KEY=2"}, "hidden"),
    ({"path": "node_modules/x.js", "replace": "x\n"}, "hidden folder"),
    ({"path": "calc.py", "find": "not there", "replace": "y"}, "isn't in calc.py"),
    ({"path": "calc.py", "find": "a", "replace": "y"}, "appears"),
    ({"path": "calc.py", "find": "a - b", "replace": "a - b"}, "doesn't change anything"),
])
def test_bad_proposals_go_back_to_the_model(c, fake, proj, args, why):
    f = setup(c, proj)
    ev = propose(c, fake, f, {"summary": "x", **args})
    assert cards(ev) == []
    assert why in str(fake.rounds[-1]["messages"])
    assert (proj / "calc.py").read_bytes() == ORIGINAL and not (proj.parent / "outside.py").exists()


def test_assignment_folders_get_small_changes_only(c, fake, proj):
    f = setup(c, proj, mode="assignment")
    ev = propose(c, fake, f, {"path": "calc.py", "replace": "everything new\n", "summary": "rewrite"})
    assert cards(ev) == [] and "find and replace" in str(fake.rounds[-1]["messages"])
    big = "\n".join(f"line {i}" for i in range(20))
    ev = propose(c, fake, f, {"path": "calc.py", "find": "    return a - b", "replace": big, "summary": "big"})
    assert cards(ev) == [] and "at most 12 changed lines" in str(fake.rounds[-1]["messages"])
    ev = propose(c, fake, f, {"path": "calc.py", "find": "a - b", "replace": "a + b", "summary": "small"})
    assert len(cards(ev)) == 1
    assert "only when the student asks for a fix" in fake.rounds[0]["system"]


def test_line_numbers_copied_from_the_context_are_ignored(c, fake, proj):
    f = setup(c, proj)
    ev = propose(c, fake, f, {"path": "calc.py", "find": "   2|     return a - b", "replace": "   2|     return a + b",
                              "summary": "fix"})
    assert c.post(f"/api/code/changes/{cards(ev)[0]['change_id']}/apply").status_code == 200
    assert b"return a + b" in (proj / "calc.py").read_bytes()


def test_indentation_left_off_by_the_model_is_put_back(c, fake, proj):
    """What gemma4:e4b really sent: find without the indent, and the new lines from column 0."""
    f = setup(c, proj)
    card = cards(propose(c, fake, f, {"path": "calc.py", "find": "return a - b",
                                      "replace": "if a is None:\n    return b\nreturn a + b", "summary": "fix"}))[0]
    c.post(f"/api/code/changes/{card['change_id']}/apply")
    assert (proj / "calc.py").read_bytes() == ORIGINAL.replace(
        b"    return a - b", b"    if a is None:\r\n        return b\r\n    return a + b")


def test_match_indent_leaves_correct_replacements_alone():
    from ai.code_changes import match_indent
    code = "def f():\n    return 1\n"
    assert match_indent(code, "    return 1", "    x = 1\n    return x") == "    x = 1\n    return x"
    assert match_indent(code, "return 1", "return 2") == "return 2"                 # one line: nothing to do
    assert match_indent(code, "def f():", "def g():\n    pass") == "def g():\n    pass"  # starts at column 0


def test_dismiss_and_the_gate(c, fake, proj):
    f = setup(c, proj)
    card = cards(propose(c, fake, f, {"path": "calc.py", "find": "a - b", "replace": "a + b", "summary": "fix"}))[0]
    assert c.post(f"/api/code/changes/{card['change_id']}/dismiss").json() == {"status": "dismissed"}
    assert c.post(f"/api/code/changes/{card['change_id']}/apply").status_code == 409
    assert (proj / "calc.py").read_bytes() == ORIGINAL
    c.put("/api/ai/settings", json={"code_enabled": False})
    assert c.post(f"/api/code/changes/{card['change_id']}/undo").status_code == 403
    agree(c)


def test_without_tool_support_there_is_no_tool(c, fake, proj, monkeypatch):
    f = setup(c, proj)
    monkeypatch.setattr(fake, "supports_tools", lambda model: False, raising=False)
    c.post("/api/ai/chat", json={"mode": "code", "code": {"folder_id": f["id"], "files": []},
                                 "messages": [{"role": "user", "content": "hi"}]})
    assert fake.last["tools"] is None


def test_a_forgotten_find_doesnt_replace_the_whole_file(c, fake, proj):
    """What gemma4:e4b really did once: one new line and no find, which would have wiped the file."""
    f = setup(c, proj)
    ev = propose(c, fake, f, {"path": "calc.py", "replace": "    return a + b", "summary": "fix"})
    assert cards(ev) == [] and "Give find" in str(fake.rounds[-1]["messages"])
    ev = propose(c, fake, f, {"path": "calc.py", "replace": "def add(a, b):\n    return a + b\n", "summary": "rewrite",
                              "whole_file": True})
    c.post(f"/api/code/changes/{cards(ev)[0]['change_id']}/apply")
    assert (proj / "calc.py").read_bytes() == b"def add(a, b):\r\n    return a + b\r\n"


@pytest.mark.skipif(__import__("os").name == "nt", reason="execute permissions are a POSIX thing")
def test_apply_and_undo_keep_file_permissions(c, fake, proj):
    import os
    os.chmod(proj / "calc.py", 0o755)
    f = setup(c, proj)
    card = cards(propose(c, fake, f, {"path": "calc.py", "find": "a - b", "replace": "a + b", "summary": "fix"}))[0]
    assert c.post(f"/api/code/changes/{card['change_id']}/apply").status_code == 200
    assert (proj / "calc.py").read_bytes() == ORIGINAL.replace(b"a - b", b"a + b")
    assert os.stat(proj / "calc.py").st_mode & 0o777 == 0o755
    assert c.post(f"/api/code/changes/{card['change_id']}/undo").status_code == 200
    assert (proj / "calc.py").read_bytes() == ORIGINAL
    assert os.stat(proj / "calc.py").st_mode & 0o777 == 0o755


def test_write_keeps_the_original_mode(tmp_path):
    import os
    import stat as st
    from ai.code_changes import ChangeStore
    target = tmp_path / "s.sh"
    target.write_text("echo 1\n")
    os.chmod(target, st.S_IREAD | st.S_IWRITE)
    before = st.S_IMODE(os.stat(target).st_mode)
    ChangeStore.write(target, b"echo 2\n")
    assert target.read_bytes() == b"echo 2\n" and st.S_IMODE(os.stat(target).st_mode) == before
    ChangeStore.write(tmp_path / "new.txt", b"x")
    assert os.stat(tmp_path / "new.txt").st_mode & st.S_IREAD


# ── an edit saved at the worst moment is never overwritten ──
def editor_saves_during(monkeypatch, target, content):
    """Make the student's editor save the file just after the app's check, while the new file is being made."""
    from ai.code_changes import ChangeStore
    real = ChangeStore._temp

    def temp(t, data, mode):
        target.write_bytes(content)
        return real(t, data, mode)
    monkeypatch.setattr(ChangeStore, "_temp", staticmethod(temp))


def test_apply_never_overwrites_an_edit_saved_after_the_check(c, fake, proj, monkeypatch):
    f = setup(c, proj)
    card = cards(propose(c, fake, f, {"path": "calc.py", "find": "a - b", "replace": "a + b", "summary": "fix"}))[0]
    editor_saves_during(monkeypatch, proj / "calc.py", b"saved just now\n")
    r = c.post(f"/api/code/changes/{card['change_id']}/apply")
    assert r.status_code == 409 and "has changed since" in r.json()["detail"]
    assert (proj / "calc.py").read_bytes() == b"saved just now\n"
    assert [p.name for p in proj.iterdir() if p.name.startswith(".eut-")] == []          # nothing left behind


def test_undo_never_overwrites_an_edit_saved_after_the_check(c, fake, proj, monkeypatch):
    f = setup(c, proj)
    card = cards(propose(c, fake, f, {"path": "calc.py", "find": "a - b", "replace": "a + b", "summary": "fix"}))[0]
    c.post(f"/api/code/changes/{card['change_id']}/apply")
    editor_saves_during(monkeypatch, proj / "calc.py", b"saved just now\n")
    r = c.post(f"/api/code/changes/{card['change_id']}/undo")
    assert r.status_code == 409 and (proj / "calc.py").read_bytes() == b"saved just now\n"
    monkeypatch.undo()
    (proj / "calc.py").write_bytes(ORIGINAL.replace(b"a - b", b"a + b"))
    assert c.post(f"/api/code/changes/{card['change_id']}/undo").status_code == 200       # still undoable after


def test_swap_puts_nothing_where_a_file_appeared(tmp_path):
    from ai.code_changes import ChangeStore, Conflict
    target = tmp_path / "new.py"
    target.write_bytes(b"someone else's\n")
    with pytest.raises(Conflict):
        ChangeStore.swap(target, b"mine\n", None)
    assert target.read_bytes() == b"someone else's\n" and len(list(tmp_path.iterdir())) == 1


# ── a change cut off part-way (the app closed during Apply or Undo) ──
def cut_off(c, A, fake, proj, file_bytes, status="applying"):
    f = setup(c, proj)
    card = cards(propose(c, fake, f, {"path": "calc.py", "find": "a - b", "replace": "a + b", "summary": "fix"}))[0]
    from ai.code_changes import ChangeStore, sha
    store = ChangeStore(A.db, A.DB_PATH.parent)
    new = ORIGINAL.replace(b"a - b", b"a + b")
    backup = A.DB_PATH.parent / "code-backups" / f"{card['change_id']}-calc.py"
    backup.parent.mkdir(exist_ok=True)
    backup.write_bytes(ORIGINAL)
    store.set(card["change_id"], status=status, backup=str(backup), applied_hash=sha(new))
    (proj / "calc.py").write_bytes(file_bytes)
    store.recover()
    return store.get(card["change_id"])["status"], card["change_id"]


def test_recover_an_apply_that_finished_writing(c, A, fake, proj):
    status, cid = cut_off(c, A, fake, proj, ORIGINAL.replace(b"a - b", b"a + b"))
    assert status == "applied"
    assert c.post(f"/api/code/changes/{cid}/undo").status_code == 200 and (proj / "calc.py").read_bytes() == ORIGINAL


def test_recover_an_apply_that_never_wrote(c, A, fake, proj):
    assert cut_off(c, A, fake, proj, ORIGINAL)[0] == "proposed"


def test_recover_an_apply_when_the_file_is_something_else(c, A, fake, proj):
    assert cut_off(c, A, fake, proj, b"edited meanwhile\n")[0] == "stale"


def test_recover_an_undo(c, A, fake, proj):
    assert cut_off(c, A, fake, proj, ORIGINAL, status="undoing")[0] == "undone"


def test_without_hard_links_nothing_is_overwritten_either(tmp_path, monkeypatch):
    import errno
    import os
    from ai.code_changes import ChangeStore, Conflict

    def no_links(*a):
        raise OSError(errno.EPERM, "no hard links here")
    monkeypatch.setattr(os, "link", no_links)
    src, target = tmp_path / "src", tmp_path / "target.py"
    src.write_bytes(b"mine\n")
    target.write_bytes(b"theirs\n")
    with pytest.raises(Conflict):
        ChangeStore._put(src, target)
    assert target.read_bytes() == b"theirs\n" and src.exists()
    target.unlink()
    ChangeStore._put(src, target)
    assert target.read_bytes() == b"mine\n" and not src.exists()


def test_recover_puts_back_a_file_moved_aside_during_apply(c, A, fake, proj):
    from ai.code_changes import ChangeStore
    f = setup(c, proj)
    card = cards(propose(c, fake, f, {"path": "calc.py", "find": "a - b", "replace": "a + b", "summary": "fix"}))[0]
    store = ChangeStore(A.db, A.DB_PATH.parent)
    store.set(card["change_id"], status="applying")
    (proj / "calc.py").rename(ChangeStore.hold_path(proj / "calc.py", str(card["change_id"])))   # crash here
    store.recover()
    assert (proj / "calc.py").read_bytes() == ORIGINAL and store.get(card["change_id"])["status"] == "proposed"
    assert [p.name for p in proj.iterdir() if p.name.startswith(".eut-")] == []


def test_recover_finishes_undoing_a_new_file(c, A, fake, proj):
    from ai.code_changes import ChangeStore
    f = setup(c, proj)
    card = cards(propose(c, fake, f, {"path": "notes.txt", "replace": "hello\n", "summary": "new"}))[0]
    c.post(f"/api/code/changes/{card['change_id']}/apply")
    store = ChangeStore(A.db, A.DB_PATH.parent)
    store.set(card["change_id"], status="undoing")
    (proj / "notes.txt").rename(ChangeStore.hold_path(proj / "notes.txt", str(card["change_id"])))   # crash here
    store.recover()
    assert not (proj / "notes.txt").exists() and store.get(card["change_id"])["status"] == "undone"
    assert [p.name for p in proj.iterdir() if p.name.startswith(".eut-")] == []


@pytest.mark.parametrize("written", ["half", "all"])
def test_recover_after_a_crash_while_writing_without_hard_links(c, A, fake, proj, written):
    """The crash came during the exclusive-create fallback: the file is cut off part-way, or complete."""
    from ai.code_changes import ChangeStore, sha
    f = setup(c, proj)
    card = cards(propose(c, fake, f, {"path": "calc.py", "find": "a - b", "replace": "a + b", "summary": "fix"}))[0]
    store = ChangeStore(A.db, A.DB_PATH.parent)
    new = ORIGINAL.replace(b"a - b", b"a + b")
    backup = A.DB_PATH.parent / "code-backups" / f"{card['change_id']}-calc.py"
    backup.parent.mkdir(exist_ok=True)
    backup.write_bytes(ORIGINAL)
    store.set(card["change_id"], status="applying", backup=str(backup), applied_hash=sha(new))
    (proj / "calc.py").rename(ChangeStore.hold_path(proj / "calc.py", str(card["change_id"])))
    (proj / "calc.py").write_bytes(new[:10] if written == "half" else new)
    store.recover()
    expected = (ORIGINAL, "proposed") if written == "half" else (new, "applied")
    assert ((proj / "calc.py").read_bytes(), store.get(card["change_id"])["status"]) == expected
    assert [p.name for p in proj.iterdir() if p.name.startswith(".eut-")] == []
