"""v4 stage 1: terms gate, settings, keys, providers and the "This PC" check.

Nothing here touches the network (httpx.MockTransport) or the real Windows Credential Manager
(an in-memory keyring)."""
import importlib
import json
import sys
from pathlib import Path

import httpx
import keyring
import keyring.backend
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class MemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.store = {}

    def set_password(self, service, user, password):
        self.store[(service, user)] = password

    def get_password(self, service, user):
        return self.store.get((service, user))

    def delete_password(self, service, user):
        if (service, user) not in self.store:              # like the real vault
            from keyring.errors import PasswordDeleteError
            raise PasswordDeleteError("not found")
        del self.store[(service, user)]


@pytest.fixture()
def vault():
    old = keyring.get_keyring()
    mem = MemoryKeyring()
    keyring.set_keyring(mem)
    yield mem
    keyring.set_keyring(old)


class Net:
    """Fake internet for providers: map 'METHOD host/path' prefixes to (status, json)."""
    def __init__(self):
        self.routes, self.seen = {}, []

    def __call__(self, request: httpx.Request):
        self.seen.append(request)
        url = f"{request.method} {request.url.host}{request.url.path}"
        for prefix, (status, body) in self.routes.items():
            if url.startswith(prefix):
                return httpx.Response(status, json=body)
        raise httpx.ConnectError("unreachable", request=request)


@pytest.fixture()
def A(tmp_path, monkeypatch, vault):
    monkeypatch.setenv("TRACKADEMIC_DATA_DIR", str(tmp_path))
    import app
    importlib.reload(app)
    net = Net()
    app.AI_TRANSPORT["value"] = httpx.MockTransport(net)
    app.net = net
    yield app
    app.AI_TRANSPORT["value"] = None


@pytest.fixture()
def c(A):
    return TestClient(A.app)


def agree(c):
    terms = c.get("/api/ai/terms").json()
    return c.post("/api/ai/terms/agree", json={"version": terms["version"],
                                               "ticks": {k: True for k in terms["ticks"]}})


# ── off by default, and the terms gate ──

def test_off_and_not_agreed_by_default(c):
    s = c.get("/api/ai/state").json()
    assert s["assistant_enabled"] is False and s["code_enabled"] is False
    assert s["terms"]["agreed"] is False and s["provider"] == "" and s["preview"] is True


def test_terms_are_complete(c):
    t = c.get("/api/ai/terms").json()
    assert t["version"] and len(t["about"]) >= 5 and len(t["terms"]) >= 10
    assert set(t["ticks"]) == {"beta", "rules", "agree"}
    text = json.dumps(t).lower()
    for must in ("beta", "can be wrong", "university", "to the extent permitted by law",
                 "australian consumer law", "only run code you trust", "credential manager"):
        assert must in text, must


@pytest.mark.parametrize("missing", ["beta", "rules", "agree"])
def test_all_three_ticks_are_required(c, missing):
    terms = c.get("/api/ai/terms").json()
    ticks = {k: k != missing for k in terms["ticks"]}
    r = c.post("/api/ai/terms/agree", json={"version": terms["version"], "ticks": ticks})
    assert r.status_code == 400
    assert c.get("/api/ai/state").json()["terms"]["agreed"] is False


def test_ticks_must_be_real_true_values(c):
    terms = c.get("/api/ai/terms").json()
    r = c.post("/api/ai/terms/agree", json={"version": terms["version"], "ticks": {k: "yes" for k in terms["ticks"]}})
    assert r.status_code == 400


def test_an_old_terms_version_is_refused(c):
    r = c.post("/api/ai/terms/agree", json={"version": "0.9", "ticks": {"beta": True, "rules": True, "agree": True}})
    assert r.status_code == 409


def test_agreeing_turns_the_assistant_on_but_not_the_code_workspace(c):
    s = agree(c).json()
    assert s["terms"]["agreed"] and s["terms"]["agreed_at"]
    assert s["assistant_enabled"] is True and s["code_enabled"] is False


