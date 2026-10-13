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

    def stream_chat(self, model: str, system: str, messages: list):
        import json
        body = {"model": model, "max_tokens": 2048, "system": system, "messages": messages, "stream": True}
        usage = {"type": "usage", "input": 0, "output": 0}
        for data in self.stream_lines("/v1/messages", self.headers(), body):
            ev = json.loads(data)
            kind = ev.get("type")
            if kind == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
                yield {"type": "text", "text": ev["delta"]["text"]}
            elif kind == "message_start":
                usage["input"] = ev.get("message", {}).get("usage", {}).get("input_tokens", 0)
            elif kind == "message_delta":
                usage["output"] = ev.get("usage", {}).get("output_tokens", usage["output"])
            elif kind == "error":
                raise ProviderError(f"Anthropic stopped with an error: {ev.get('error', {}).get('message', 'unknown')}")
        yield usage
