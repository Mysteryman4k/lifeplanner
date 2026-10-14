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


    def stream_chat(self, model: str, system: str, messages: list):
        import json
        body = {"model": model, "stream": True, "stream_options": {"include_usage": True},
                "messages": [{"role": "system", "content": system}, *messages]}
        usage = {"type": "usage", "input": 0, "output": 0}
        for data in self.stream_lines("/chat/completions", self.headers(), body):
            ev = json.loads(data)
            for choice in ev.get("choices") or []:
                text = (choice.get("delta") or {}).get("content")
                if text:
                    yield {"type": "text", "text": text}
            if ev.get("usage"):
                usage["input"] = ev["usage"].get("prompt_tokens", 0)
                usage["output"] = ev["usage"].get("completion_tokens", 0)
        yield usage