@pytest.mark.parametrize("call", [
    ("put", "/api/ai/settings", {"assistant_enabled": True}),
    ("put", "/api/ai/settings", {"provider": "ollama"}),
    ("put", "/api/ai/key", {"provider": "openai", "key": "sk-123456789"}),
    ("delete", "/api/ai/key/openai", None),
    ("post", "/api/ai/test", {"provider": "ollama"}),
])
def test_nothing_works_before_agreeing(c, call):
    method, path, body = call
    r = c.request(method.upper(), path, json=body)
    assert r.status_code == 403
    assert "terms" in r.json()["detail"]


def test_withdrawing_turns_everything_off(c):
    agree(c)
    c.put("/api/ai/settings", json={"code_enabled": True})
    s = c.post("/api/ai/terms/withdraw").json()
    assert s["terms"]["agreed"] is False and not s["assistant_enabled"] and not s["code_enabled"]
    assert c.put("/api/ai/settings", json={"assistant_enabled": True}).status_code == 403


def test_new_terms_version_asks_again_and_switches_off(c, monkeypatch):
    agree(c)
    import ai.terms
    monkeypatch.setattr(ai.terms, "TERMS_VERSION", "2.0")
    s = c.get("/api/ai/state").json()
    assert s["terms"]["agreed"] is False and s["terms"]["needs_reagreement"] is True
    assert s["assistant_enabled"] is False                 # off until the new version is agreed
    assert c.post("/api/ai/test", json={"provider": "ollama"}).status_code == 403
    assert agree(c).json()["terms"]["agreed"] is True


def test_the_agreement_and_ai_settings_are_not_in_backups(c):
    agree(c)
    backup = json.dumps(c.get("/api/export").json())
    assert "terms_version" not in backup and "assistant_enabled" not in backup


# ── settings ──

def test_settings_save_and_validate(c):
    agree(c)
    s = c.put("/api/ai/settings", json={"provider": "custom", "base_url": " https://openrouter.ai/api/v1 ",
                                        "model": "x", "code_enabled": True}).json()
    assert s["provider"] == "custom" and s["base_url"] == "https://openrouter.ai/api/v1" and s["code_enabled"]
    assert c.put("/api/ai/settings", json={"base_url": "ftp://nope"}).status_code == 400
    assert c.put("/api/ai/settings", json={"provider": "skynet"}).status_code == 422


# ── keys ──

def test_keys_go_to_the_vault_and_never_come_back(c, A, vault):
    agree(c)
    c.put("/api/ai/settings", json={"provider": "openai"})
    s = c.put("/api/ai/key", json={"provider": "openai", "key": " sk-test-abcdefgh1234 "}).json()
    assert vault.store[("EasyUniTrack AI", "openai")] == "sk-test-abcdefgh1234"
    assert s["key"] == "…1234"
    everything = json.dumps([c.get("/api/ai/state").json(), c.get("/api/export").json()])
    assert "sk-test-abcdefgh1234" not in everything
    with A.db() as conn:
        assert "abcdefgh1234" not in json.dumps([dict(r) for r in conn.execute("SELECT * FROM settings")])
    assert c.delete("/api/ai/key/openai").json()["key"] is None
    assert ("EasyUniTrack AI", "openai") not in vault.store


def test_remove_all_ai_data(c, vault):
    agree(c)
    c.put("/api/ai/settings", json={"provider": "anthropic", "model": "m"})
    c.put("/api/ai/key", json={"provider": "anthropic", "key": "sk-ant-12345678"})
    c.put("/api/ai/key", json={"provider": "deepseek", "key": "sk-ds-12345678"})
    s = c.delete("/api/ai/all").json()
    assert vault.store == {}
    assert s["terms"]["agreed"] is False and s["provider"] == "" and s["model"] == ""


# ── providers ──

