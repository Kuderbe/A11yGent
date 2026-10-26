"""The ``report_barrier`` tool: incremental, evidence-grounded barrier logging.

A no-op sink the agent calls each time it observes a barrier; the barrier data
lives in the tool-call arguments and is recovered by
:func:`a11y_gent.tooling.extract.extract_barriers`. Reporting barriers as they
occur keeps each one tied to the evidence available at that moment.

Does NOT use ``from __future__ import annotations``: the OpenAI schema generator
introspects the real signature, so ``wcag: list`` must stay an actual type
object to be emitted as an ``"array"``.
"""

from a11y_gent.model.tool import Tool


def make_barrier_tool() -> Tool:
    """Build the ``report_barrier`` :class:`Tool`."""

    def report_barrier(
        description: str,
        expected_behavior: str,
        actual_behavior: str,
        reproduction_steps: list,
        evidence: str,
    ) -> str:
        """Record one accessibility barrier you have just observed.

        Call this as soon as you encounter a barrier, before continuing.
        Include the expected and actual screen-reader behaviour, executed
        reproduction steps, and concrete grounding such as quoted NVDA speech or
        focus state.
        """
        return "barrier recorded"

    return Tool(
        name="report_barrier",
        description=(
            "Record one accessibility barrier the moment you observe it. Provide "
            "a description of what a real screen-reader user hits, expected and "
            "actual screen-reader behaviour, executed reproduction steps, and "
            "cited evidence such as NVDA speech or focus state. Call this once "
            "per distinct barrier as you find it."
        ),
        tool_function=report_barrier,
    )
