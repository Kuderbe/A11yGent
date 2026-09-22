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
        evidence: str,
        wcag: list = None,
    ) -> str:
        """Record one accessibility barrier you have just observed.

        Call this as soon as you encounter a barrier, before continuing.
        ``description`` explains what a real screen-reader user hits;
        ``evidence`` must cite the concrete grounding (quoted NVDA speech, focus
        state, etc.); ``wcag`` optionally lists WCAG success-criterion strings.
        """
        return "barrier recorded"

    return Tool(
        name="report_barrier",
        description=(
            "Record one accessibility barrier the moment you observe it. Provide "
            "a description of what a real screen-reader user hits and cited "
            "evidence (quoted NVDA speech / focus state); optionally a list of "
            "wcag success-criterion references. Call this once per distinct "
            "barrier as you find it."
        ),
        tool_function=report_barrier,
    )
