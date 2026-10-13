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

