"""The interface every provider implements, plus plain-language error handling."""
from dataclasses import dataclass, field

import httpx

TIMEOUT = httpx.Timeout(20.0, connect=6.0)
CREDENTIAL_HEADERS = {"authorization", "x-api-key"}
LOOPBACK = {"localhost", "127.0.0.1", "::1", "[::1]"}


def is_loopback(url: str) -> bool:
    return httpx.URL(url).host in LOOPBACK


def use_proxy_settings(url: str) -> bool:
    """Never route requests for a service on this PC through a proxy from the environment (HTTP_PROXY and
    friends): with plain http://, a key would otherwise cross the network to the proxy. Remote https://
    providers keep proxy settings, which students on uni or work networks may need."""
    return not is_loopback(url)


def secure_for_keys(url: str) -> bool:
    """Keys may only travel over HTTPS, or plain HTTP to a service on this PC (e.g. LM Studio)."""
    u = httpx.URL(url)
    return u.scheme == "https" or (u.scheme == "http" and u.host in LOOPBACK)


class ProviderError(Exception):
    """An error with a message the student can read and act on."""


@dataclass
class Result:
    ok: bool
    message: str
    models: list = field(default_factory=list)
    tools: bool = None              # True/False when known, None when not checked
    cloud_models: list = field(default_factory=list)   # Ollama models that actually run on ollama.com


class Provider:
    def __init__(self, provider_id: str, base_url: str, *, key: str = None, transport=None):
        self.id = provider_id
        self.base_url = base_url
        self.key = key
        self._transport = transport          # tests pass an httpx.MockTransport
        self.cloud_models = set()            # set by providers whose "local" list can include cloud models

    # ── to implement ──
    def list_models(self) -> list:
        raise NotImplementedError

    def supports_tools(self, model: str):
        """True/False if the provider can tell, None if unknown. Cloud providers support tools."""
        return True

    # ── shared ──
    def client(self) -> httpx.Client:
        return httpx.Client(timeout=TIMEOUT, transport=self._transport, follow_redirects=False,
                            trust_env=use_proxy_settings(self.base_url or "https://x"))

    def test_connection(self, model: str = "") -> Result:
        """A free check: listing models needs a valid key but uses no tokens."""
        try:
            models = self.list_models()
        except ProviderError as e:
            return Result(False, str(e))
        if not models:
            return Result(True, "Connected, but no models are available yet.", [])
        tools = self.supports_tools(model) if model else None
        msg = "Connected."
        if tools is True:
            msg += " Tools supported."
        elif tools is False:
            msg += " This model can't use tools, so task and code actions will be off."
        if model in self.cloud_models:
            msg += " Note: this is an Ollama cloud model, so your messages go to ollama.com, not just this PC."
        return Result(True, msg, models, tools, sorted(self.cloud_models))

    def stream_chat(self, model: str, system: str, messages: list):
        """Yield {"type": "text", "text": ...} chunks, then {"type": "usage", "input": n, "output": n}.
        messages: [{"role": "user"|"assistant", "content": str}]"""
        raise NotImplementedError

    def stream_lines(self, path: str, headers: dict, json: dict):
        """POST and yield each server-sent-event data line, with the same safety checks and plain
        errors as request()."""
        name = self.display_name()
        if not self.base_url:
            raise ProviderError("Enter the service's base URL first.")
        if headers and any(h.lower() in CREDENTIAL_HEADERS for h in headers) and not secure_for_keys(self.base_url):
            raise ProviderError("Your API key would be sent without encryption. Use an https:// address "
                                "(plain http:// is only allowed for services running on this PC).")
        try:
            with self.client() as c, c.stream("POST", self.base_url + path, headers=headers, json=json,
                                               timeout=httpx.Timeout(120.0, connect=6.0)) as r:
                if r.status_code >= 400:
                    r.read()
                    self.raise_for_status(r.status_code, name)
                for line in r.iter_lines():
                    if line.startswith("data:"):
                        data = line[5:].strip()
                        if data and data != "[DONE]":
                            yield data
        except httpx.ConnectError:
            raise ProviderError(self.unreachable_message()) from None
        except httpx.TimeoutException:
            raise ProviderError(f"{name} took too long to answer. Try again in a moment.") from None
        except httpx.HTTPError as e:
            raise ProviderError(f"The connection to {name} dropped ({e.__class__.__name__}). Try again.") from None

    def raise_for_status(self, status: int, name: str):
        if status in (401, 403):
            raise ProviderError("That key wasn't accepted. Check it was copied in full, and that it's still active.")
        if status == 404:
            raise ProviderError(f"{name} doesn't recognise that address or model. Check the base URL and model.")
        if status == 429:
            raise ProviderError(f"{name} says you've hit a rate or spending limit. Wait a little, or check your "
                                "account's credit and limits.")
        if status >= 400:
            raise ProviderError(f"{name} returned an error ({status}). Try again later.")

    def get(self, path: str, headers: dict = None) -> dict:
        return self.request("GET", path, headers=headers)

    def request(self, method: str, path: str, headers: dict = None, json=None) -> dict:
        name = self.display_name()
        if not self.base_url:
            raise ProviderError("Enter the service's base URL first.")
        if headers and any(h.lower() in CREDENTIAL_HEADERS for h in headers) and not secure_for_keys(self.base_url):
            raise ProviderError("Your API key would be sent without encryption. Use an https:// address "
                                "(plain http:// is only allowed for services running on this PC).")
        try:
            with self.client() as c:
                r = c.request(method, self.base_url + path, headers=headers or {}, json=json)
        except httpx.ConnectError:
            raise ProviderError(self.unreachable_message()) from None
        except httpx.TimeoutException:
            raise ProviderError(f"{name} took too long to answer. Try again in a moment.") from None
        except httpx.HTTPError as e:
            raise ProviderError(f"Couldn't reach {name}: {e.__class__.__name__}.") from None
        if r.status_code >= 400:
            self.raise_for_status(r.status_code, name)
        try:
            return r.json()
        except ValueError:
            raise ProviderError(f"{name} sent a reply EasyUniTrack couldn't read. Check the base URL.") from None

    def display_name(self) -> str:
        from . import PRESETS
        return PRESETS.get(self.id, {}).get("name", self.id)

    def unreachable_message(self) -> str:
        return f"Couldn't reach {self.display_name()}. Check your internet connection."
