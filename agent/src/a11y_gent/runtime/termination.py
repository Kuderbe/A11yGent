"""Loop termination logic for the reason -> act -> observe graph.
"""

from a11y_gent.model.graph_state import GraphState
from a11y_gent.model.message import Message, MessageOrigin


def latest_message_calls(history: list[Message], tool_name: str) -> bool:
    """True if the last message is an assistant turn calling ``tool_name``."""
    if not history:
        return False
    last = history[-1]
    if last["origin"] != MessageOrigin.ASSISTANT:
        return False
    return any(
        call["tool"]["name"] == tool_name
        for call in last.get("tool_calls", []) or []
    )


def should_continue(state: GraphState) -> str:
    """End the run once report_verdict was called or the step cap is reached."""
    history = state["discovery_context"]
    if latest_message_calls(history, "report_verdict"):
        return "done"

    if state["step_count"] >= state["max_steps"]:
        return "done"

    # Run any tool calls (including report_barrier) and loop back to reasoning.
    return "tools"
