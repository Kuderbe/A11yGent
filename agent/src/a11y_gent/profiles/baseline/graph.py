"""The baseline alternating reasoning and action graph."""

from langgraph.graph import END, START, StateGraph

from a11y_gent import observability
from a11y_gent.profiles.baseline.state import BaselineState
from a11y_gent.runtime.reasoning import assert_plain_text_reasoning
from a11y_gent.runtime.termination import latest_message_calls


def build_graph():
    graph = StateGraph(BaselineState)
    graph.add_node("think", think_node)
    graph.add_node("act", act_node)
    graph.add_node("observe", observe_node)
    graph.add_edge(START, "think")
    graph.add_edge("think", "act")
    graph.add_conditional_edges("act", should_continue, {"observe": "observe", "done": END})
    graph.add_edge("observe", "think")
    return graph.compile()


async def think_node(state: BaselineState):
    observability.verbose("phase.started", phase="think", step=state["step_count"] + 1)
    observability.debug("phase.started", phase="think", step=state["step_count"] + 1)
    response = await state["llm"].infer(state["discovery_context"], state["model"], use_tools=False)
    assert_plain_text_reasoning(response["message"]["content"])
    observability.reason(response["message"]["content"])
    observability.verbose("phase.completed", phase="think", step=state["step_count"] + 1, thinking=response["message"]["content"])
    observability.debug("phase.completed", phase="think", step=state["step_count"] + 1, thinking=response["message"]["content"])
    return {"discovery_context": [*state["discovery_context"], response["message"]], "step_count": state["step_count"] + 1}


async def act_node(state: BaselineState):
    observability.verbose("phase.started", phase="act", step=state["step_count"])
    observability.debug("phase.started", phase="act", step=state["step_count"])
    response = await state["llm"].infer(state["discovery_context"], state["model"], use_tools=True)
    tool_calls = response.get("tool_calls", [])
    for call in tool_calls:
        if call["tool"]["name"] not in {"report_barrier", "report_verdict"}:
            observability.act(call["tool"]["name"], call["arguments"])
    calls = [{"tool": call["tool"]["name"], "arguments": call["arguments"]} for call in tool_calls]
    observability.verbose("phase.completed", phase="act", step=state["step_count"], tool_calls=calls)
    observability.debug("phase.completed", phase="act", step=state["step_count"], tool_calls=calls)
    return {"discovery_context": [*state["discovery_context"], response["message"]], "pending_tool_calls": tool_calls}


async def observe_node(state: BaselineState):
    observability.verbose("phase.started", phase="observe", tool_call_count=len(state["pending_tool_calls"]))
    observability.debug("phase.started", phase="observe", tool_call_count=len(state["pending_tool_calls"]))
    tool_messages = [await state["llm"].execute_tool_call(call) for call in state["pending_tool_calls"]]
    observability.verbose("phase.completed", phase="observe", result_count=len(tool_messages))
    observability.debug("phase.completed", phase="observe", result_count=len(tool_messages))
    return {"discovery_context": [*state["discovery_context"], *tool_messages], "pending_tool_calls": []}


def should_continue(state: BaselineState) -> str:
    if latest_message_calls(state["discovery_context"], "report_verdict"):
        return "done"
    if state["step_count"] >= state["max_steps"]:
        return "done"
    return "observe"