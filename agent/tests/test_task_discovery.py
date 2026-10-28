"""Offline tests for DevTools-based ordinary-user task discovery."""

import asyncio
import tempfile
from pathlib import Path

from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.config import RunConfig
from a11y_gent.model.message import MessageOrigin
from a11y_gent.model.workflow import DiscoveryResult
from a11y_gent.task_discovery import discover_tasks


class _ScriptedLlm(LlmClient):
    def __init__(self, responses):
        self.responses = list(responses)
        self.executed_calls = []
        self.histories = []
        self.reason_turn = True

    async def infer(self, history, model, use_tools=True):
        self.histories.append(history)
        if self.reason_turn:
            self.reason_turn = False
            return {
                "message": {
                    "origin": MessageOrigin.ASSISTANT,
                    "name": "assistant",
                    "content": "I will inspect the application before selecting the next action.",
                }
            }
        self.reason_turn = True
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

    discovery = _discover(_config(), llm)

    assert discovery == DiscoveryResult(
        tasks=[
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
        ],
        incomplete=False,
    )
    assert llm.executed_calls == ["inspect_page", "complete_discovery"]
    assert "Use the test buyer account." in llm.histories[0][0]["content"]


def test_discover_tasks_does_not_treat_plain_model_text_as_a_task_list():
    llm = _ScriptedLlm(
        [
            [],
            [_completion_call(["Create an account."], incomplete=False)],
        ]
    )

    discovery = _discover(_config(), llm)

    assert discovery.tasks == [
        {
            "number": 1,
            "url": "https://shop.example/",
            "description": "Create an account.",
        }
    ]
    assert len(llm.histories) == 4


def test_discover_tasks_observes_a_rejected_batch_before_completion():
    llm = _ScriptedLlm(
        [
            [
                _devtools_call(),
                _completion_call(["Review account settings."], incomplete=False),
            ],
            [_completion_call(["Review account settings."], incomplete=False)],
        ]
    )

    discovery = _discover(_config(), llm)

    assert discovery.tasks[0]["description"] == "Review account settings."
    assert llm.executed_calls == ["complete_discovery"]
    assert "received 2" in _observation(llm, "received 2")["content"]


def test_discover_tasks_counts_a_rejected_action_against_its_budget():
    llm = _ScriptedLlm([[]])

    try:
        _discover(_config(discovery_max_steps=1), llm)
    except RuntimeError as error:
        assert str(error) == "Discovery found no suitable task"
    else:
        raise AssertionError("Expected rejected discovery action to consume its budget")
    assert llm.executed_calls == []


def test_discover_tasks_observes_unknown_and_invalid_argument_calls_before_completion():
    unknown = {"id": "unknown", "tool": {"name": "missing", "description": "", "tool_function": lambda: None}, "arguments": {}}
    invalid = {"id": "invalid", "tool": {"name": "inspect_page", "description": "", "tool_function": lambda: None}, "arguments": {"unexpected": True}}
    llm = _ScriptedLlm([[unknown], [invalid], [_completion_call(["Create an account."], incomplete=False)]])

    discovery = _discover(_config(), llm)

    assert discovery.tasks[0]["description"] == "Create an account."
    assert llm.executed_calls == ["complete_discovery"]
    assert "unknown tool 'missing'" in _observation(llm, "unknown tool 'missing'")["content"]
    assert "invalid arguments for 'inspect_page'" in _observation(llm, "invalid arguments for 'inspect_page'")["content"]


def test_discover_tasks_returns_partial_tasks_when_budget_ends_after_checkpoint():
    llm = _ScriptedLlm(
        [
            [_completion_call(["Browse available products."], incomplete=True)],
            [_devtools_call()],
        ]
    )

    discovery = _discover(_config(discovery_max_steps=2), llm)

    assert discovery == DiscoveryResult(
        tasks=[
            {
                "number": 1,
                "url": "https://shop.example/",
                "description": "Browse available products.",
            }
        ],
        incomplete=True,
    )


