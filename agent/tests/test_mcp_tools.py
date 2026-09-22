"""Tests for the MCP -> agent Tool integration (a11y_gent.adaptor.mcp_tools).

These are pure, offline tests: no NVDA and no network are required. They verify
that a server-provided MCP ``inputSchema`` is faithfully turned into an
``inspect.Signature`` and, via OpenaiLlmClient._convert_tool, into the correct
OpenAI function schema -- including the array ``items`` handling -- and that the
argument-coercion and result-flattening helpers behave.

Run standalone with the stdlib (no pytest needed):

    python -m tests.test_mcp_tools

Each ``test_*`` function is also discoverable by pytest if it is added later.
"""

import asyncio
import json

from a11y_gent.adaptor.mcp_tools import (
    _coerce_arguments,
    _flatten_result,
    _make_tool_function,
    _signature_from_schema,
    register_mcp_tools,
)
from a11y_gent.adaptor.openai_llm_client import OpenaiLlmClient
from a11y_gent.model.tool import Tool


# Real-shaped schemas taken from the NVDA MCP Bridge tool definitions.
SEND_KEYS_SCHEMA = {
    "type": "object",
    "properties": {
        "gestures": {"type": "array", "items": {"type": "string"}},
        "delay_ms": {"type": "integer", "default": 0},
    },
    "required": ["gestures"],
    "additionalProperties": False,
}
SPEECH_SCHEMA = {
    "type": "object",
    "properties": {
        "limit": {"type": "integer", "default": 50},
        "since_id": {"type": "integer", "default": 0},
    },
    "additionalProperties": False,
}
SEND_KEY_SCHEMA = {
    "type": "object",
    "properties": {"gesture": {"type": "string"}},
    "required": ["gesture"],
    "additionalProperties": False,
}


class _FakeSession:
    """Minimal stand-in for an mcp.Client session."""

    def __init__(self, tools=None):
        self._tools = tools or []
        self.calls = []

    async def list_tools(self):
        class _Listed:
            def __init__(self, tools):
                self.tools = tools

        return _Listed(self._tools)

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"structured_content": {"ok": True, "name": name, "args": arguments}}


class _FakeRemoteTool:
    def __init__(self, name, description, input_schema):
        self.name = name
        self.description = description
        self.input_schema = input_schema


def test_signature_from_schema_required_and_defaults():
    sig = _signature_from_schema(SEND_KEYS_SCHEMA)
    params = sig.parameters
    assert list(params) == ["gestures", "delay_ms"], list(params)
    # required -> no default; annotation list
    assert params["gestures"].default is params["gestures"].empty
    assert params["gestures"].annotation is list
    # optional with server default -> uses it; annotation int
    assert params["delay_ms"].default == 0
    assert params["delay_ms"].annotation is int


def test_convert_tool_emits_array_items():
    fn = _make_tool_function(_FakeSession(), "send_keys", SEND_KEYS_SCHEMA)
    conv = OpenaiLlmClient._convert_tool(
        Tool(name="send_keys", description="d", tool_function=fn)
    )
    params = conv["function"]["parameters"]
    props = params["properties"]
    assert props["gestures"]["type"] == "array", props
    assert props["gestures"]["items"]["type"] == "string", props
    assert props["delay_ms"]["type"] == "integer", props
    assert params["required"] == ["gestures"], params


def test_convert_tool_scalar_schemas():
    for name, schema, required in [
        ("get_speech_log", SPEECH_SCHEMA, []),
        ("send_key", SEND_KEY_SCHEMA, ["gesture"]),
    ]:
        fn = _make_tool_function(_FakeSession(), name, schema)
        conv = OpenaiLlmClient._convert_tool(
            Tool(name=name, description="d", tool_function=fn)
        )
        params = conv["function"]["parameters"]
        assert params["required"] == required, (name, params)


def test_coerce_parses_stringified_array_and_drops_unset():
    coerced = _coerce_arguments(
        {"gestures": '["tab","enter"]', "delay_ms": None}, SEND_KEYS_SCHEMA
    )
    # stringified JSON array parsed; optional None dropped
    assert coerced == {"gestures": ["tab", "enter"]}, coerced


def test_flatten_prefers_structured_content():
    assert _flatten_result({"structured_content": {"x": 1}}) == json.dumps({"x": 1})


def test_flatten_falls_back_to_text_content():
    class _Block:
        def __init__(self, text):
            self.text = text

    class _Result:
        structured_content = None
        content = [_Block("hello"), _Block("world")]

    assert _flatten_result(_Result()) == "hello\nworld"


def test_register_mcp_tools_end_to_end_with_fake_session():
    async def _run():
        session = _FakeSession(
            tools=[
                _FakeRemoteTool("send_keys", "send key gestures", SEND_KEYS_SCHEMA),
                _FakeRemoteTool("send_key", "send one gesture", SEND_KEY_SCHEMA),
            ]
        )
        tools = await register_mcp_tools(session)
        assert [t["name"] for t in tools] == ["send_keys", "send_key"]
        # closure round-trips through the shared session
        result = await tools[0]["tool_function"](gestures=["tab", "enter"])
        assert session.calls == [("send_keys", {"gestures": ["tab", "enter"]})]
        assert json.loads(result)["ok"] is True
        # synthesized signature makes _convert_tool emit the array schema
        conv = OpenaiLlmClient._convert_tool(tools[0])
        assert (
            conv["function"]["parameters"]["properties"]["gestures"]["type"] == "array"
        )

    asyncio.run(_run())


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()
