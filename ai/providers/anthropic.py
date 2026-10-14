"""Anthropic Messages API adapter (chat arrives in stage 2)."""
from .base import Provider, ProviderError

API_VERSION = "2023-06-01"


class AnthropicProvider(Provider):
    def headers(self) -> dict:
        if not self.key:
            raise ProviderError("Add your Anthropic API key first.")
        return {"x-api-key": self.key, "anthropic-version": API_VERSION}

    def list_models(self) -> list:
        data = self.get("/v1/models?limit=100", headers=self.headers())
        return [m["id"] for m in data.get("data", []) if m.get("id")]

    def stream_chat(self, model: str, system: str, messages: list, tools: list = None):
        import json
        body = {"model": model, "max_tokens": 2048, "system": system, "messages": messages, "stream": True}
        if tools:
            body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                             for t in tools]
        usage = {"type": "usage", "input": 0, "output": 0}
        blocks = {}                                   # index -> {"type", "text"} or {"type", "id", "name", "json"}
        for data in self.stream_lines("/v1/messages", self.headers(), body):
            ev = json.loads(data)
            kind = ev.get("type")
            if kind == "content_block_start":
                b = ev.get("content_block", {})
                blocks[ev.get("index", 0)] = ({"type": "tool_use", "id": b.get("id"), "name": b.get("name"), "json": ""}
                                              if b.get("type") == "tool_use" else {"type": "text", "text": ""})
            elif kind == "content_block_delta":
                d, block = ev.get("delta", {}), blocks.setdefault(ev.get("index", 0), {"type": "text", "text": ""})
                if d.get("type") == "text_delta":
                    block["text"] = block.get("text", "") + d["text"]
                    yield {"type": "text", "text": d["text"]}
                elif d.get("type") == "input_json_delta":
                    block["json"] = block.get("json", "") + d.get("partial_json", "")
            elif kind == "message_start":
                usage["input"] = ev.get("message", {}).get("usage", {}).get("input_tokens", 0)
            elif kind == "message_delta":
                usage["output"] = ev.get("usage", {}).get("output_tokens", usage["output"])
            elif kind == "error":
                raise ProviderError(f"Anthropic stopped with an error: {ev.get('error', {}).get('message', 'unknown')}")
        yield usage
        calls, content = [], []
        for _, b in sorted(blocks.items()):
            if b["type"] == "tool_use":
                try:
                    args = json.loads(b["json"] or "{}")
                except ValueError:
                    args = {}
                calls.append({"id": b["id"], "name": b["name"], "args": args})
                content.append({"type": "tool_use", "id": b["id"], "name": b["name"], "input": args})
            elif b.get("text"):
                content.append({"type": "text", "text": b["text"]})
        if calls:
            yield {"type": "tool_calls", "calls": calls, "assistant": {"role": "assistant", "content": content}}

    def tool_results(self, results: list) -> list:
        return [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": call["id"], "content": text}
                                             for call, text in results]}]
