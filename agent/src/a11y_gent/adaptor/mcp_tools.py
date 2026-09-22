"""Integrate an MCP server's tools into the agent as regular ``Tool``s.

The single entry point is :func:`register_mcp_tools`, which takes a live,
already-initialised MCP client session and returns one :class:`Tool` per tool
the server advertises. Each returned tool's ``tool_function`` is an *async*
closure that shares the given session, so every tool call reuses one
persistent connection instead of re-handshaking.

Because :class:`~a11y_gent.adaptor.openai_llm_client.OpenaiLlmClient` derives
each tool's JSON schema from ``inspect.signature(tool_function)``, we synthesise
a matching :class:`inspect.Signature` from the server-provided ``inputSchema``
and attach it to the closure via ``__signature__``. ``inspect.signature``
honours that attribute, so the LLM sees the server's real parameters.
"""

from __future__ import annotations

import inspect
import json
from typing import Any, Awaitable, Callable

from a11y_gent.model.tool import Tool


# JSON-schema primitive -> Python annotation used for the synthesised signature.
# The annotations are chosen so that OpenaiLlmClient._json_schema_type maps them
# back to the original JSON-schema type (string/integer/number/boolean/array/
# object), keeping the round-trip lossless for the types the client supports.
_JSON_TYPE_TO_ANNOTATION: dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


async def register_mcp_tools(session: Any) -> list[Tool]:
    """Return one :class:`Tool` per tool advertised by ``session``.

    ``session`` must be a live, initialised MCP client (e.g. an ``mcp.Client``
    used as an async context manager). The session is captured by each tool's
    closure and reused for every call, so keep it open for the agent run.
    """
    listed = await session.list_tools()
    remote_tools = getattr(listed, "tools", None)
    if remote_tools is None:
        # Some client surfaces return the sequence directly.
        remote_tools = listed

    tools: list[Tool] = []
    for remote in remote_tools:
        name = _tool_attr(remote, "name")
        description = _tool_attr(remote, "description") or ""
        input_schema = (
            _tool_attr(remote, "input_schema")
            or _tool_attr(remote, "inputSchema")
            or {}
        )
        tools.append(
            Tool(
                name=name,
                description=description,
                tool_function=_make_tool_function(session, name, input_schema),
            )
        )
    return tools


def _tool_attr(remote: Any, key: str) -> Any:
    """Read ``key`` from an MCP tool that may be a pydantic model or a dict."""
    if isinstance(remote, dict):
        return remote.get(key)
    return getattr(remote, key, None)


def _make_tool_function(
    session: Any, name: str, input_schema: dict[str, Any]
) -> Callable[..., Awaitable[str]]:
    """Build the async closure that invokes one MCP tool over ``session``."""

    async def tool_function(**kwargs: Any) -> str:
        arguments = _coerce_arguments(kwargs, input_schema)
        result = await session.call_tool(name, arguments)
        return _flatten_result(result)

    # Make the synthesised signature visible to inspect.signature so the LLM
    # client emits the correct JSON schema for this tool.
    tool_function.__signature__ = _signature_from_schema(input_schema)  # type: ignore[attr-defined]
    tool_function.__name__ = name
    return tool_function


def _signature_from_schema(input_schema: dict[str, Any]) -> inspect.Signature:
    """Turn an MCP ``inputSchema`` into a keyword-only :class:`inspect.Signature`."""
    properties: dict[str, Any] = input_schema.get("properties", {}) or {}
    required = set(input_schema.get("required", []) or [])

    parameters: list[inspect.Parameter] = []
    for prop_name, prop_schema in properties.items():
        prop_schema = prop_schema or {}
        json_type = prop_schema.get("type", "string")
        annotation = _JSON_TYPE_TO_ANNOTATION.get(json_type, str)

        if prop_name in required:
            default: Any = inspect.Parameter.empty
        elif "default" in prop_schema:
            default = prop_schema["default"]
        else:
            # Optional with no server-provided default: give it one so the
            # LLM may omit it (and it stays out of `required` in the schema).
            default = None

        parameters.append(
            inspect.Parameter(
                prop_name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                annotation=annotation,
                default=default,
            )
        )

    return inspect.Signature(parameters)


def _coerce_arguments(
    kwargs: dict[str, Any], input_schema: dict[str, Any]
) -> dict[str, Any]:
    """Best-effort fix-ups before sending arguments to the MCP server.

    Drops optional parameters the caller left as ``None`` (the synthesised
    signature's sentinel for "not provided"), so the server applies its own
    default; and parses JSON strings the LLM may send for array/object
    parameters (a known consequence of the LLM sometimes stringifying
    structured values).
    """
    properties: dict[str, Any] = input_schema.get("properties", {}) or {}
    required = set(input_schema.get("required", []) or [])

    arguments: dict[str, Any] = {}
    for key, value in kwargs.items():
        prop_schema = properties.get(key, {}) or {}
        json_type = prop_schema.get("type")

        # Drop optional params the caller left unset. The synthesised signature
        # gives optional params a sentinel default of None, so a None here for a
        # non-required param means "not provided" -- omit it so the server can
        # apply its own default.
        if value is None and key not in required:
            continue

        if json_type in ("array", "object") and isinstance(value, str):
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                pass

        arguments[key] = value

    return arguments


def _flatten_result(result: Any) -> str:
    """Reduce an MCP ``CallToolResult`` to a string for the tool message.

    Prefers ``structured_content`` (serialised as JSON); otherwise joins the
    text of any text content blocks; otherwise falls back to ``str``.
    """
    structured = getattr(result, "structured_content", None)
    if structured is None and isinstance(result, dict):
        structured = result.get("structured_content")
    if structured is not None:
        try:
            return json.dumps(structured, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(structured)

    content = getattr(result, "content", None)
    if content is None and isinstance(result, dict):
        content = result.get("content")
    if content:
        texts = [
            _tool_attr(block, "text")
            for block in content
            if _tool_attr(block, "text") is not None
        ]
        if texts:
            return "\n".join(texts)

    return str(result)
