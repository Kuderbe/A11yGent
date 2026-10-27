"""Offline contracts for the read-only retrospective phase."""

import asyncio
from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.model.message import MessageOrigin
from a11y_gent.task_retrospective import retrospect


class _ScriptedLlm(LlmClient):
    def __init__(self, calls):
        self.calls = calls
        self.histories = []
        self.executed_calls = []

    async def infer(self, history, model, use_tools=True):
        self.histories.append(history)
        name, arguments = self.calls[len(self.histories) - 1]
        call = {
            "id": f"retrospective-{len(self.histories)}",
            "tool": {"name": name, "description": "", "tool_function": lambda: None},
            "arguments": arguments,
        }
        return {
            "message": {
                "origin": MessageOrigin.ASSISTANT,
                "name": "assistant",
                "content": "",
                "tool_calls": [call],
            },
            "tool_calls": [call],
        }

    async def execute_tool_call(self, tool_call):
        self.executed_calls.append(tool_call["tool"]["name"])
        return {
            "origin": MessageOrigin.TOOL,
            "name": tool_call["tool"]["name"],
            "content": "retrospective completed",
            "reference_id": tool_call["id"],
        }


def test_retrospect_accumulates_candidates_across_iterations_before_completion():
    llm = _ScriptedLlm(
        [
            ("create_candidate", {"description": "The confirmation might not be announced.", "verification_brief": "Submit the order and inspect NVDA speech for confirmation."}),
            ("create_candidate", {"description": "An error message might not be announced.", "verification_brief": "Submit invalid data and inspect NVDA speech."}),
            ("complete_retrospective", {}),
        ]
    )

    candidates = _retrospect(llm, _solve_history())

    assert candidates == [
        {
            "description": "The confirmation might not be announced.",
            "verification_brief": "Submit the order and inspect NVDA speech for confirmation.",
        },
        {
            "description": "An error message might not be announced.",
            "verification_brief": "Submit invalid data and inspect NVDA speech.",
        },
    ]
    assert len(llm.histories) == 3
    assert llm.executed_calls == ["create_candidate", "create_candidate", "complete_retrospective"]


def test_retrospect_excludes_directly_reported_conditions_without_mutating_history():
    history = _solve_history(with_direct_barrier=True)
    original = list(history)
    llm = _ScriptedLlm(
        [
            ("create_candidate", {"description": "The checkout button has no name.", "verification_brief": "Inspect the button announcement."}),
            ("create_candidate", {"description": "The confirmation might not be announced.", "verification_brief": "Submit and inspect NVDA speech."}),
            ("complete_retrospective", {}),
        ]
    )

    candidates = _retrospect(llm, history)

    assert [candidate["description"] for candidate in candidates] == [
        "The confirmation might not be announced."
    ]
    assert history == original


def test_retrospect_rejects_any_tool_except_its_completion_sink():
    llm = _ScriptedLlm([("read_speech", {})])

    try:
        _retrospect(llm, _solve_history())
    except RuntimeError as error:
        assert "create_candidate or complete_retrospective" in str(error)
    else:
        raise AssertionError("Retrospective must not execute external tools")


def test_retrospect_allows_an_empty_candidate_list():
    llm = _ScriptedLlm([("complete_retrospective", {})])

    assert _retrospect(llm, _solve_history()) == []
    assert llm.executed_calls == ["complete_retrospective"]


def test_retrospect_stops_when_candidate_creation_reaches_its_iteration_budget():
    llm = _ScriptedLlm(
        [
            ("create_candidate", {"description": "Candidate.", "verification_brief": "Check it."}),
            ("complete_retrospective", {}),
        ]
    )

    try:
        _retrospect(llm, _solve_history(), 1)
    except RuntimeError as error:
        assert str(error) == "Retrospective exceeded its iteration budget"
    else:
        raise AssertionError("Retrospective must stop after its iteration budget")
    assert llm.executed_calls == ["create_candidate"]


def _retrospect(llm, history, max_iterations=20):
    return asyncio.run(retrospect(_task(1), history, llm, "test-model", max_iterations))


def _task(number):
    return {"number": number, "url": "https://shop.example/", "description": "Purchase the first product."}


def _solve_history(with_direct_barrier=False):
    history = [
        {
            "origin": MessageOrigin.TOOL,
            "name": "read_speech",
            "content": "Checkout button announced. No confirmation followed submission.",
            "reference_id": "speech-1",
        }
    ]
    if with_direct_barrier:
        history.insert(
            0,
            {
                "origin": MessageOrigin.ASSISTANT,
                "name": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "barrier-1",
                        "tool": {"name": "report_barrier", "description": ""},
                        "arguments": {
                            "description": "The checkout button has no name.",
                            "expected_behavior": "NVDA announces the checkout button.",
                            "actual_behavior": "NVDA announces only button.",
                            "reproduction_steps": ["Navigate to checkout."],
                            "evidence": "Speech: button.",
                        },
                    }
                ],
            },
        )
    return history


def _run_all():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"OK  {test.__name__}")
    print(f"\n{len(tests)} test(s) passed.")


if __name__ == "__main__":
    _run_all()