# ruff: noqa: F811  (shared pytest fixtures)
"""v4 stage 8: running code. Real Python in temp folders: output, exit codes, input, the time limit, keep
running, Stop ending child processes, the output cap, a cleaned environment, and the routes' gates."""
import os
import sys
import time
from pathlib import Path

import pytest

from ai import runner as R
from test_ai_chat import events, ready
from test_ai_setup import A, agree, c, vault  # noqa: F401  (fixtures)

PY = f'"{sys.executable}"'


def wait(run, until=lambda r: r.status != "running", seconds=20):
    end = time.time() + seconds
    while time.time() < end and not until(run):
        time.sleep(0.05)
    return run.view()


def alive(pid: int) -> bool:
    if os.name == "nt":
        import subprocess
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:                                                   # a zombie (killed, not yet reaped) isn't running
        return "Z" not in Path(f"/proc/{pid}/stat").read_text().split()[2]
    except OSError:
        return True


@pytest.fixture()
def folder(tmp_path):
    (tmp_path / "hello.py").write_text("name = input('Name? ')\nprint('Hello', name, '✓')\n", encoding="utf-8")
    (tmp_path / "fail.py").write_text("import sys\nprint('about to fail')\nsys.exit(3)\n")
    child = "import os, time; open('child.pid', 'w').write(str(os.getpid())); time.sleep(120)"
    (tmp_path / "spawn.py").write_text(
        f"import subprocess, sys, time\np = subprocess.Popen([sys.executable, '-c', {child!r}])\n"
        "print('started', flush=True)\ntime.sleep(120)\n")
    (tmp_path / "flood.py").write_text("import sys\nfor i in range(100000):\n    print('line', i, 'x' * 40)\n")
    (tmp_path / "env.py").write_text(
        "import os\nprint(sorted(k for k in os.environ if 'TRACKADEMIC' in k or 'EASYUNITRACK' in k))\n"
        "print(os.getcwd())\n")
    return tmp_path


def test_output_input_and_exit_code(folder):
    r = R.Runner().start(1, str(folder), f"{PY} hello.py")
    v = wait(r, lambda r: "Name?" in r.output)
    assert v["output"] == "Name? " and v["status"] == "running"     # the prompt shows before any input
    r.send("Sean\n")
    v = wait(r)
    assert v["status"] == "finished" and v["exit_code"] == 0 and v["output"] == "Name? Hello Sean ✓\n"
    with pytest.raises(RuntimeError):
        r.send("again\n")
    f = wait(R.Runner().start(1, str(folder), f"{PY} fail.py"))
    assert f["exit_code"] == 3 and f["output"] == "about to fail\n"


def test_the_time_limit_ends_the_program_and_its_children(folder):
    r = R.Runner().start(1, str(folder), f"{PY} spawn.py", timeout=5)
    v = wait(r, seconds=30)
    assert v["status"] == "timed_out" and "5 s time limit" in v["reason"] and v["output"] == "started\n"
    pid = int((folder / "child.pid").read_text())
    time.sleep(0.5)
    assert not alive(pid)


def test_stop_and_keep_running(folder):
    r = R.Runner().start(1, str(folder), f"{PY} spawn.py", timeout=5, keep_running=True)
    wait(r, lambda r: "started" in r.output)
    time.sleep(6)
    assert r.status == "running"                                     # no time limit while keeping it running
    pid = int((folder / "child.pid").read_text())
    r.stop()
    v = wait(r)
    assert v["status"] == "stopped" and v["reason"] == "Stopped."
    time.sleep(0.5)
    assert not alive(pid)


def test_output_is_capped(folder, monkeypatch):
    monkeypatch.setattr(R, "MAX_OUTPUT", 5000)
    v = wait(R.Runner().start(1, str(folder), f"{PY} flood.py"), seconds=60)
    assert v["status"] == "finished" and len(v["output"]) == 5000 and v["truncated"]


def test_polling_returns_only_new_output(folder):
    r = R.Runner().start(1, str(folder), f"{PY} fail.py")
    wait(r)
    first = r.view(0)
    assert r.view(first["next"])["output"] == "" and r.view(6)["output"] == first["output"][6:]


