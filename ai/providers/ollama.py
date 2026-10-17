"""Ollama on this PC. Chat goes through its OpenAI-compatible API (stage 2); the model list and tool
support come from Ollama's own API, which knows what's actually installed."""
import httpx

from .base import ProviderError
from .openai_compat import OpenAICompatProvider


class OllamaProvider(OpenAICompatProvider):
    # Nothing arrives while a local model reads a long question (an attached file can take several minutes on a
    # PC without a graphics card), so wait longer than for a cloud service
    read_timeout = 900.0

    @property
    def native(self) -> str:
        """http://localhost:11434/v1 -> http://localhost:11434"""
        return self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url

    def unreachable_message(self) -> str:
        return ("Ollama isn't running on this PC. Start it from the Start menu, or install it from "
                "ollama.com/download.")

    # Thinking models (gemma4, qwen3.5, gpt-oss...) think before every reply by default, which on a PC without a
    # graphics card means 20 to 60 seconds before the first word. Replies are quick unless the student turns on
    # Think in the chat: then the model's own default applies
    def show(self, model: str) -> dict:
        """Ollama's details for the model (capabilities, thinking levels), asked once per provider object."""
        shown = self.__dict__.setdefault("_shown", {})
        if model not in shown:
            shown[model] = self._native("POST", "/api/show", json={"model": model})
        return shown[model]

    def thinking_levels(self, model: str) -> list:
        """How the model can think: [False, True] (off or on) or ["low", "medium", "high"]; [] if it doesn't,
        or this Ollama doesn't say."""
        try:
            thinking = self.show(model).get("thinking")
        except ProviderError:
            return []
        values = thinking.get("values") if isinstance(thinking, dict) else None
        return list(values) if isinstance(values, list) else []

    def request_options(self, model: str) -> dict:
        """A quick reply: thinking off, or the least of it when it can't be turned off (gpt-oss: low)."""
        if self.think:
            return {}
        levels = self.thinking_levels(model)
        if any(v is False for v in levels):
            return {"reasoning_effort": "none"}
        named = [v for v in levels if isinstance(v, str)]
        least = next((v for v in ("minimal", "low") if v in named), named[0] if named else None)
        return {"reasoning_effort": least} if least else {}

    def stream_chat(self, model: str, system: str, messages: list, tools: list = None):
        self.chat_model = model                   # named in the message if Ollama doesn't have it
        yield from super().stream_chat(model, system, messages, tools)

    def raise_for_status(self, status: int, name: str, body: str = ""):
        model = getattr(self, "chat_model", "")
        # A model that isn't downloaded: 404 with {"error": {"message": "model 'x' not found"}}. A wrong address is
        # a 404 too ("404 page not found"), and keeps the message about checking the address
        if status == 404 and model and "not found" in body and "model" in body.lower():
            raise ProviderError(f"Ollama doesn't have {model} on this PC. Choose a model you have in Settings, or "
                                f"download it in a terminal with: ollama pull {model}")
        super().raise_for_status(status, name, body)

    def _native(self, method: str, path: str, json=None, timeout=None) -> dict:
        saved, self.base_url = self.base_url, self.native
        try:
            return self.request(method, path, json=json, timeout=timeout)
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
            caps = self.show(model).get("capabilities")
        except ProviderError:
            return None
        return None if caps is None else "tools" in caps

    def context_length(self, model: str, load: bool = False):
        """How many tokens Ollama reads at once for this model: Ollama's own setting (Settings > Context length),
        often far less than the model allows, and anything past it is silently left out. Known while the model
        is loaded; with load=True it's loaded first (as the next question would). None if it can't be told."""
        def loaded():
            for m in self._native("GET", "/api/ps").get("models") or []:
                if model in (m.get("name"), m.get("model")):
                    return m.get("context_length")
            return None
        try:
            n = loaded()
            if n is None and load:
                self._native("POST", "/api/generate", json={"model": model}, timeout=httpx.Timeout(180.0, connect=6.0))
                n = loaded()
        except ProviderError:
            return None
        return n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else None