def test_anthropic_connection(c, A):
    agree(c)
    c.put("/api/ai/key", json={"provider": "anthropic", "key": "sk-ant-12345678"})
    A.net.routes["GET api.anthropic.com/v1/models"] = (200, {"data": [{"id": "claude-opus-5-5"}, {"id": "claude-haiku-5-5"}]})
    r = c.post("/api/ai/test", json={"provider": "anthropic", "model": "claude-haiku-5-5"}).json()
    assert r["ok"] and r["tools"] is True and "Connected" in r["message"]
    assert r["suggested"] == "claude-haiku-5-5"
    sent = A.net.seen[-1]
    assert sent.headers["x-api-key"] == "sk-ant-12345678" and sent.headers["anthropic-version"]


@pytest.mark.parametrize("status,words", [(401, "wasn't accepted"), (429, "limit"), (500, "error (500)")])
def test_provider_errors_are_plain(c, A, status, words):
    agree(c)
    c.put("/api/ai/key", json={"provider": "openai", "key": "sk-12345678"})
    A.net.routes["GET api.openai.com/v1/models"] = (status, {"error": "x"})
    r = c.post("/api/ai/test", json={"provider": "openai"}).json()
    assert r["ok"] is False and words in r["message"]


def test_missing_key_and_no_internet(c, A):
    agree(c)
    assert "Add your OpenAI API key" in c.post("/api/ai/test", json={"provider": "openai"}).json()["message"]
    c.put("/api/ai/key", json={"provider": "deepseek", "key": "sk-12345678"})
    r = c.post("/api/ai/test", json={"provider": "deepseek"}).json()          # no route: unreachable
    assert r["ok"] is False and "internet connection" in r["message"]


def test_openai_compatible_lists_models_with_bearer_key(c, A):
    agree(c)
    c.put("/api/ai/key", json={"provider": "deepseek", "key": "sk-ds-12345678"})
    A.net.routes["GET api.deepseek.com/v1/models"] = (200, {"data": [{"id": "deepseek-reasoner"}, {"id": "deepseek-chat"}]})
    r = c.post("/api/ai/test", json={"provider": "deepseek"}).json()
    assert r["ok"] and r["models"] == ["deepseek-chat", "deepseek-reasoner"] and r["suggested"] == "deepseek-chat"
    assert A.net.seen[-1].headers["authorization"] == "Bearer sk-ds-12345678"


def test_ollama_models_and_tool_support(c, A):
    agree(c)
    A.net.routes["GET localhost/api/tags"] = (200, {"models": [{"name": "qwen2.5:7b"}, {"name": "gemma4:latest"}]})
    A.net.routes["POST localhost/api/show"] = (200, {"capabilities": ["completion", "tools"]})
    r = c.post("/api/ai/test", json={"provider": "ollama", "model": "qwen2.5:7b"}).json()
    assert r["ok"] and r["tools"] is True and r["suggested"] == "qwen2.5:7b"
    A.net.routes["POST localhost/api/show"] = (200, {"capabilities": ["completion"]})
    r = c.post("/api/ai/test", json={"provider": "ollama", "model": "gemma4:latest"}).json()
    assert r["tools"] is False and "can't use tools" in r["message"]


def test_ollama_not_running_or_no_models(c, A):
    agree(c)
    r = c.post("/api/ai/test", json={"provider": "ollama"}).json()
    assert r["ok"] is False and "Ollama isn't running" in r["message"]
    A.net.routes["GET localhost/api/tags"] = (200, {"models": []})
    r = c.post("/api/ai/test", json={"provider": "ollama"}).json()
    assert r["ok"] is False and "ollama pull" in r["message"]


def test_custom_provider_needs_a_base_url(c, A):
    agree(c)
    r = c.post("/api/ai/test", json={"provider": "custom"}).json()
    assert r["ok"] is False and "base URL" in r["message"]
    A.net.routes["GET openrouter.ai/api/v1/models"] = (200, {"data": [{"id": "meta/llama"}]})
    r = c.post("/api/ai/test", json={"provider": "custom", "base_url": "https://openrouter.ai/api/v1"}).json()
    assert r["ok"] and r["models"] == ["meta/llama"]


