"""Anthropic Messages API adapter (chat arrives in stage 2)."""
import time

import httpx

from .base import CUT_OFF, Provider, ProviderError

API_VERSION = "2023-06-01"
MAX_TOKENS = 8192              # thinking counts towards it, so leave room for the answer after it
THINK_BUDGET = 4096            # older models that only take a fixed thinking budget (Claude Haiku 4.5 and earlier)


class AnthropicProvider(Provider):
    # A model's capabilities (which thinking settings it takes) from the Models API, kept for 10 minutes; a failed
    # answer for 30 s, so a slow API can only hold up one refresh of the AI settings in a while
    MODELS: dict = {}
    MODEL_TTL, MODEL_FAILED_TTL = 600.0, 30.0

    def headers(self) -> dict:
        if not self.key:
            raise ProviderError("Add your Anthropic API key first.")
        return {"x-api-key": self.key, "anthropic-version": API_VERSION}

    def list_models(self) -> list:
        data = self.get("/v1/models?limit=100", headers=self.headers())
        return [m["id"] for m in data.get("data", []) if m.get("id")]

    def model_info(self, model: str) -> dict:
        key = (self.base_url, model, self._transport)
        hit = AnthropicProvider.MODELS.get(key)
        if hit and time.monotonic() < hit[0]:
            if isinstance(hit[1], ProviderError):
                raise hit[1]
            return hit[1]
        try:
            data = self.request("GET", f"/v1/models/{model}", headers=self.headers(),
                                timeout=httpx.Timeout(6.0, connect=3.0))
        except ProviderError as e:
            AnthropicProvider.MODELS[key] = (time.monotonic() + self.MODEL_FAILED_TTL, e)
            raise
        AnthropicProvider.MODELS[key] = (time.monotonic() + self.MODEL_TTL, data)
        return data

    def thinking_levels(self, model: str) -> list:
        """The thinking settings the model takes ("disabled", "between_tools", "adaptive", "enabled"), plus
        "effort" when it takes an effort level; [] if it doesn't think or the Models API can't be asked."""
        try:
            caps = self.model_info(model).get("capabilities") or {}
        except ProviderError:
            return []
        thinking = caps.get("thinking") or {}
        if not thinking.get("supported"):
            return []
        types = thinking.get("types") or {}
        levels = [t for t in ("disabled", "between_tools", "adaptive", "enabled") if (types.get(t) or {}).get("supported")]
        if ((caps.get("effort") or {}).get("low") or {}).get("supported"):
            levels.append("effort")
        return levels

    def request_options(self, model: str) -> dict:
        """Quick replies unless the student turned on Think. Claude 5 models think by default; quick turns that
        off where the model allows it, or uses its lowest setting (Sonnet 5.5: between_tools; Opus 5.5, which
        always thinks: low effort). Think lets it think: adaptive thinking, or a fixed budget on older models."""
        levels = self.thinking_levels(model)
        if not self.think:
            if "disabled" in levels:
                return {"thinking": {"type": "disabled"}}
            if "between_tools" in levels:
                return {"thinking": {"type": "between_tools"}}
            return {"output_config": {"effort": "low"}} if "effort" in levels else {}
        if "adaptive" in levels:           # the thinking itself isn't shown, so don't wait for it to be summarised
            return {"thinking": {"type": "adaptive", "display": "omitted"}}
        if "enabled" in levels:
            return {"thinking": {"type": "enabled", "budget_tokens": THINK_BUDGET}}
        return {}

    def stream_chat(self, model: str, system: str, messages: list, tools: list = None):
        import json
        body = {"model": model, "max_tokens": MAX_TOKENS, "system": system, "messages": messages, "stream": True,
                **self.request_options(model)}
        if tools:
            body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                             for t in tools]
        usage = {"type": "usage", "input": 0, "output": 0}
        stop = ""
        blocks = {}                                   # index -> a text, thinking, redacted_thinking or tool_use block
        for data in self.stream_lines("/v1/messages", self.headers(), body):
            ev = json.loads(data)
            kind = ev.get("type")
            if kind == "content_block_start":
                b = ev.get("content_block", {})
                if b.get("type") == "tool_use":
                    block = {"type": "tool_use", "id": b.get("id"), "name": b.get("name"), "json": ""}
                elif b.get("type") == "thinking":    # passed back unchanged when the reply uses a tool
                    block = {"type": "thinking", "thinking": b.get("thinking", ""), "signature": b.get("signature", "")}
                elif b.get("type") == "redacted_thinking":
                    block = {"type": "redacted_thinking", "data": b.get("data", "")}
                else:
                    block = {"type": "text", "text": ""}
                blocks[ev.get("index", 0)] = block
            elif kind == "content_block_delta":
                d, block = ev.get("delta", {}), blocks.setdefault(ev.get("index", 0), {"type": "text", "text": ""})
                if d.get("type") == "text_delta":
                    block["text"] = block.get("text", "") + d["text"]
                    yield {"type": "text", "text": d["text"]}
                elif d.get("type") == "input_json_delta":
                    block["json"] = block.get("json", "") + d.get("partial_json", "")
                elif d.get("type") == "thinking_delta":
                    block["thinking"] = block.get("thinking", "") + d.get("thinking", "")
                elif d.get("type") == "signature_delta":
                    block["signature"] = block.get("signature", "") + d.get("signature", "")
            elif kind == "message_start":
                usage["input"] = ev.get("message", {}).get("usage", {}).get("input_tokens", 0)
            elif kind == "message_delta":
                usage["output"] = ev.get("usage", {}).get("output_tokens", usage["output"])
                stop = (ev.get("delta") or {}).get("stop_reason") or stop
            elif kind == "error":
                raise ProviderError(f"Anthropic stopped with an error: {ev.get('error', {}).get('message', 'unknown')}")
        yield usage
        if stop == "max_tokens":                      # say so, rather than end mid-sentence without a word
            yield {"type": "error", "message": CUT_OFF}
        calls, content = [], []
        for _, b in sorted(blocks.items()):
            if b["type"] == "tool_use":
                try:
                    args = json.loads(b["json"] or "{}")
                except ValueError:
                    args = {}
                calls.append({"id": b["id"], "name": b["name"], "args": args})
                content.append({"type": "tool_use", "id": b["id"], "name": b["name"], "input": args})
            elif b["type"] == "thinking":
                content.append({"type": "thinking", "thinking": b["thinking"], "signature": b["signature"]})
            elif b["type"] == "redacted_thinking":
                content.append({"type": "redacted_thinking", "data": b["data"]})
            elif b.get("text"):
                content.append({"type": "text", "text": b["text"]})
        if calls:
            yield {"type": "tool_calls", "calls": calls, "assistant": {"role": "assistant", "content": content}}

    def tool_results(self, results: list) -> list:
        return [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": call["id"], "content": text}
                                             for call, text in results]}]
