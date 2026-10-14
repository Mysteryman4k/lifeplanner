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

    def stream_chat(self, model: str, system: str, messages: list, tools: list = None):
        """Without a script: a fixed greeting. With self.script (a list of rounds): each round is a list of
        events, and a {"type": "tool_calls", "calls": [...]} event asks to use tools."""
        if self.fail:
            raise ProviderError(self.fail)
        self.last = {"model": model, "system": system, "messages": list(messages), "tools": tools}
        self.rounds = getattr(self, "rounds", [])
        self.rounds.append(self.last)
        script = getattr(self, "script", None)
        if script is None:
            for word in ("Hello ", "from ", "the ", "fake ", "tutor."):
                yield {"type": "text", "text": word}
            yield {"type": "usage", "input": 12, "output": 5}
            return
        events = script.pop(0) if script else [{"type": "text", "text": "Done."}]
        for ev in events:
            if ev["type"] == "tool_calls":
                yield {**ev, "assistant": {"role": "assistant", "content": "", "tool_calls": ev["calls"]}}
            else:
                yield ev
        yield {"type": "usage", "input": 10, "output": 4}

    def tool_results(self, results: list) -> list:
        return [{"role": "tool", "tool_call_id": call["id"], "content": text} for call, text in results]
