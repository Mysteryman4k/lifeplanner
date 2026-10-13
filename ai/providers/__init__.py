"""AI providers. Two adapters cover everything: Anthropic, and anything OpenAI-compatible (OpenAI, DeepSeek,
Ollama, custom services). The rest of the app only uses `get_provider()` and the Provider interface.

Model lists always come from the provider itself, never a list in the app, so new and retired models
don't break anything.
"""
from .base import Provider, ProviderError, Result

# Shown in Settings. Links are where the student creates a key and sets a spending limit.
PRESETS = {
    "anthropic": {
        "name": "Anthropic", "kind": "anthropic", "base_url": "https://api.anthropic.com", "needs_key": True,
        "key_url": "https://console.anthropic.com/settings/keys",
        "limit_url": "https://console.anthropic.com/settings/limits",
        "about": "Claude models. Needs an Anthropic account with API credit (18+). Light study use typically "
                 "costs a few cents a session with a small model.",
        "suggest": ("haiku",),
    },
    "openai": {
        "name": "OpenAI", "kind": "openai", "base_url": "https://api.openai.com/v1", "needs_key": True,
        "key_url": "https://platform.openai.com/api-keys",
        "limit_url": "https://platform.openai.com/settings/organization/limits",
        "about": "GPT models. Needs an OpenAI platform account with API credit (18+), separate from ChatGPT. "
                 "Small models cost a few cents a session.",
        "suggest": ("mini",),
    },
    "deepseek": {
        "name": "DeepSeek", "kind": "openai", "base_url": "https://api.deepseek.com/v1", "needs_key": True,
        "key_url": "https://platform.deepseek.com/api_keys",
        "limit_url": "https://platform.deepseek.com/top_up",
        "about": "DeepSeek models. Prepaid credit, so your balance is your limit. Usually the cheapest cloud option.",
        "suggest": ("chat",),
    },
    "ollama": {
        "name": "Ollama (this PC)", "kind": "ollama", "base_url": "http://localhost:11434/v1", "needs_key": False,
        "key_url": "https://ollama.com/download", "limit_url": "",
        "about": "Free and private: local models run on your own computer and nothing leaves it. Needs Ollama "
                 "installed and a model downloaded (usually 2 to 10 GB). Replies are slower on most laptops. "
                 "Ollama's cloud models (marked \"cloud\") run on ollama.com instead.",
        "suggest": ("qwen", "llama", "gemma"),
    },
    "custom": {
        "name": "Custom", "kind": "openai", "base_url": "", "needs_key": False,
        "key_url": "", "limit_url": "",
        "about": "Any OpenAI-compatible service, such as OpenRouter, Groq or LM Studio. Enter its base URL, "
                 "and an API key if it needs one.",
        "suggest": (),
    },
}


def get_provider(provider_id: str, *, key: str = None, base_url: str = None, transport=None) -> Provider:
    from .anthropic import AnthropicProvider
    from .ollama import OllamaProvider
    from .openai_compat import OpenAICompatProvider
    preset = PRESETS[provider_id]
    url = (base_url or preset["base_url"]).rstrip("/")
    cls = {"anthropic": AnthropicProvider, "openai": OpenAICompatProvider, "ollama": OllamaProvider}[preset["kind"]]
    return cls(provider_id, url, key=key, transport=transport)


def suggest_model(provider_id: str, models: list, avoid=()) -> str:
    """A sensible default from the provider's own list: cheap and good enough for study help.
    Never suggests a model in `avoid` (Ollama cloud models, which send data off the PC)."""
    usable = [m for m in models if m not in set(avoid)]
    for word in PRESETS.get(provider_id, {}).get("suggest", ()):
        for m in usable:
            if word in m.lower():
                return m
    return usable[0] if usable else ""


__all__ = ["PRESETS", "Provider", "ProviderError", "Result", "get_provider", "suggest_model"]