def test_the_environment_is_cleaned_and_runs_happen_in_the_folder(folder, monkeypatch):
    monkeypatch.setenv("TRACKADEMIC_DATA_DIR", "/secret")
    monkeypatch.setenv("EASYUNITRACK_TOKEN", "abc")
    v = wait(R.Runner().start(1, str(folder), f"{PY} env.py"))
    lines = v["output"].splitlines()
    assert lines[0] == "[]" and Path(lines[1]).resolve() == folder.resolve()
    env = R.clean_env()
    assert env["PYTHONUNBUFFERED"] == "1" and "TRACKADEMIC_DATA_DIR" not in env


def test_a_bundle_path_is_taken_out_of_the_environment(monkeypatch):
    bundle, mine = os.path.join(os.sep, "apps", "EasyUniTrack", "_internal"), os.path.join(os.sep, "tools", "python")
    monkeypatch.setattr(R.sys, "_MEIPASS", bundle, raising=False)
    monkeypatch.setenv("PATH", os.pathsep.join([bundle, mine]))
    monkeypatch.setenv("TCL_LIBRARY", os.path.join(bundle, "tcl"))
    env = R.clean_env()
    assert env["PATH"] == mine and "TCL_LIBRARY" not in env


def test_localhost_addresses_become_links(folder):
    (folder / "srv.py").write_text("print('Running on http://127.0.0.1:5000/ (Press CTRL+C)')\n")
    v = wait(R.Runner().start(1, str(folder), f"{PY} srv.py"))
    assert v["links"] == ["http://127.0.0.1:5000/"]


def test_too_many_at_once(folder, monkeypatch):
    monkeypatch.setattr(R, "MAX_RUNNING", 1)
    runner = R.Runner()
    first = runner.start(1, str(folder), f"{PY} spawn.py", keep_running=True)
    try:
        with pytest.raises(RuntimeError, match="already running"):
            runner.start(1, str(folder), f"{PY} fail.py")
    finally:
        first.stop()


# ── what can be run ──
TOOLS = {"python": {"command": "python"}, "node": {}, "npm": {}, "mvn": {}, "dotnet": {}, "go": {}, "gcc": {}}


def test_suggestions_for_projects(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {"dev": "vite", "test": "vitest"}, "dependencies": {"react": "1"}}')
    (tmp_path / "manage.py").write_text("")
    (tmp_path / "pom.xml").write_text("<project>spring-boot</project>")
    (tmp_path / "go.mod").write_text("module x")
    s = {x["command"]: x for x in R.suggestions(tmp_path, "", TOOLS)["commands"]}
    assert s["npm run dev"]["keep_running"] and "React" in s["npm run dev"]["label"]
    assert not s["npm run test"]["keep_running"]
    assert s["python manage.py runserver"]["keep_running"] and s["mvn -q spring-boot:run"]["keep_running"]
    assert "go test ./..." in s and s["go run ."]["missing"] == []


def test_suggestions_for_single_files(tmp_path):
    (tmp_path / "game.py").write_text("import pygame\n")
    (tmp_path / "Main.java").write_text("class Main {}")
    (tmp_path / "prog.c").write_text("int main(){}")
    (tmp_path / "q.sql").write_text("select 1;")
    (tmp_path / "Program.cs").write_text("class P {}")
    one = lambda f: R.suggestions(tmp_path, f, TOOLS)          # noqa: E731
    assert one("game.py")["commands"][0]["why"] == "Opens its own window"
    java = one("Main.java")["commands"][0]
    assert java["command"] == "java Main.java" and java["missing"] == ["java"]
    windows = os.name == "nt"
    assert one("prog.c")["commands"][0]["command"] == ("gcc prog.c -o prog.exe && prog.exe" if windows
                                                       else "gcc prog.c -o prog && ./prog")
    # rustc writes exactly the name it's given, so Windows needs .exe; names with spaces are quoted
    (tmp_path / "my prog.rs").write_text("fn main() {}")
    assert one("my prog.rs")["commands"][0]["command"] == ('rustc "my prog.rs" -o "my prog.exe" && "my prog.exe"' if windows
                                                           else 'rustc "my prog.rs" -o "my prog" && "./my prog"')
    assert one("q.sql")["commands"] == [] and "explained" in one("q.sql")["explain_only"]
    assert "needs a project" in one("Program.cs")["explain_only"]


