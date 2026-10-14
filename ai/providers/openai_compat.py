"""Adapter for anything OpenAI-compatible: OpenAI, DeepSeek, custom services (chat arrives in stage 2)."""
from .base import Provider, ProviderError


class OpenAICompatProvider(Provider):
    def headers(self) -> dict:
        from . import PRESETS
        if self.key:
            return {"Authorization": f"Bearer {self.key}"}
        if PRESETS.get(self.id, {}).get("needs_key"):
            raise ProviderError(f"Add your {self.display_name()} API key first.")
        return {}

    def list_models(self) -> list:
        data = self.get("/models", headers=self.headers())
        items = data.get("data", []) if isinstance(data, dict) else []
        return sorted(m["id"] for m in items if isinstance(m, dict) and m.get("id"))

    def stream_chat(self, model: str, system: str, messages: list, tools: list = None):
        import json
        body = {"model": model, "stream": True, "stream_options": {"include_usage": True},
                "messages": [{"role": "system", "content": system}, *messages]}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                                "parameters": t["parameters"]}} for t in tools]
        usage = {"type": "usage", "input": 0, "output": 0}
        text, calls = "", {}                          # index -> {"id", "name", "arguments"}
        for data in self.stream_lines("/chat/completions", self.headers(), body):
            ev = json.loads(data)
            for choice in ev.get("choices") or []:
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    text += delta["content"]
                    yield {"type": "text", "text": delta["content"]}
                for tc in delta.get("tool_calls") or []:
                    c = calls.setdefault(tc.get("index", len(calls)), {"id": "", "name": "", "arguments": ""})
                    c["id"] = tc.get("id") or c["id"]
                    fn = tc.get("function") or {}
                    c["name"] = fn.get("name") or c["name"]
                    args = fn.get("arguments")
                    # Some servers (e.g. Ollama) send the arguments as one object rather than string pieces
                    c["arguments"] += json.dumps(args) if isinstance(args, dict) else (args or "")
            if ev.get("usage"):
                usage["input"] = ev["usage"].get("prompt_tokens", 0)
                usage["output"] = ev["usage"].get("completion_tokens", 0)
        yield usage
        if calls:
            out, native = [], []
            for n, c in sorted(calls.items()):
                cid = c["id"] or f"call_{n}"
                try:
                    args = json.loads(c["arguments"] or "{}")
                except ValueError:
                    args = {}
                out.append({"id": cid, "name": c["name"], "args": args})
                native.append({"id": cid, "type": "function",
                               "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}})
            yield {"type": "tool_calls", "calls": out,
                   "assistant": {"role": "assistant", "content": text or None, "tool_calls": native}}

    def tool_results(self, results: list) -> list:
        return [{"role": "tool", "tool_call_id": call["id"], "content": text} for call, text in results]
