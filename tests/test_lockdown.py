"""The local server only answers this app: other hosts (DNS rebinding) and requests without the
session token are refused once the launchers switch the protection on."""
import importlib
import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import system_integration  # noqa: E402


@pytest.fixture()
def A(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACKADEMIC_DATA_DIR", str(tmp_path))
    import app
    importlib.reload(app)
    app.enable_lockdown()
    yield app
    app.LOCKDOWN["on"] = False


def client(A, host="127.0.0.1:8585"):
    return TestClient(A.app, base_url=f"http://{host}")


def token(A):
    return {A.TOKEN_HEADER: A.SESSION_TOKEN}


def test_off_until_a_launcher_switches_it_on(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACKADEMIC_DATA_DIR", str(tmp_path))
    import app
    importlib.reload(app)
    assert app.LOCKDOWN["on"] is False


@pytest.mark.parametrize("host", ["127.0.0.1:8585", "localhost:8585", "[::1]:8585", "LOCALHOST", "127.0.0.1"])
def test_local_addresses_are_answered(A, host):
    assert client(A, host).get("/api/info").status_code == 200


@pytest.mark.parametrize("host", ["evil.example:8585", "evil.example", "127.0.0.1.evil.example", "192.168.1.20:8585"])
def test_other_hosts_are_refused_even_for_reading(A, host):
    """DNS rebinding: a website that points its own name at 127.0.0.1 can't read or change anything."""
    c = client(A, host)
    for path in ("/api/tasks", "/api/export", "/", "/static/app.js"):
        assert c.get(path).status_code == 403, path
    assert c.post("/api/tasks", json={"title": "x"}, headers=token(A)).status_code == 403


def test_changes_need_the_token(A):
    c = client(A)
    assert c.post("/api/tasks", json={"title": "No token"}).status_code == 403
    assert c.post("/api/tasks", json={"title": "Wrong"}, headers={A.TOKEN_HEADER: "guess"}).status_code == 403
    assert c.get("/api/tasks").json() == []                     # nothing was created
    r = c.post("/api/tasks", json={"title": "From the window"}, headers=token(A))
    assert r.status_code == 200
    tid = r.json()["id"]
    for method, body in (("put", {"title": "Renamed"}), ("delete", None)):
        assert c.request(method.upper(), f"/api/tasks/{tid}", json=body).status_code == 403
    assert c.put(f"/api/tasks/{tid}", json={"title": "Renamed"}, headers=token(A)).status_code == 200
    assert c.delete(f"/api/tasks/{tid}", headers=token(A)).status_code == 200


def test_reading_needs_no_token(A):
    """Browsers already stop other websites reading these (no CORS), so the page can load freely."""
    c = client(A)
    for path in ("/api/info", "/api/tasks", "/api/diag/startup", "/static/app.js", "/manifest.json"):
        assert c.get(path).status_code == 200, path


def test_the_page_carries_the_token(A):
    html = client(A).get("/").text
    assert f'<meta name="app-token" content="{A.SESSION_TOKEN}">' in html
    assert len(A.SESSION_TOKEN) >= 32


def test_each_start_gets_a_new_token(tmp_path, monkeypatch):
    monkeypatch.setenv("TRACKADEMIC_DATA_DIR", str(tmp_path))
    import app
    first = importlib.reload(app).SESSION_TOKEN
    assert importlib.reload(app).SESSION_TOKEN != first


def test_extra_hosts_for_deliberate_network_use(A):
    A.enable_lockdown(["192.168.1.20", " my-laptop.local ", ""])
    assert client(A, "192.168.1.20:8585").get("/api/info").status_code == 200
    assert client(A, "my-laptop.local:8585").get("/api/info").status_code == 200
    assert client(A, "evil.example").get("/api/info").status_code == 403


def test_the_launchers_switch_it_on():
    src = (ROOT / "desktop.py").read_text(encoding="utf-8")
    assert "enable_lockdown()" in src.split("def start_server", 1)[1].split("def ", 1)[0]
    main = (ROOT / "app.py").read_text(encoding="utf-8").split('if __name__ == "__main__":', 1)[1]
    assert "enable_lockdown(" in main


def test_a_second_copy_can_still_bring_the_window_forward(A, tmp_path):
    """Opening the app again asks the running copy to come forward, using the token in instance.json."""
    import uvicorn
    shown = []
    A.WINDOW["show"] = lambda: shown.append(1)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(A.app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    try:
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.02)
        system_integration.claim_instance(tmp_path, port, A.SESSION_TOKEN)
        assert json.loads((tmp_path / "instance.json").read_text())["token"] == A.SESSION_TOKEN
        assert system_integration.find_running_instance(tmp_path, A.APP_NAME) == port
        assert system_integration.bring_to_front(port, "not the token") is False
        assert system_integration.bring_to_front(port, system_integration.instance_token(tmp_path)) is True
        for _ in range(100):
            if shown:
                break
            time.sleep(0.02)
        assert shown == [1]
    finally:
        server.should_exit = True
        A.WINDOW["show"] = None


def test_instance_token_is_empty_without_a_lock_file(tmp_path):
    assert system_integration.instance_token(tmp_path) == ""


@pytest.mark.parametrize("value", ["true", "1", "yes", "on", "True"])
def test_a_forced_update_check_needs_the_token(A, monkeypatch, value):
    """It contacts GitHub, so another website mustn't be able to trigger it over and over."""
    import updater
    calls = []
    monkeypatch.setattr(updater, "_cache", {"at": 0.0, "data": None})
    monkeypatch.setattr(updater, "fetch_latest", lambda: calls.append(1) or {
        "version": "0.0.1", "name": "v0.0.1", "notes": "", "url": "", "published_at": "", "assets": {}})
    c = client(A)
    assert c.get(f"/api/update/check?force={value}").status_code == 403
    assert calls == []                                            # GitHub was never contacted
    assert c.get(f"/api/update/check?force={value}", headers=token(A)).status_code == 200
    assert calls == [1]


@pytest.mark.parametrize("query", ["", "?force=false", "?force=0", "?force=no"])
def test_a_normal_update_check_needs_no_token(A, monkeypatch, query):
    import updater
    monkeypatch.setattr(updater, "_cache", {"at": 0.0, "data": None})
    monkeypatch.setattr(updater, "fetch_latest", lambda: {
        "version": "0.0.1", "name": "v0.0.1", "notes": "", "url": "", "published_at": "", "assets": {}})
    assert client(A).get(f"/api/update/check{query}").status_code == 200


def test_an_unclear_force_value_is_treated_as_forced(A):
    """Fail closed: anything that isn't clearly "false" needs the token."""
    assert client(A).get("/api/update/check?force=anything").status_code == 403