def test_this_pc_check(c, A):
    A.net.routes["GET localhost/api/version"] = (200, {"version": "0.40.3"})
    s = c.get("/api/ai/system").json()
    assert s["ram_gb"] > 0 and "RAM" in s["advice"]
    assert s["ollama"] == {"running": True, "version": "0.40.3"}


@pytest.mark.parametrize("ram,words", [(4, "very slow"), (8, "small local models"),
                                       (32, "medium local models"), (0, "Couldn't check")])
def test_local_model_advice(ram, words):
    from ai.system import local_model_advice
    assert words in local_model_advice(ram)


def test_fake_provider_matches_the_interface():
    from ai.providers.fake import FakeProvider
    assert FakeProvider().test_connection("fake-small").ok
    r = FakeProvider(fail="nope").test_connection()
    assert r.ok is False and r.message == "nope"


def test_tests_never_reach_the_real_vault():
    """The app's key code leaves an in-memory vault alone (so tests can't touch Credential Manager)."""
    import ai.keys
    mem = MemoryKeyring()
    old = keyring.get_keyring()
    keyring.set_keyring(mem)
    try:
        ai.keys.save("openai", "sk-memory-only")
        assert mem.store[("EasyUniTrack AI", "openai")] == "sk-memory-only"
    finally:
        keyring.set_keyring(old)


def test_restoring_a_backup_keeps_this_pcs_ai_settings(c):
    """A backup never carries the agreement, and restoring one doesn't switch AI off or on."""
    backup = c.get("/api/export").json()                   # made before agreeing
    agree(c)
    c.put("/api/ai/settings", json={"provider": "ollama"})
    assert c.post("/api/import", json=backup).status_code == 200
    s = c.get("/api/ai/state").json()
    assert s["terms"]["agreed"] is True and s["provider"] == "ollama"


def test_ollama_cloud_models_are_never_suggested_and_are_flagged(c, A):
    """Ollama lists "cloud" models that run on ollama.com: data leaves the PC, so the app must say so."""
    agree(c)
    A.net.routes["GET localhost/api/tags"] = (200, {"models": [
        {"name": "gemma4:31b-cloud", "remote_model": "gemma4:31b", "remote_host": "https://ollama.com:443", "size": 342},
        {"name": "gemma4:latest", "size": 9608350718}]})
    A.net.routes["POST localhost/api/show"] = (200, {"capabilities": ["completion", "tools"]})
    r = c.post("/api/ai/test", json={"provider": "ollama"}).json()
    assert r["suggested"] == "gemma4:latest"                     # the local one, even though "cloud" sorts first
    assert r["cloud_models"] == ["gemma4:31b-cloud"]
    assert "Tools supported" in r["message"]                     # reported for the suggested model straight away
    r = c.post("/api/ai/test", json={"provider": "ollama", "model": "gemma4:31b-cloud"}).json()
    assert "ollama.com" in r["message"]



# ── review fixes ──

def test_a_key_is_never_sent_over_plain_http(c, A):
    """Keys only travel over HTTPS, or plain HTTP to a service on this PC."""
    agree(c)
    c.put("/api/ai/key", json={"provider": "custom", "key": "sk-secret-12345678"})
    r = c.post("/api/ai/test", json={"provider": "custom", "base_url": "http://example.com/v1"}).json()
    assert r["ok"] is False and "without encryption" in r["message"]
    assert A.net.seen == []                                   # refused before anything was sent
    A.net.routes["GET localhost/v1/models"] = (200, {"data": [{"id": "local-model"}]})
    r = c.post("/api/ai/test", json={"provider": "custom", "base_url": "http://localhost:1234/v1"}).json()
    assert r["ok"] and A.net.seen[-1].headers["authorization"] == "Bearer sk-secret-12345678"


