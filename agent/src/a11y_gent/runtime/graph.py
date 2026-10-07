"""The reason -> act -> observe loop as a compiled LangGraph state graph.

Three phases: ``think`` (reasoning-only inference, no tool calls), ``act``
(inference with tools, issues the next tool call), and ``observe`` (runs the
pending tool calls). The model name and step cap are read from the graph state,
so this module holds no run configuration of its own.
"""

from a11y_gent.model.graph_state import GraphState
from a11y_gent import observability
from a11y_gent.runtime.termination import should_continue
from langgraph.graph import StateGraph, START, END


def build_agent_graph():
    """Build the reason -> act -> observe loop as a LangGraph state graph."""
    graph = StateGraph(GraphState)
    graph.add_node("think", think_node)
    graph.add_node("act", act_node)
    graph.add_node("observe", observe_node)

    graph.add_edge(START, "think")
    graph.add_edge("think", "act")
    graph.add_conditional_edges(
        "act",
        should_continue,
        {
            "observe": "observe",
            "done": END,
        },
    )
    graph.add_edge("observe", "think")
    return graph.compile()


async def think_node(state: GraphState):
    """Reasoning-only turn: infer without tools so no action is taken."""
    observability.verbose("phase.started", phase="think", step=state["step_count"] + 1)
    observability.debug("phase.started", phase="think", step=state["step_count"] + 1)
    response = await state["llm"].infer(
        state["discovery_context"], state["model"], use_tools=False
    )
    observability.verbose(
        "phase.completed",
        phase="think",
        step=state["step_count"] + 1,
        thinking=response["message"]["content"],
    )
    observability.debug(
        "phase.completed",
        phase="think",
        step=state["step_count"] + 1,
        thinking=response["message"]["content"],
    )

    return {
        "discovery_context": [
            *state["discovery_context"],
            response["message"],
        ],
        "step_count": state["step_count"] + 1,
    }


async def act_node(state: GraphState):
    """Action turn: infer with tools; the model issues the next tool call."""
    observability.verbose("phase.started", phase="act", step=state["step_count"])
    observability.debug("phase.started", phase="act", step=state["step_count"])
    response = await state["llm"].infer(
        state["discovery_context"], state["model"], use_tools=True
    )
    observability.verbose(
        "phase.completed",
        phase="act",
        step=state["step_count"],
        tool_calls=[
            {"tool": call["tool"]["name"], "arguments": call["arguments"]}
            for call in response.get("tool_calls", [])
        ],
    )
    observability.debug(
        "phase.completed",
        phase="act",
        step=state["step_count"],
        tool_calls=[
            {"tool": call["tool"]["name"], "arguments": call["arguments"]}
            for call in response.get("tool_calls", [])
        ],
    )

    return {
        "discovery_context": [
            *state["discovery_context"],
            response["message"],
        ],
        "pending_tool_calls": response.get("tool_calls", []),
    }


async def observe_node(state: GraphState):
    observability.verbose(
        "phase.started",
        phase="observe",
        tool_call_count=len(state["pending_tool_calls"]),
    )
    observability.debug(
        "phase.started",
        phase="observe",
        tool_call_count=len(state["pending_tool_calls"]),
    )
    tool_messages = [
        await state["llm"].execute_tool_call(tool_call)
        for tool_call in state["pending_tool_calls"]
    ]
    observability.verbose("phase.completed", phase="observe", result_count=len(tool_messages))
    observability.debug("phase.completed", phase="observe", result_count=len(tool_messages))

    return {
        "discovery_context": [
            *state["discovery_context"],
            *tool_messages,
        ],
        "pending_tool_calls": [],
    }
