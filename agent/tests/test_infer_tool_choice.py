"""Tests that infer(use_tools=...) sets tool_choice correctly.

Offline: the OpenAI client is replaced by a fake that records the kwargs of
chat.completions.create and returns a minimal response. Verifies that the
reasoning-only "think" step suppresses tool calls via tool_choice="none" while
the action step allows them via tool_choice="auto".

Run standalone with the stdlib:

    PYTHONPATH=src python -m tests.test_infer_tool_choice
"""

import asyncio

from a11y_gent.adaptor.openai_llm_client import OpenaiLlmClient
from a11y_gent.model.message import MessageOrigin


class _FakeMessage:
    def __init__(self):
        self.content = "some reasoning"
        self.tool_calls = None


class _FakeChoice:
    def __init__(self):
        self.message = _FakeMessage()


class _FakeResponse:
    def __init__(self):
        self.choices = [_FakeChoice()]


class _FakeCompletions:
    def __init__(self):
        self.last_kwargs = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeResponse()


class _FakeChat:
    def __init__(self):
        self.completions = _FakeCompletions()


class _FakeClient:
    def __init__(self):
        self.chat = _FakeChat()


def _client_with_fake():
    client = OpenaiLlmClient.__new__(OpenaiLlmClient)
    client._client = _FakeClient()
    client._tools = []
    return client


_HISTORY = [{"origin": MessageOrigin.USER, "name": "user", "content": "hi"}]


def test_use_tools_false_sends_tool_choice_none():
    client = _client_with_fake()

    async def _run():
        await client.infer(_HISTORY, "m", use_tools=False)

    asyncio.run(_run())
    assert client._client.chat.completions.last_kwargs["tool_choice"] == "none"


def test_use_tools_true_sends_tool_choice_auto():
    client = _client_with_fake()

    async def _run():
        await client.infer(_HISTORY, "m", use_tools=True)

    asyncio.run(_run())
    assert client._client.chat.completions.last_kwargs["tool_choice"] == "auto"


def test_default_uses_tools():
    client = _client_with_fake()

    async def _run():
        await client.infer(_HISTORY, "m")

    asyncio.run(_run())
    assert client._client.chat.completions.last_kwargs["tool_choice"] == "auto"


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()
