# ruff: noqa: F811  (shared pytest fixtures)
"""v4 stage 9: the computer science quick actions (Trace, Big-O, Visualise, tests, Explain my change, practice)
and the diff behind Explain my change, which must never run programs from a downloaded repo's git config."""
import os
import shutil
import subprocess
import sys

import pytest

from ai import codediff
from ai.codebase import CodeError, Folder
from test_ai_chat import events, fake, ready  # noqa: F401  (fixtures)
from test_ai_setup import A, agree, c, vault  # noqa: F401  (fixtures)

GIT = shutil.which("git")
needs_git = pytest.mark.skipif(not GIT, reason="git isn't installed")


# None of git's own variables (set when the tests run from a git hook), so these commands only touch temp repos
CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}


def git(root, *args):
    subprocess.run([GIT, "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                   check=True, capture_output=True, env=CLEAN_ENV)


@pytest.fixture()
def proj(tmp_path_factory):
    root = tmp_path_factory.mktemp("lab")
    (root / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (root / ".env").write_text("KEY=1\n")
    return root


def setup(c, proj, mode="assignment"):
    ready(c)
    c.put("/api/ai/settings", json={"code_enabled": True})
    return c.post("/api/code/folders", json={"path": str(proj), "mode": mode}).json()


def ask(c, folder, action, diff="", files=("calc.py",)):
    return c.post("/api/ai/chat", json={"mode": "code", "messages": [{"role": "user", "content": "go"}],
                                        "code": {"folder_id": folder["id"], "files": list(files), "action": action,
                                                 "diff": diff}})


@pytest.mark.parametrize("action,expect", [
    ("trace", "dry-run table"), ("big_o", "Big-O"), ("visualise", "Mermaid diagram"), ("practice", "Don't give the solution"),
    ("explain_error", "explain the error"), ("debug", "Task: debug"),
])
def test_each_action_adds_its_instructions(c, fake, proj, action, expect):
    f = setup(c, proj)
    assert ask(c, f, action).status_code == 200
    assert expect in fake.last["system"] and "--- calc.py (Python) ---" in fake.last["system"]


def test_tests_are_planned_in_an_assignment_and_written_in_a_personal_project(c, fake, proj):
    f = setup(c, proj)
    ask(c, f, "tests")
    assert "Don't write the test code" in fake.last["system"]
    c.put(f"/api/code/folders/{f['id']}", json={"mode": "personal"})
    ask(c, f, "tests")
    assert "propose them as a test file" in fake.last["system"] and "Don't write the test code" not in fake.last["system"]


def test_the_diff_goes_only_with_explain_my_change(c, fake, proj):
    f = setup(c, proj)
    ask(c, f, "explain_change", diff="-    return a - b\n+    return a + b")
    assert "Task: explain my change" in fake.last["system"] and "+    return a + b" in fake.last["system"]
    ask(c, f, "trace", diff="+ sneaky")
    assert "sneaky" not in fake.last["system"]
    ask(c, f, None)
    assert "Task:" not in fake.last["system"]
    assert ask(c, f, "write_my_assignment").status_code == 422


# ── what changed ──
@needs_git
def test_changes_since_the_last_commit(proj):
    git(proj, "init", "-q")
    git(proj, "add", "calc.py")
    git(proj, "commit", "-q", "-m", "first")
    (proj / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    r = codediff.changes(Folder(str(proj)), "calc.py")
    assert r["source"] == "git" and "-    return a - b" in r["diff"] and "+    return a + b" in r["diff"]
    (proj / "new.py").write_text("x = 1\n")
    r = codediff.changes(Folder(str(proj)), "new.py")
    assert r["source"] == "git" and r["new_file"] and "+x = 1" in r["diff"]


@needs_git
def test_a_file_in_a_subfolder_of_the_repo(tmp_path):
    (tmp_path / "unit1").mkdir()
    (tmp_path / "unit1" / "a.py").write_text("x = 1\n")
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "first")
    (tmp_path / "unit1" / "a.py").write_text("x = 2\n")
    r = codediff.changes(Folder(str(tmp_path / "unit1")), "a.py")       # the linked folder is inside the repo
    assert r["source"] == "git" and "+x = 2" in r["diff"]


def test_changes_since_opening_without_git(proj, monkeypatch):
    monkeypatch.setattr(codediff.shutil, "which", lambda name: None)
    f = Folder(str(proj))
    assert codediff.changes(f, "calc.py") == {"source": "none", "diff": "", "truncated": False}
    r = codediff.changes(f, "calc.py", baseline="def add(a, b):\r\n    return a * b\r\n")
    assert r["source"] == "opened" and "-    return a * b" in r["diff"] and "+    return a - b" in r["diff"]
    with pytest.raises(CodeError, match="hidden"):
        codediff.changes(f, ".env", baseline="")


@needs_git
def test_a_downloaded_repo_cant_run_programs_through_its_git_config(proj, tmp_path):
    """Filters, textconv drivers and a file-system monitor in the repo's own config each run a program with
    `git diff`. Explain my change reads the committed copy instead, so none of them run."""
    marker = tmp_path / "PWNED"
    cmd = f'"{sys.executable}" -c "open(r\'{marker}\', \'w\').close()"'.replace("\\", "/")
    git(proj, "init", "-q")
    (proj / ".gitattributes").write_text("*.py filter=evil diff=evil\n")
    git(proj, "add", "calc.py", ".gitattributes")
    git(proj, "commit", "-q", "-m", "first")
    git(proj, "config", "filter.evil.clean", cmd)
    git(proj, "config", "diff.evil.textconv", cmd)
    git(proj, "config", "core.fsmonitor", cmd)
    (proj / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    r = codediff.changes(Folder(str(proj)), "calc.py")
    assert r["source"] == "git" and "+    return a + b" in r["diff"]
    assert not marker.exists()
    subprocess.run([GIT, "-C", str(proj), "diff"], capture_output=True, env=CLEAN_ENV)   # what a plain git diff would do
    assert marker.exists(), "the test's trap didn't fire, so it proves nothing"


@needs_git
def test_git_variables_from_where_the_app_started_are_ignored(proj, tmp_path, monkeypatch):
    """Started from a git hook or a developer's shell, GIT_DIR would point git at another repository."""
    other = tmp_path / "other"
    other.mkdir()
    (other / "calc.py").write_text("something else entirely\n")
    git(other, "init", "-q")
    git(other, "add", "calc.py")
    git(other, "commit", "-q", "-m", "other")
    git(proj, "init", "-q")
    git(proj, "add", "calc.py")
    git(proj, "commit", "-q", "-m", "first")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    (proj / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    r = codediff.changes(Folder(str(proj)), "calc.py")
    assert "-    return a - b" in r["diff"] and "something else" not in r["diff"]


def test_the_diff_route(c, proj, monkeypatch):
    monkeypatch.setattr(codediff.shutil, "which", lambda name: None)
    f = setup(c, proj)
    r = c.post(f"/api/code/folders/{f['id']}/diff", json={"path": "calc.py", "baseline": "old\n"}).json()
    assert r["source"] == "opened" and "+    return a - b" in r["diff"]
    assert c.post(f"/api/code/folders/{f['id']}/diff", json={"path": "../x.py"}).status_code == 400
    c.post("/api/ai/terms/withdraw")
    assert c.post(f"/api/code/folders/{f['id']}/diff", json={"path": "calc.py"}).status_code == 403
    agree(c)