def test_discover_tasks_deduplicates_normalized_descriptions():
    llm = _ScriptedLlm(
        [[_completion_call(["Purchase a product.", "Purchase the product!"], incomplete=False)]]
    )

    discovery = _discover(_config(), llm)

    assert discovery.tasks == [
        {"number": 1, "url": "https://shop.example/", "description": "Purchase a product."}
    ]


def test_discover_tasks_fails_when_completion_contains_no_tasks():
    llm = _ScriptedLlm([[_completion_call([], incomplete=False)]])

    try:
        _discover(_config(), llm)
    except RuntimeError as error:
        assert str(error) == "Discovery found no suitable task"
    else:
        raise AssertionError("Expected discovery with no tasks to fail")


def test_discover_tasks_keeps_serialized_tool_call_text_in_reasoning():
    llm = _LeakingReasoningLlm()

    discovery = _discover(_config(), llm)

    assert discovery.tasks == [{"number": 1, "url": "https://shop.example/", "description": "Browse products."}]
    assert any(
        message["content"] == '<tool_call name="inspect_page">'
        for history in llm.histories
        for message in history
    )


def _config(discovery_max_steps=150):
    return RunConfig(
        application_url="https://shop.example/",
        task=None,
        model="test-model",
        openai_base_url="http://inference.test",
        openai_api_key="secret",
        nvda_mcp_url="http://nvda.test/mcp",
        trajectory_path="trajectory.jsonl",
        retrospective_max_iterations=20,
        discovery_instructions="Use the test buyer account.",
        discovery_max_steps=discovery_max_steps,
    )


def _devtools_call():
    return {
        "id": "inspect-1",
        "tool": {"name": "inspect_page", "description": "", "tool_function": lambda: None},
        "arguments": {},
    }


class _LeakingReasoningLlm(LlmClient):
    def __init__(self):
        self.histories = []
        self.reason_turn = True

    async def infer(self, history, model, use_tools=True):
        self.histories.append(history)
        if self.reason_turn:
            self.reason_turn = False
            return {"message": {"origin": MessageOrigin.ASSISTANT, "name": "assistant", "content": '<tool_call name="inspect_page">'}}
        self.reason_turn = True
        call = _completion_call(["Browse products."], incomplete=False)
        return {"message": {"origin": MessageOrigin.ASSISTANT, "name": "assistant", "content": "", "tool_calls": [call]}, "tool_calls": [call]}

    async def execute_tool_call(self, tool_call):
        return {
            "origin": MessageOrigin.TOOL,
            "name": tool_call["tool"]["name"],
            "content": "discovery completed",
            "reference_id": tool_call["id"],
        }


def _completion_call(task_descriptions, incomplete):
    def complete_discovery(task_descriptions: list, incomplete: bool):
        return None

    return {
        "id": "complete-1",
        "tool": {"name": "complete_discovery", "description": "", "tool_function": complete_discovery},
        "arguments": {"task_descriptions": task_descriptions, "incomplete": incomplete},
    }


def _discover(config, llm):
    with tempfile.TemporaryDirectory() as tmp:
        async def run_discovery():
            isolated_config = RunConfig(
                application_url=config.application_url,
                task=config.task,
                model=config.model,
                openai_base_url=config.openai_base_url,
                openai_api_key=config.openai_api_key,
                nvda_mcp_url=config.nvda_mcp_url,
                trajectory_path=str(Path(tmp) / "trajectory.jsonl"),
                retrospective_max_iterations=config.retrospective_max_iterations,
                discovery_instructions=config.discovery_instructions,
                discovery_max_steps=config.discovery_max_steps,
            )
            return await discover_tasks(
                isolated_config,
                llm,
                [_devtools_call()["tool"], _completion_call([], False)["tool"]],
            )

        return asyncio.run(run_discovery())


def _observation(llm, text):
    return next(
        message
        for history in llm.histories
        for message in history
        if text in message["content"]
    )


def _run_all():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()