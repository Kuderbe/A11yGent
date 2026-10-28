"""Offline tests for DevTools-only confirmed-barrier enrichment."""

import asyncio

from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.model.message import MessageOrigin
from a11y_gent.report_enrichment import enrich_confirmed_barrier


class _CompletionLlm(LlmClient):
    def __init__(self):
        self.histories = []
        self.executed_calls = []
        self.action_count = 0

    async def infer(self, history, model, use_tools=True):
        self.histories.append(history)
        if not use_tools:
            return {
                "message": {
                    "origin": MessageOrigin.ASSISTANT,
                    "name": "assistant",
                    "content": "I will inspect the implementation details.",
                }
            }
        self.action_count += 1
        if self.action_count == 1:
            call = {"id": "inspect-page", "tool": _devtools_tool(), "arguments": {}}
        else:
            call = {
                "id": "complete-enrichment",
                "tool": {"name": "complete_report_enrichment", "description": "", "tool_function": lambda: None},
                "arguments": {
                    "title": "Unnamed payment button",
                    "implementation_context": "The button has no accessible name.",
                    "remediation_target": "Payment button",
                    "suggested_fix": "Provide an accessible name.",
                },
            }
        return {
            "message": {"origin": MessageOrigin.ASSISTANT, "name": "assistant", "content": "", "tool_calls": [call]},
            "tool_calls": [call],
        }

    async def execute_tool_call(self, tool_call):
        self.executed_calls.append(tool_call["tool"]["name"])
        return {
            "origin": MessageOrigin.TOOL,
            "name": tool_call["tool"]["name"],
            "content": "report enrichment completed",
            "reference_id": tool_call["id"],
        }


class _FailingLlm(LlmClient):
    async def infer(self, history, model, use_tools=True):
        raise RuntimeError("DevTools inspection timed out")

    async def execute_tool_call(self, tool_call):
        raise AssertionError("No tool call follows a failed inference")


class _IncompleteLlm(LlmClient):
    async def infer(self, history, model, use_tools=True):
        return {
            "message": {
                "origin": MessageOrigin.ASSISTANT,
                "name": "assistant",
                "content": "I need more implementation context.",
            }
        }

    async def execute_tool_call(self, tool_call):
        raise AssertionError("No tool call is available")


class _RecoveringLlm(LlmClient):
    def __init__(self):
        self.histories = []
        self.executed_calls = []
        self.action_count = 0

    async def infer(self, history, model, use_tools=True):
        self.histories.append(history)
        if not use_tools:
            return {"message": {"origin": MessageOrigin.ASSISTANT, "name": "assistant", "content": "I will revise the next action."}}
        self.action_count += 1
        if self.action_count == 1:
            calls = [
                {"id": "first", "tool": _devtools_tool(), "arguments": {}},
                {"id": "second", "tool": _devtools_tool(), "arguments": {}},
            ]
        else:
            calls = [
                {
                    "id": "complete-enrichment",
                    "tool": {"name": "complete_report_enrichment", "description": "", "tool_function": lambda: None},
                    "arguments": {
                        "title": "Unnamed payment button",
                        "implementation_context": "The button has no accessible name.",
                        "remediation_target": "Payment button",
                        "suggested_fix": "Provide an accessible name.",
                    },
                }
            ]
        return {"message": {"origin": MessageOrigin.ASSISTANT, "name": "assistant", "content": "", "tool_calls": calls}, "tool_calls": calls}

    async def execute_tool_call(self, tool_call):
        self.executed_calls.append(tool_call["tool"]["name"])
        return {"origin": MessageOrigin.TOOL, "name": tool_call["tool"]["name"], "content": "report enrichment completed", "reference_id": tool_call["id"]}


def test_enrichment_returns_completion_data_from_devtools_only_phase():
    llm = _CompletionLlm()

    enrichment = asyncio.run(enrich_confirmed_barrier(_barrier(), llm, "test-model", [_devtools_tool()], 3))

    assert enrichment == {
        "title": "Unnamed payment button",
        "implementation_context": "The button has no accessible name.",
        "remediation_target": "Payment button",
        "suggested_fix": "Provide an accessible name.",
    }
    assert llm.executed_calls == ["inspect_page", "complete_report_enrichment"]
    assert "The payment button has no accessible name." in llm.histories[0][0]["content"]


def test_enrichment_failure_preserves_the_error_for_manual_investigation():
    enrichment = asyncio.run(enrich_confirmed_barrier(_barrier(), _FailingLlm(), "test-model", [_devtools_tool()], 3))

    assert enrichment == {
        "title": "The payment button has no accessible name.",
        "implementation_context": "",
        "remediation_target": "",
        "suggested_fix": "manual investigation",
        "error": "DevTools inspection timed out",
    }


def test_enrichment_uses_manual_investigation_when_the_budget_ends_without_completion():
    enrichment = asyncio.run(enrich_confirmed_barrier(_barrier(), _IncompleteLlm(), "test-model", [_devtools_tool()], 1))

    assert enrichment == {
        "title": "The payment button has no accessible name.",
        "implementation_context": "",
        "remediation_target": "",
        "suggested_fix": "manual investigation",
        "error": "DevTools enrichment reached its interaction limit",
    }


def test_enrichment_observes_a_rejected_action_before_completion():
    llm = _RecoveringLlm()

    enrichment = asyncio.run(enrich_confirmed_barrier(_barrier(), llm, "test-model", [_devtools_tool()], 3))

    assert enrichment["suggested_fix"] == "Provide an accessible name."
    assert llm.executed_calls == ["complete_report_enrichment"]
    assert "received 2" in llm.histories[2][-1]["content"]


def test_enrichment_counts_a_rejected_action_against_its_budget():
    llm = _IncompleteLlm()

    enrichment = asyncio.run(enrich_confirmed_barrier(_barrier(), llm, "test-model", [_devtools_tool()], 1))

    assert enrichment["error"] == "DevTools enrichment reached its interaction limit"


def _barrier():
    return {
        "description": "The payment button has no accessible name.",
        "expected_behavior": "NVDA announces the payment button.",
        "actual_behavior": "NVDA announces only button.",
        "reproduction_steps": ["Navigate to payment."],
        "evidence": "Speech: button.",
    }


def _devtools_tool():
    return {"name": "inspect_page", "description": "", "tool_function": lambda: None}


def _run_all():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()