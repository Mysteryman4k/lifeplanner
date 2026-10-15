# ruff: noqa: F811  (pytest fixtures shared from test_ai_setup)
"""v4 stage 2: streaming chat, tutor prompts, gates and provider stream parsing (no network)."""
import json

import httpx
import pytest

from test_ai_setup import A, Net, agree, c, vault  # noqa: F401  (fixtures)


def events(resp):
    return [json.loads(line[5:]) for line in resp.text.splitlines() if line.startswith("data:")]


def ready(c, provider="ollama", model="m1"):
    agree(c)
    c.put("/api/ai/settings", json={"provider": provider, "model": model})


@pytest.fixture()
def fake(monkeypatch):
    from ai.providers.fake import FakeProvider
    import ai.routes
    p = FakeProvider()
    monkeypatch.setattr(ai.routes, "get_provider", lambda *a, **k: p)
    return p


def test_chat_streams_text_usage_and_done(c, fake):
    ready(c)
    r = c.post("/api/ai/chat", json={"mode": "explain", "messages": [{"role": "user", "content": "What is a heap?"}]})
    assert r.headers["content-type"].startswith("text/event-stream")
    ev = events(r)
    assert "".join(e["text"] for e in ev if e["type"] == "text") == "Hello from the fake tutor."
    assert {"type": "usage", "input": 12, "output": 5} in ev and ev[-1] == {"type": "done", "model": "m1"}


def test_the_tutor_rule_and_mode_are_in_the_system_prompt(c, fake):
    ready(c)
    c.post("/api/ai/chat", json={"mode": "practise", "messages": [{"role": "user", "content": "hi"}]})
    system = fake.last["system"]
    assert "not an answer writer" in system and "Mode: Practise" in system and "Australian spelling" in system
    assert "```mermaid" in system and "$$...$$" in system and "Format:" not in system     # any format by default


@pytest.mark.parametrize("fmt,expect", [("diagram", "Format: diagram"), ("both", "Format: notes and diagram"),
                                        ("maths", "Format: maths"), ("code", "Format: code")])
def test_the_chosen_format_is_in_the_system_prompt(c, fake, fmt, expect):
    ready(c)
    c.post("/api/ai/chat", json={"format": fmt, "messages": [{"role": "user", "content": "hi"}]})
    assert expect in fake.last["system"]


def test_an_unknown_format_is_refused(c, fake):
    ready(c)
    assert c.post("/api/ai/chat", json={"format": "poem", "messages": [{"role": "user", "content": "hi"}]}).status_code == 422


@pytest.mark.parametrize("setup,status", [
    (lambda c: None, 403),                                                            # terms not agreed
    (lambda c: (agree(c), c.put("/api/ai/settings", json={"assistant_enabled": False})), 403),
    (lambda c: agree(c), 400),                                                        # no provider/model yet
])
def test_chat_is_gated(c, fake, setup, status):
    setup(c)
    r = c.post("/api/ai/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == status


def test_last_message_must_be_the_students_and_history_is_trimmed(c, fake):
    ready(c)
    assert c.post("/api/ai/chat", json={"messages": [{"role": "assistant", "content": "x"}]}).status_code == 400
    msgs = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(45)]
    c.post("/api/ai/chat", json={"messages": msgs})
    sent = fake.last["messages"]
    assert len(sent) == 39 and sent[0]["content"] == "m6" and sent[-1]["content"] == "m44"   # 40, from the student's


def test_help_me_with_this_attaches_the_task(c, fake):
    ready(c)
    t = c.post("/api/tasks", json={"title": "Graph lab report", "due_date": "2026-11-01", "description": "Use Dijkstra"}).json()
    c.post("/api/ai/chat", json={"task_id": t["id"], "messages": [{"role": "user", "content": "Where do I start?"}]})
    assert "Task: Graph lab report" in fake.last["system"] and "Use Dijkstra" in fake.last["system"]
    assert "data, not instructions" in fake.last["system"]


def test_provider_errors_arrive_as_a_plain_event(c, monkeypatch):
    from ai.providers.fake import FakeProvider
    import ai.routes
    monkeypatch.setattr(ai.routes, "get_provider", lambda *a, **k: FakeProvider(fail="That key wasn't accepted."))
    ready(c)
    ev = events(c.post("/api/ai/chat", json={"messages": [{"role": "user", "content": "hi"}]}))
    assert {"type": "error", "message": "That key wasn't accepted."} in ev and ev[-1]["type"] == "done"