@pytest.mark.parametrize("url,ok", [("https://api.example.com/v1", True), ("http://127.0.0.1:1234/v1", True),
                                    ("http://localhost/v1", True), ("http://[::1]:8080/v1", True),
                                    ("http://example.com/v1", False), ("http://192.168.1.5:1234/v1", False),
                                    ("http://localhost.example.com/v1", False)])
def test_where_keys_may_go(url, ok):
    from ai.providers.base import secure_for_keys
    assert secure_for_keys(url) is ok


def test_preset_providers_ignore_an_address_override(c, A):
    """A saved OpenAI key must only ever go to OpenAI, whatever the request asks for."""
    agree(c)
    c.put("/api/ai/key", json={"provider": "openai", "key": "sk-openai-12345678"})
    A.net.routes["GET api.openai.com/v1/models"] = (200, {"data": [{"id": "gpt-x-mini"}]})
    r = c.post("/api/ai/test", json={"provider": "openai", "base_url": "https://attacker.example/v1"}).json()
    assert r["ok"]
    assert {req.url.host for req in A.net.seen} == {"api.openai.com"}


def test_removing_data_reports_a_key_that_couldnt_be_deleted(c, monkeypatch):
    agree(c)
    c.put("/api/ai/settings", json={"provider": "openai"})
    c.put("/api/ai/key", json={"provider": "openai", "key": "sk-openai-12345678"})
    import ai.keys

    def broken(provider):
        raise RuntimeError("vault locked")
    monkeypatch.setattr(ai.keys, "delete", broken)
    r = c.delete("/api/ai/all")
    assert r.status_code == 500 and "No keys were removed" in r.json()["detail"]
    assert c.get("/api/ai/state").json()["terms"]["agreed"] is True       # settings left as they were
    r = c.delete("/api/ai/key/openai")
    assert r.status_code == 500 and "Credential Manager" in r.json()["detail"]


def test_deleting_a_key_that_isnt_saved_is_fine(c):
    agree(c)
    assert c.delete("/api/ai/key/deepseek").status_code == 200
    assert c.delete("/api/ai/all").status_code == 200


def test_partial_key_removal_is_reported_exactly(c, vault, monkeypatch):
    """Two saved keys, the second fails: say which one was removed so it can be saved again."""
    agree(c)
    c.put("/api/ai/key", json={"provider": "anthropic", "key": "sk-ant-12345678"})
    c.put("/api/ai/key", json={"provider": "openai", "key": "sk-openai-12345678"})
    import ai.keys
    real = ai.keys.delete

    def fail_on_openai(provider):
        if provider == "openai":
            raise RuntimeError("vault locked")
        real(provider)
    monkeypatch.setattr(ai.keys, "delete", fail_on_openai)
    detail = c.delete("/api/ai/all").json()["detail"]
    assert "for OpenAI" in detail and "The key for Anthropic was removed" in detail and "weren't changed" in detail
    assert ("EasyUniTrack AI", "anthropic") not in vault.store and ("EasyUniTrack AI", "openai") in vault.store
    assert c.get("/api/ai/state").json()["terms"]["agreed"] is True


@pytest.mark.parametrize("url,proxy", [("http://localhost:1234/v1", False), ("http://127.0.0.1:11434", False),
                                       ("http://[::1]:8080/v1", False), ("https://api.openai.com/v1", True)])
def test_services_on_this_pc_never_go_through_a_proxy(url, proxy, monkeypatch):
    """With HTTP_PROXY set, a local http:// request (which may carry a key) must not be sent to the proxy."""
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:3128")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    monkeypatch.delenv("NO_PROXY", raising=False)
    from ai.providers import get_provider
    provider = get_provider("custom", key="sk-12345678", base_url=url)
    with provider.client() as client:
        assert client._trust_env is proxy
        routed = client._transport_for_url(__import__("httpx").URL(url + "/models"))
        assert (routed is not client._transport) is proxy             # a proxy transport only for remote https
