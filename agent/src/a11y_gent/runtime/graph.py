"""The reason -> act -> observe loop as a compiled LangGraph state graph.

Three nodes: ``think`` (reasoning-only inference, no tool calls), ``act``
(inference with tools, issues the next tool call), and ``execute_tools`` (runs
the pending tool calls). The model name and step cap are read from the graph
state, so this module holds no run configuration of its own.
"""

from a11y_gent.model.graph_state import GraphState
from a11y_gent.runtime.termination import should_continue
from langgraph.graph import StateGraph, START, END


def build_agent_graph():
    """Build the reason -> act -> observe loop as a LangGraph state graph."""
    graph = StateGraph(GraphState)
    graph.add_node("think", think_node)
    graph.add_node("act", act_node)
    graph.add_node("execute_tools", execute_tools_node)

    graph.add_edge(START, "think")
    graph.add_edge("think", "act")
    graph.add_conditional_edges(
        "act",
        should_continue,
        {
            "tools": "execute_tools",
            "done": END,
        },
    )
    graph.add_edge("execute_tools", "think")
    return graph.compile()


async def think_node(state: GraphState):
    """Reasoning-only turn: infer without tools so no action is taken."""
    response = await state["llm"].infer(
        state["discovery_context"], state["model"], use_tools=False
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
    response = await state["llm"].infer(
        state["discovery_context"], state["model"], use_tools=True
    )

    return {
        "discovery_context": [
            *state["discovery_context"],
            response["message"],
        ],
        "pending_tool_calls": response.get("tool_calls", []),
    }


async def execute_tools_node(state: GraphState):
    tool_messages = [
        await state["llm"].execute_tool_call(tool_call)
        for tool_call in state["pending_tool_calls"]
    ]

    return {
        "discovery_context": [
            *state["discovery_context"],
            *tool_messages,
        ],
        "pending_tool_calls": [],
    }