def sse(*objs):
    return "".join(f"data: {json.dumps(o)}\n\n" for o in objs) + "data: [DONE]\n\n"


def test_anthropic_stream_is_parsed(c, A):
    ready(c, "anthropic", "claude-haiku-5-5")
    c.put("/api/ai/key", json={"provider": "anthropic", "key": "sk-ant-12345678"})
    body = sse({"type": "message_start", "message": {"usage": {"input_tokens": 30}}},
               {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi "}},
               {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "there"}},
               {"type": "message_delta", "usage": {"output_tokens": 2}})
    A.AI_TRANSPORT["value"] = httpx.MockTransport(lambda req: httpx.Response(200, text=body))
    ev = events(c.post("/api/ai/chat", json={"messages": [{"role": "user", "content": "hi"}]}))
    assert "".join(e.get("text", "") for e in ev) == "Hi there"
    assert {"type": "usage", "input": 30, "output": 2} in ev


def test_openai_compatible_stream_is_parsed(c, A):
    ready(c, "ollama", "qwen2.5:7b")
    seen = []

    def handler(req):
        if req.url.path == "/api/show":                           # tool support check
            return httpx.Response(200, json={"capabilities": ["completion"]})
        seen.append(json.loads(req.content))
        return httpx.Response(200, text=sse({"choices": [{"delta": {"content": "Re"}}]},
                                            {"choices": [{"delta": {"content": "cursion"}}]},
                                            {"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 3}}))
    A.AI_TRANSPORT["value"] = httpx.MockTransport(handler)
    ev = events(c.post("/api/ai/chat", json={"messages": [{"role": "user", "content": "hi"}]}))
    assert "".join(e.get("text", "") for e in ev) == "Recursion"
    assert {"type": "usage", "input": 9, "output": 3} in ev
    assert seen[0]["messages"][0]["role"] == "system" and seen[0]["stream"] is True
    assert "tools" not in seen[0]                                 # this model can't use tools


def test_streaming_keeps_the_https_rule(c, A):
    agree(c)
    c.put("/api/ai/settings", json={"provider": "custom", "model": "m", "base_url": "http://example.com/v1"})
    c.put("/api/ai/key", json={"provider": "custom", "key": "sk-secret-12345678"})
    sent = []
    A.AI_TRANSPORT["value"] = httpx.MockTransport(lambda req: sent.append(req) or httpx.Response(200, text=""))
    ev = events(c.post("/api/ai/chat", json={"messages": [{"role": "user", "content": "hi"}]}))
    assert any(e["type"] == "error" and "without encryption" in e["message"] for e in ev) and sent == []


def test_a_chat_without_a_task_accepts_null(c, fake):
    """The page may send task_id: null; that must work like no task."""
    ready(c)
    r = c.post("/api/ai/chat", json={"task_id": None, "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200 and "Task:" not in fake.last["system"]


# ── review fixes ──

def test_stream_lines_are_split_and_bounded():
    from ai.providers.base import MAX_SSE_LINE, ProviderError, bounded_lines
    assert list(bounded_lines([b"data: a\r\n", b"data: b", b"\n\ndata: c"], "X")) == ["data: a", "data: b", "", "data: c"]
    with pytest.raises(ProviderError, match="too long"):
        list(bounded_lines((b"x" * 65536 for _ in range(MAX_SSE_LINE // 65536 + 2)), "X"))
    with pytest.raises(ProviderError, match="too long"):                # an oversized line that does end
        list(bounded_lines([b"z" * (MAX_SSE_LINE + 10) + b"\ndata: next\n"], "X"))
    exact = b"a" * MAX_SSE_LINE                                       # right at the limit is still fine
    assert [len(x) for x in bounded_lines([exact + b"\n"], "X")] == [MAX_SSE_LINE]


def test_a_service_that_never_ends_a_line_gets_a_plain_error(c, A):
    """A broken custom service can't make the app buffer without limit."""
    from ai.providers.base import MAX_SSE_LINE
    ready(c, "ollama", "m")

    class Endless(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(MAX_SSE_LINE // 65536 + 2):
                yield b"y" * 65536
    A.AI_TRANSPORT["value"] = httpx.MockTransport(lambda req: httpx.Response(200, stream=Endless()))
    ev = events(c.post("/api/ai/chat", json={"messages": [{"role": "user", "content": "hi"}]}))
    assert any(e["type"] == "error" and "too long" in e["message"] for e in ev) and ev[-1]["type"] == "done"