def test_projects_that_cant_run_here(tmp_path):
    (tmp_path / "ProjectSettings").mkdir()
    (tmp_path / "ProjectSettings" / "ProjectVersion.txt").write_text("")
    assert "Unity" in R.suggestions(tmp_path, "", TOOLS)["explain_only"]


def test_the_store_python_stand_in_doesnt_count(monkeypatch):
    class Done:
        returncode, stdout = 9009, ""
        stderr = "Python was not found; run without arguments to install from the Microsoft Store"
    monkeypatch.setattr(R.subprocess, "run", lambda *a, **k: Done())
    assert R._probe("python.exe", ["--version"]) == ""


# ── the routes ──
@pytest.fixture()
def proj(tmp_path_factory):
    root = tmp_path_factory.mktemp("lab")
    (root / "hello.py").write_text("name = input()\nprint('Hi', name)\n")
    return root


def setup(c, proj):
    ready(c)
    c.put("/api/ai/settings", json={"code_enabled": True})
    return c.post("/api/code/folders", json={"path": str(proj)}).json()


def test_running_needs_the_run_notice_first(c, proj):
    f = setup(c, proj)
    r = c.post(f"/api/code/folders/{f['id']}/run", json={"command": f"{PY} hello.py"})
    assert r.status_code == 428
    assert c.post("/api/ai/run-notice").json() == {"run_notice": True}
    assert c.get("/api/ai/state").json()["run_notice"] is True
    run = c.post(f"/api/code/folders/{f['id']}/run", json={"command": f"{PY} hello.py"}).json()
    assert run["status"] == "running"
    assert c.post(f"/api/code/runs/{run['id']}/input", json={"text": "Sean"}).json() == {"ok": True}
    for _ in range(200):
        v = c.get(f"/api/code/runs/{run['id']}").json()
        if v["status"] != "running":
            break
        time.sleep(0.05)
    assert v["status"] == "finished" and v["output"] == "Hi Sean\n"
    assert c.get(f"/api/code/runs/{run['id']}", params={"since": 3}).json()["output"] == "Sean\n"
    assert c.post(f"/api/code/runs/{run['id']}/input", json={"text": "x"}).status_code == 409
    assert c.get("/api/code/runs/999").status_code == 404


def test_run_routes_are_gated(c, proj):
    f = setup(c, proj)
    c.post("/api/ai/run-notice")
    c.put("/api/ai/settings", json={"code_enabled": False})
    assert c.post(f"/api/code/folders/{f['id']}/run", json={"command": "echo hi"}).status_code == 403
    assert c.get("/api/code/toolchains").status_code == 403
    c.post("/api/ai/terms/withdraw")
    assert c.post("/api/ai/run-notice").status_code == 403
    agree(c)


def test_commands_for_the_open_file(c, proj):
    f = setup(c, proj)
    r = c.get(f"/api/code/folders/{f['id']}/commands", params={"open_file": "hello.py"}).json()
    assert r["commands"][0]["label"] == "Run hello.py" and r["explain_only"] == ""
    assert c.get(f"/api/code/folders/{f['id']}/commands", params={"open_file": "../x.py"}).json()["explain_only"]


def test_the_assistant_can_only_suggest_a_run(c, proj, monkeypatch):
    from ai.providers.fake import FakeProvider
    import ai.routes
    p = FakeProvider()
    p.script = [[{"type": "tool_calls", "calls": [{"id": "c0", "name": "suggest_run",
                                                    "args": {"command": "python -m pytest", "why": "See which test fails"}}]}],
                [{"type": "text", "text": "Try running the tests."}]]
    monkeypatch.setattr(ai.routes, "get_provider", lambda *a, **k: p)
    f = setup(c, proj)
    ev = events(c.post("/api/ai/chat", json={"mode": "code", "code": {"folder_id": f["id"], "files": []},
                                              "messages": [{"role": "user", "content": "why do my tests fail"}]}))
    assert {"type": "run_suggestion", "command": "python -m pytest", "why": "See which test fails"} in ev
    assert "It runs only if they click Run" in str(p.rounds[-1]["messages"])
    assert "never say you ran it" in p.rounds[0]["system"]


