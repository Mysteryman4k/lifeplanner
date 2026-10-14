"""Server routes for the AI features (/api/ai/...).

Gate: apart from reading the state, the terms and the "This PC" check, nothing works until the student
has agreed to the current terms version. Like every change, the routes that change something need the
window's session token (app.py, protect_local_server).
"""
from datetime import datetime
from typing import Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from . import keys, prompts, system, terms
from .tools import TOOLS, TaskTools, system_addendum
from .providers import PRESETS, get_provider, suggest_model

ProviderId = Literal["", "anthropic", "openai", "deepseek", "ollama", "custom"]
SETTING_KEY = "ai"
MAX_HISTORY = 20            # messages sent with each request (older ones stay on screen only)
MAX_TOOL_ROUNDS = 5         # tool calls and replies in one turn, so a confused model can't loop forever


class AISettings(BaseModel):
    assistant_enabled: bool = False
    code_enabled: bool = False
    provider: ProviderId = ""
    model: str = Field(default="", max_length=200)
    base_url: str = Field(default="", max_length=500)     # custom provider only
    terms_version: str = ""                               # the version agreed to, "" if none
    terms_agreed_at: str = ""


class AISettingsUpdate(BaseModel):
    assistant_enabled: bool = None
    code_enabled: bool = None
    provider: ProviderId = None
    model: str = Field(default=None, max_length=200)
    base_url: str = Field(default=None, max_length=500)


class Agreement(BaseModel):
    version: str
    ticks: dict


class KeyIn(BaseModel):
    provider: Literal["anthropic", "openai", "deepseek", "custom"]
    key: str = Field(min_length=8, max_length=500)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)


class ChatIn(BaseModel):
    mode: Literal["explain", "practise", "notes"] = "explain"
    format: Literal["auto", "notes", "diagram", "both", "maths", "code"] = "auto"
    messages: list[ChatMessage] = Field(min_length=1, max_length=200)
    task_id: Optional[int] = None


class ConfirmIn(BaseModel):
    action_id: int
    approve: bool


class UndoIn(BaseModel):
    action_id: int


class TestIn(BaseModel):
    provider: Literal["anthropic", "openai", "deepseek", "ollama", "custom"]
    model: str = Field(default="", max_length=200)
    base_url: str = Field(default="", max_length=500)


