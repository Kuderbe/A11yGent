"""Offline contracts for the read-only retrospective phase."""

import asyncio
from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.model.message import MessageOrigin
from a11y_gent.task_retrospective import retrospect


class _ScriptedLlm(LlmClient):
    def __init__(self, descriptions, verification_briefs):
        self.descriptions = descriptions
        self.verification_briefs = verification_briefs
        self.histories = []
        self.executed_calls = []
        self.tool_name = "complete_retrospective"

    async def infer(self, history, model, use_tools=True):
        self.histories.append(history)
        return {
            "message": {
                "origin": MessageOrigin.ASSISTANT,
                "name": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "retrospective-1",
                        "tool": {
                            "name": self.tool_name,
                            "description": "",
                            "tool_function": lambda: None,
                        },
                        "arguments": {
                            "descriptions": self.descriptions,
                            "verification_briefs": self.verification_briefs,
                        },
                    }
                ],
            },
            "tool_calls": [
                {
                    "id": "retrospective-1",
                    "tool": {
                        "name": self.tool_name,
                        "description": "",
                        "tool_function": lambda: None,
                    },
                    "arguments": {
                        "descriptions": self.descriptions,
                        "verification_briefs": self.verification_briefs,
                    },
                }
            ],
        }

    async def execute_tool_call(self, tool_call):
        self.executed_calls.append(tool_call["tool"]["name"])
        return {
            "origin": MessageOrigin.TOOL,
            "name": tool_call["tool"]["name"],
            "content": "retrospective completed",
            "reference_id": tool_call["id"],
        }


def test_retrospect_returns_only_briefed_candidates_from_one_completion():
    llm = _ScriptedLlm(
        ["The confirmation might not be announced."],
        ["Submit the order and inspect NVDA speech for confirmation."],
    )

    candidates = _retrospect(llm, _solve_history())

    assert candidates == [
        {
            "description": "The confirmation might not be announced.",
            "verification_brief": "Submit the order and inspect NVDA speech for confirmation.",
        }
    ]
    assert len(llm.histories) == 1
    assert llm.executed_calls == ["complete_retrospective"]


def test_retrospect_excludes_directly_reported_conditions_without_mutating_history():
    history = _solve_history(with_direct_barrier=True)
    original = list(history)
    llm = _ScriptedLlm(
        ["The checkout button has no name.", "The confirmation might not be announced."],
        ["Inspect the button announcement.", "Submit and inspect NVDA speech."],
    )

    candidates = _retrospect(llm, history)

    assert [candidate["description"] for candidate in candidates] == [
        "The confirmation might not be announced."
    ]
    assert history == original


def test_retrospect_rejects_any_tool_except_its_completion_sink():
    llm = _ScriptedLlm(["Candidate."], ["Check the condition."])
    llm.tool_name = "read_speech"

    try:
        _retrospect(llm, _solve_history())
    except RuntimeError as error:
        assert "complete_retrospective" in str(error)
    else:
        raise AssertionError("Retrospective must not execute external tools")


def test_retrospect_allows_an_empty_candidate_list():
    llm = _ScriptedLlm([], [])

    assert _retrospect(llm, _solve_history()) == []
    assert llm.executed_calls == ["complete_retrospective"]


def _retrospect(llm, history):
    return asyncio.run(retrospect(_task(1), history, llm, "test-model"))


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