def test_all_output_is_in_before_the_run_counts_as_finished(folder):
    """The status only changes once the last of the output (a traceback, say) has been read."""
    (folder / "crash.py").write_text("print('start')\nraise ValueError('the last line')\n")
    for _ in range(10):
        v = wait(R.Runner().start(1, str(folder), f"{PY} crash.py"))
        assert v["status"] == "finished" and "ValueError: the last line" in v["output"]


def test_colour_is_off_in_the_output_panel(monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    env = R.clean_env()
    assert "FORCE_COLOR" not in env and env["NO_COLOR"] == "1"


def test_suggesting_commands_doesnt_run_any_tools(tmp_path, monkeypatch):
    """Opening the workspace mustn't wait for dozens of `--version` checks (CI machines have many tools)."""
    monkeypatch.setattr(R, "_found_cache", {"at": 0.0, "tools": None})
    monkeypatch.setattr(R, "_stand_in", lambda path: False)
    monkeypatch.setattr(R, "_probe", lambda *a: pytest.fail("ran a tool"))
    (tmp_path / "a.py").write_text("print(1)\n")
    assert R.suggestions(tmp_path, "a.py")["commands"]


def test_versions_are_checked_all_at_once(monkeypatch):
    monkeypatch.setattr(R, "_tool_cache", {"at": 0.0, "tools": None})
    monkeypatch.setattr(R, "available", lambda refresh=False: {n: {"path": n, "command": n} for n in list(R.TOOLS)[:8]})
    monkeypatch.setattr(R, "_probe", lambda path, args: time.sleep(0.5) or "v1")
    start = time.time()
    found = R.toolchains(refresh=True)
    assert len(found) == 8 and all(t["version"] == "v1" for t in found.values()) and time.time() - start < 3   # one by one: 4 s


def test_links_are_found_as_output_arrives_even_when_split():
    run = R.Run(1, "x", ".", 30, False)
    run._add("Serving at http://local")
    run._add("host:8000/ now\n")
    for i in range(10):
        run._add(f"http://127.0.0.1:{9000 + i}/\n")
    v = run.view()
    assert v["links"][0] == "http://localhost:8000/" and len(v["links"]) == 5


@pytest.mark.skipif(os.name != "nt", reason="Windows starts runs suspended")
def test_a_run_that_cant_be_resumed_is_ended_not_left_hanging(folder, monkeypatch):
    class NoResume:
        @staticmethod
        def NtResumeProcess(handle):
            return 0xC0000001                                  # STATUS_UNSUCCESSFUL
    monkeypatch.setattr(R, "_ntdll", NoResume)
    run = R.Run(1, f"{PY} fail.py", str(folder), 30, False)
    with pytest.raises(OSError, match="couldn't be started"):
        run.start(R.clean_env())
    assert run.proc.wait(timeout=10) is not None


def test_the_running_limit_holds_when_starts_arrive_together(folder, monkeypatch):
    """Several requests at the same moment (two folders, say) can't get past the limit together."""
    import threading
    monkeypatch.setattr(R, "MAX_RUNNING", 2)
    runner, go, results = R.Runner(), threading.Barrier(6), []

    def start():
        go.wait()
        try:
            results.append(runner.start(1, str(folder), f"{PY} spawn.py", keep_running=True))
        except RuntimeError:
            results.append(None)
    threads = [threading.Thread(target=start) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    started = [r for r in results if r]
    try:
        assert len(results) == 6 and len(started) == 2
    finally:
        runner.stop_all()


def test_a_run_that_cant_be_watched_is_stopped_not_left_running(folder, monkeypatch):
    real = R.threading.Thread

    class NoThreads(real):
        def start(self):
            raise RuntimeError("can't start new thread")
    monkeypatch.setattr(R.threading, "Thread", NoThreads)
    run = R.Run(1, f"{PY} spawn.py", str(folder), 30, False)
    with pytest.raises(OSError, match="couldn't be watched"):
        run.start(R.clean_env())
    assert run.proc.poll() is not None
