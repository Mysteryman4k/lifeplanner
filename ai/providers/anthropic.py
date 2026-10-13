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
