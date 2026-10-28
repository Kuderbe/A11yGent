"""Offline contracts for recoverable native tool-call actions."""

from a11y_gent.model.message import MessageOrigin
from a11y_gent.adaptor.openai_llm_client import OpenaiLlmClient
from a11y_gent.adaptor.llm_response import ToolCallConversionError
from a11y_gent.runtime.action_contract import rejected_action, validate_action


def test_multiple_calls_are_rejected_without_executing_either_call():
    action = {
        "origin": MessageOrigin.ASSISTANT,
        "name": "assistant",
        "content": "",
        "tool_calls": [_call("first"), _call("second")],
    }

    result = validate_action(action, {"inspect": _tool()})

    assert result["pending_tool_calls"] == []
    assert [observation["reference_id"] for observation in result["observations"]] == ["first", "second"]
    assert all("exactly one" in observation["content"] for observation in result["observations"])
    assert all("received 2" in observation["content"] for observation in result["observations"])


def test_missing_call_returns_a_correction_for_the_next_reasoning_turn():
    action = {"origin": MessageOrigin.ASSISTANT, "name": "assistant", "content": "", "tool_calls": []}

    result = validate_action(action, {"inspect": _tool()})

    assert result["pending_tool_calls"] == []
    assert result["observations"] == [
        {
            "origin": MessageOrigin.USER,
            "name": "action_contract",
            "content": "Action rejected: exactly one tool call is required; received 0. No requested tool was executed.",
        }
    ]


def test_unknown_tool_returns_a_matching_error_observation():
    action = {
        "origin": MessageOrigin.ASSISTANT,
        "name": "assistant",
        "content": "",
        "tool_calls": [{"id": "unknown", "tool": {"name": "missing", "description": ""}, "arguments": {}}],
    }

    result = validate_action(action, {"inspect": _tool()})

    assert result["pending_tool_calls"] == []
    assert result["observations"][0]["reference_id"] == "unknown"
    assert "unknown tool 'missing'" in result["observations"][0]["content"]


def test_invalid_arguments_return_a_matching_error_observation():
    action = {
        "origin": MessageOrigin.ASSISTANT,
        "name": "assistant",
        "content": "",
        "tool_calls": [{"id": "arguments", "tool": {"name": "required", "description": ""}, "arguments": {}}],
    }

    result = validate_action(action, {"required": _required_tool()})

    assert result["pending_tool_calls"] == []
    assert result["observations"][0]["reference_id"] == "arguments"
    assert "invalid arguments for 'required'" in result["observations"][0]["content"]


def test_rejected_calls_and_observations_convert_to_native_provider_messages():
    action = {
        "origin": MessageOrigin.ASSISTANT,
        "name": "assistant",
        "content": "",
        "tool_calls": [_call("first"), _call("second")],
    }
    result = validate_action(action, {"inspect": _tool()})

    messages = [OpenaiLlmClient._convert_message(message) for message in [action, *result["observations"]]]

    assert [call["id"] for call in messages[0]["tool_calls"]] == ["first", "second"]
    assert [message["tool_call_id"] for message in messages[1:]] == ["first", "second"]


def test_conversion_error_becomes_a_native_action_and_matching_observation():
    error = ToolCallConversionError("bad-json", "inspect", "{", "Invalid JSON arguments for 'inspect'.")

    action, observation = rejected_action(error)

    assert action["tool_calls"][0]["id"] == "bad-json"
    assert action["tool_calls"][0]["tool"]["name"] == "inspect"
    assert action["tool_calls"][0]["arguments"] == {}
    assert observation["reference_id"] == "bad-json"
    assert observation["content"] == "Invalid JSON arguments for 'inspect'."


def test_adapter_preserves_unknown_tool_conversion_context():
    client = OpenaiLlmClient.__new__(OpenaiLlmClient)
    client._tools = []

    try:
        client._convert_tool_call("unknown", "missing", "{}")
    except ToolCallConversionError as error:
        assert error.call_id == "unknown"
        assert error.tool_name == "missing"
        assert error.arguments_raw == "{}"
    else:
        raise AssertionError("Expected an unknown tool conversion error")


def test_adapter_preserves_invalid_json_conversion_context():
    client = OpenaiLlmClient.__new__(OpenaiLlmClient)
    client._tools = [_tool()]

    try:
        client._convert_tool_call("bad-json", "inspect", "{")
    except ToolCallConversionError as error:
        assert error.call_id == "bad-json"
        assert error.tool_name == "inspect"
        assert error.arguments_raw == "{"
    else:
        raise AssertionError("Expected an invalid JSON conversion error")


def test_provider_conversion_replaces_a_null_message_content_with_empty_text():
    message = {"origin": MessageOrigin.ASSISTANT, "name": "assistant", "content": None}

    converted = OpenaiLlmClient._convert_message(message)

    assert converted["content"] == ""


def _call(identifier):
    return {"id": identifier, "tool": {"name": "inspect", "description": ""}, "arguments": {}}


def _tool():
    return {"name": "inspect", "description": "", "tool_function": lambda: None}


def _required_tool():
    def required(value: str):
        return value

    return {"name": "required", "description": "", "tool_function": required}


def _run_all():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()