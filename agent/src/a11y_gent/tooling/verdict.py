"""The ``report_verdict`` tool: the agent's explicit, structured termination.

A no-op sink: the reported status/summary live in the tool-call arguments and
are recovered afterwards by :func:`a11y_gent.tooling.extract.extract_verdict`.
Barriers are not part of the verdict; they are reported via ``report_barrier``.

Does NOT use ``from __future__ import annotations``: the OpenAI schema generator
introspects the real signature, so annotations must stay actual type objects.
"""

from a11y_gent.model.tool import Tool


def make_verdict_tool() -> Tool:
    """Build the ``report_verdict`` :class:`Tool`."""

    def report_verdict(status: str, summary: str) -> str:
        """Report the final verdict for the task and finish.

        ``status`` must be one of ``succeeded``, ``failed`` or
        ``succeeded_with_avoidable_difficulty``. ``summary`` is a short
        natural-language explanation of the outcome. Barriers are not given
        here -- report each barrier with ``report_barrier`` as you encounter it.
        """
        return "verdict recorded"

    return Tool(
        name="report_verdict",
        description=(
            "Report the final verdict for the task and finish. status is one of "
            "'succeeded', 'failed', 'succeeded_with_avoidable_difficulty'. "
            "Provide a short summary of the outcome. Do NOT list barriers here; "
            "report each barrier with report_barrier as you find it. Call this "
            "exactly once, when the task is completed or provably blocked."
        ),
        tool_function=report_verdict,
    )

