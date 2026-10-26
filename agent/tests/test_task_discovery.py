"""Offline tests for DevTools-based ordinary-user task discovery."""

import asyncio

from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.config import RunConfig
from a11y_gent.model.message import MessageOrigin
from a11y_gent.task_discovery import discover_tasks


class _ScriptedLlm(LlmClient):
    def __init__(self, responses):
        self.responses = list(responses)
        self.executed_calls = []
        self.histories = []

    async def infer(self, history, model, use_tools=True):
        self.histories.append(history)
        calls = self.responses.pop(0)
        return {
            "message": {
                "origin": MessageOrigin.ASSISTANT,
                "name": "assistant",
                "content": "",
                "tool_calls": calls,
            },
            "tool_calls": calls,
        }

    async def execute_tool_call(self, tool_call):
        self.executed_calls.append(tool_call["tool"]["name"])
        return {
            "origin": MessageOrigin.TOOL,
            "name": tool_call["tool"]["name"],
            "content": "observed application state",
            "reference_id": tool_call["id"],
        }


def test_discover_tasks_returns_ordered_tasks_from_explicit_completion():
    llm = _ScriptedLlm(
        [
            [_devtools_call()],
            [
                _completion_call(
                    ["Browse available products.", "Purchase a product."], incomplete=False
                )
            ],
        ]
    )

    tasks = asyncio.run(discover_tasks(_config(), llm))

    assert tasks == [
        {
            "number": 1,
            "url": "https://shop.example/",
            "description": "Browse available products.",
        },
        {
            "number": 2,
            "url": "https://shop.example/",
            "description": "Purchase a product.",
        },
    ]
    assert llm.executed_calls == ["inspect_page", "complete_discovery"]
    assert "Use the test buyer account." in llm.histories[0][0]["content"]


def test_discover_tasks_does_not_treat_plain_model_text_as_a_task_list():
    llm = _ScriptedLlm(
        [
            [],
            [_completion_call(["Create an account."], incomplete=False)],
        ]
    )

    tasks = asyncio.run(discover_tasks(_config(), llm))

    assert tasks == [
        {
            "number": 1,
            "url": "https://shop.example/",
            "description": "Create an account.",
        }
    ]
    assert len(llm.histories) == 2


def test_discover_tasks_executes_preceding_devtools_calls_before_completion():
    llm = _ScriptedLlm(
        [
            [
                _devtools_call(),
                _completion_call(["Review account settings."], incomplete=False),
            ]
        ]
    )

    tasks = asyncio.run(discover_tasks(_config(), llm))

    assert tasks[0]["description"] == "Review account settings."
    assert llm.executed_calls == ["inspect_page", "complete_discovery"]


def _config():
    return RunConfig(
        application_url="https://shop.example/",
        task=None,
        model="test-model",
        openai_base_url="http://inference.test",
        openai_api_key="secret",
        nvda_mcp_url="http://nvda.test/mcp",
        trajectory_path="trajectory.jsonl",
        discovery_instructions="Use the test buyer account.",
    )


def _devtools_call():
    return {
        "id": "inspect-1",
        "tool": {"name": "inspect_page", "description": "", "tool_function": lambda: None},
        "arguments": {},
    }


def _completion_call(task_descriptions, incomplete):
    return {
        "id": "complete-1",
        "tool": {"name": "complete_discovery", "description": "", "tool_function": lambda: None},
        "arguments": {"task_descriptions": task_descriptions, "incomplete": incomplete},
    }


def _run_all():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()