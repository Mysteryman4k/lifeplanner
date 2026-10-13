"""Ollama on this PC. Chat goes through its OpenAI-compatible API (stage 2); the model list and tool
support come from Ollama's own API, which knows what's actually installed."""
from .base import ProviderError
from .openai_compat import OpenAICompatProvider


class OllamaProvider(OpenAICompatProvider):
    @property
    def native(self) -> str:
        """http://localhost:11434/v1 -> http://localhost:11434"""
        return self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url

    def unreachable_message(self) -> str:
        return ("Ollama isn't running on this PC. Start it from the Start menu, or install it from "
                "ollama.com/download.")

    def _native(self, method: str, path: str, json=None) -> dict:
        saved, self.base_url = self.base_url, self.native
        try:
            return self.request(method, path, json=json)
        finally:
            self.base_url = saved

    def list_models(self) -> list:
        data = self._native("GET", "/api/tags")
        items = [m for m in data.get("models", []) if m.get("name")]
        models = sorted(m["name"] for m in items)
        # "Cloud" models are listed by Ollama but run on ollama.com, so data leaves the PC
        self.cloud_models = {m["name"] for m in items
                             if m.get("remote_host") or m.get("remote_model") or m["name"].endswith(("-cloud", ":cloud"))}
        if not models:
            raise ProviderError("Ollama is running, but no models are downloaded yet. In a terminal, run "
                                "\"ollama pull qwen2.5:7b\" (about 4.7 GB), then test again.")
        return models

    def supports_tools(self, model: str):
        """Newer Ollama versions report each model's capabilities."""
        try:
            caps = self._native("POST", "/api/show", json={"model": model}).get("capabilities")
        except ProviderError:
            return None
        return None if caps is None else "tools" in caps
