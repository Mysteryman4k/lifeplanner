"""A scripted provider for tests: no network, no cost, same interface."""
from .base import Provider, ProviderError


class FakeProvider(Provider):
    def __init__(self, models=("fake-small", "fake-large"), *, fail: str = None, tools: bool = True):
        super().__init__("fake", "fake://local")
        self.models, self.fail, self.tools = list(models), fail, tools

    def list_models(self) -> list:
        if self.fail:
            raise ProviderError(self.fail)
        return self.models

    def supports_tools(self, model: str):
        return self.tools

    def stream_chat(self, model: str, system: str, messages: list):
        if self.fail:
            raise ProviderError(self.fail)
        self.last = {"model": model, "system": system, "messages": messages}
        for word in ("Hello ", "from ", "the ", "fake ", "tutor."):
            yield {"type": "text", "text": word}
        yield {"type": "usage", "input": 12, "output": 5}