def register(app, get_setting, put_setting, transport_hook=lambda: None, task_context=lambda task_id: "",
             task_store=None, action_log=None):
    """Add the /api/ai routes to the app. get_setting/put_setting are app.py's settings helpers.
    transport_hook lets tests supply an httpx.MockTransport so nothing goes over the network."""

    def load() -> AISettings:
        return get_setting(SETTING_KEY, AISettings)

    def save(s: AISettings):
        put_setting(SETTING_KEY, s.model_dump_json())

    def agreed(s: AISettings) -> bool:
        return s.terms_version == terms.TERMS_VERSION

    def require_agreement() -> AISettings:
        s = load()
        if not agreed(s):
            raise HTTPException(403, "Read and agree to the terms of use first.")
        return s

    def public_state(s: AISettings) -> dict:
        ok = agreed(s)
        provider = s.provider if s.provider in PRESETS else ""
        return {
            "preview": True,
            "terms": {"current_version": terms.TERMS_VERSION, "agreed": ok,
                      "agreed_version": s.terms_version, "agreed_at": s.terms_agreed_at,
                      "needs_reagreement": bool(s.terms_version) and not ok},
            # Nothing is on unless the current terms are agreed, even if an old setting says so
            "assistant_enabled": ok and s.assistant_enabled,
            "code_enabled": ok and s.code_enabled,
            "provider": provider, "model": s.model, "base_url": s.base_url,
            "key": keys.hint(provider) if provider and (PRESETS[provider]["needs_key"] or provider == "custom") else None,
            "providers": {k: {x: v[x] for x in ("name", "needs_key", "key_url", "limit_url", "about", "base_url")}
                          for k, v in PRESETS.items()},
        }

    @app.get("/api/ai/state")
    def get_state():
        return public_state(load())

    @app.get("/api/ai/terms")
    def get_terms():
        return terms.as_dict()

    @app.post("/api/ai/terms/agree")
    def agree(a: Agreement):
        if a.version != terms.TERMS_VERSION:
            raise HTTPException(409, "These terms have been updated. Read the new version and agree again.")
        if set(terms.TICKS) - {k for k, v in a.ticks.items() if v is True}:
            raise HTTPException(400, "Tick all three boxes to agree.")
        s = load()
        s.terms_version, s.terms_agreed_at = terms.TERMS_VERSION, datetime.now().isoformat(timespec="seconds")
        s.assistant_enabled = True                       # agreeing is choosing to turn it on
        save(s)
        return public_state(s)

    @app.post("/api/ai/terms/withdraw")
    def withdraw():
        s = load()
        s.terms_version = s.terms_agreed_at = ""
        s.assistant_enabled = s.code_enabled = False
        save(s)
        return public_state(s)

    @app.put("/api/ai/settings")
    def update_settings(u: AISettingsUpdate):
        s = require_agreement()
        for k, v in u.model_dump(exclude_none=True).items():
            setattr(s, k, v.strip() if isinstance(v, str) else v)
        if s.base_url and not s.base_url.startswith(("http://", "https://")):
            raise HTTPException(400, "The base URL should start with http:// or https://")
        save(s)
        return public_state(s)

    @app.put("/api/ai/key")
    def save_key(k: KeyIn):
        require_agreement()
        keys.save(k.provider, k.key.strip())
        return public_state(load())

    @app.delete("/api/ai/key/{provider}")
    def delete_key(provider: Literal["anthropic", "openai", "deepseek", "custom"]):
        require_agreement()
        try:
            keys.delete(provider)
        except Exception:
            raise HTTPException(500, "Couldn't remove the key from Windows Credential Manager. Try again, or "
                                     "remove \"EasyUniTrack AI\" there yourself.") from None
        return public_state(load())

    @app.post("/api/ai/test")
    def test(t: TestIn):
        s = require_agreement()
        # Only the custom provider has a user-chosen address; presets always use their own, so a saved
        # Anthropic/OpenAI/DeepSeek key can never be sent somewhere else
        base = (t.base_url or s.base_url or None) if t.provider == "custom" else None
        p = get_provider(t.provider, key=keys.get(t.provider), base_url=base, transport=transport_hook())
        r = p.test_connection(t.model)
        suggested = suggest_model(t.provider, r.models, avoid=r.cloud_models) if r.ok else ""
        if r.ok and not t.model and suggested:
            r = p.test_connection(suggested)              # report tool support for the model that will be used
        return {"ok": r.ok, "message": r.message, "models": r.models, "tools": r.tools,
                "cloud_models": r.cloud_models, "suggested": suggested}

    @app.post("/api/ai/chat")
    def chat(c: ChatIn):
        """Stream a reply as server-sent events: {"type": "text"|"usage"|"error"|"done", ...}."""
        import json

        from fastapi.responses import StreamingResponse
        s = require_agreement()
        if not s.assistant_enabled:
            raise HTTPException(403, "Turn on the Study assistant in Settings first.")
        if not s.provider or not s.model:
            raise HTTPException(400, "Choose an AI provider and model in Settings first.")
        if c.messages[-1].role != "user":
            raise HTTPException(400, "The last message must be yours.")
        history = [m.model_dump() for m in c.messages[-MAX_HISTORY:]]       # keeps cost and length down
        while history and history[0]["role"] != "user":
            history.pop(0)
        system_text = prompts.system_prompt(c.mode, task_context(c.task_id) if c.task_id else "", c.format)
        base = (s.base_url or None) if s.provider == "custom" else None
        provider = get_provider(s.provider, key=keys.get(s.provider), base_url=base, transport=transport_hook())
        # Task tools when the app provides them, the mode is a conversation, and the model can use tools
        use_tools = task_store is not None and c.mode in ("explain", "practise") and provider.supports_tools(s.model) is not False
        tools = TaskTools(task_store, action_log) if use_tools else None
        if tools:
            system_text += "\n\n" + system_addendum()

        def events():
            messages, state = list(history), {"changes": 0, "ask_first": False}
            try:
                for _ in range(MAX_TOOL_ROUNDS):
                    calls = None
                    for ev in provider.stream_chat(s.model, system_text, messages, TOOLS if tools else None):
                        if ev["type"] == "tool_calls":
                            calls = ev
                        else:
                            yield f"data: {json.dumps(ev)}\n\n"
                    if not calls or not tools:
                        break
                    results, app_events = tools.run_round(calls["calls"], state)
                    for ev in app_events:
                        yield f"data: {json.dumps(ev)}\n\n"
                    messages += [calls["assistant"], *provider.tool_results(results)]
                else:
                    stopped = {"type": "error", "message": "The assistant took too many steps and was stopped."}
                    yield f"data: {json.dumps(stopped)}\n\n"
            except Exception as e:                       # ProviderError has a plain message; others don't
                from .providers import ProviderError
                msg = str(e) if isinstance(e, ProviderError) else "Something went wrong while getting the reply. Try again."
                yield f"data: {json.dumps({'type': 'error', 'message': msg})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'model': s.model})}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.post("/api/ai/confirm")
    def confirm(c: ConfirmIn):
        """The student's Keep / Delete (or Do it / Don't) on a change the assistant asked about."""
        require_agreement()
        if task_store is None:
            raise HTTPException(400, "Task actions aren't available.")
        return TaskTools(task_store, action_log).confirm(c.action_id, c.approve)

    @app.post("/api/ai/undo")
    def undo(u: UndoIn):
        """Undo a change the assistant made: the task goes back exactly as it was."""
        require_agreement()
        if task_store is None:
            raise HTTPException(400, "Task actions aren't available.")
        return TaskTools(task_store, action_log).undo(u.action_id)

    @app.get("/api/ai/system")
    def get_system():
        return system.summary(transport_hook())

    @app.delete("/api/ai/all")
    def remove_all():
        """Remove all AI data: saved keys and AI settings, including the agreement. (Chats and
        assistant-made notes join this list in later stages.)"""
        removed, failed = [], []
        for provider, preset in PRESETS.items():
            if preset["needs_key"] or provider == "custom":
                had_key = keys.get(provider) is not None
                try:
                    keys.delete(provider)
                    if had_key:
                        removed.append(preset["name"])
                except Exception:
                    failed.append(preset["name"])
        if failed:                       # AI settings stay as they were; say exactly what happened to the keys
            done = (f" The key for {', '.join(removed)} was removed, so save it again if you still need it."
                    if removed else " No keys were removed.")
            raise HTTPException(500, f"Couldn't remove the saved key for {', '.join(failed)} from Windows Credential "
                                     f"Manager.{done} Your AI settings weren't changed. Try again.")
        s = AISettings()
        save(s)
        return public_state(s)

