"""Enrich confirmed barriers with DevTools implementation context."""

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.model.message import Message, MessageOrigin
from a11y_gent.model.tool import Tool
from a11y_gent.model.tool_call import ToolCall, serialize_tool_call
from a11y_gent.model.verdict import Barrier
from a11y_gent.model.workflow import BarrierEnrichment
from a11y_gent.prompts import build_report_enrichment_prompt, make_report_enrichment_completion_tool
from a11y_gent.runtime.reasoning import assert_plain_text_reasoning


class ReportEnrichmentState(TypedDict):
    """State persisted for one confirmed-barrier enrichment."""

    barrier: Barrier
    history: list[Message]
    pending_tool_calls: list["EnrichmentToolCall"]
    enrichment: BarrierEnrichment | None
    step_count: int


class EnrichmentToolCall(TypedDict):
    """A serializable enrichment tool call awaiting observation."""

    id: str
    name: str
    arguments: dict[str, Any]


async def enrich_confirmed_barrier(
    barrier: Barrier, llm: LlmClient, model: str, devtools_tools: list[Tool], max_steps: int
) -> BarrierEnrichment:
    """Return implementation context or a manual-investigation fallback."""
    state = await build_report_enrichment_graph(llm, model, devtools_tools, max_steps).ainvoke(
        initial_report_enrichment_state(barrier)
    )
    if state["enrichment"] is not None:
        return state["enrichment"]
    return _manual_investigation_enrichment(barrier, "DevTools enrichment reached its interaction limit")


def build_report_enrichment_graph(llm: LlmClient, model: str, devtools_tools: list[Tool], max_steps: int):
    """Build one DevTools-only enrichment graph."""
    graph = StateGraph(ReportEnrichmentState)
    graph.add_node("reason", _reason_node(llm, model))
    graph.add_node("act", _act_node(llm, model))
    graph.add_node("observe", _observe_node(llm, [*devtools_tools, make_report_enrichment_completion_tool()]))
    graph.add_edge(START, "reason")
    graph.add_conditional_edges("reason", _after_reason, {"act": "act", "done": END})
    graph.add_conditional_edges("act", _after_act(max_steps), {"observe": "observe", "reason": "reason", "done": END})
    graph.add_conditional_edges("observe", _after_observe(max_steps), {"reason": "reason", "done": END})
    return graph.compile()


def initial_report_enrichment_state(barrier: Barrier) -> ReportEnrichmentState:
    """Create a local state containing only the confirmed barrier."""
    return {
        "barrier": barrier,
        "history": [
            {
                "origin": MessageOrigin.USER,
                "name": "report_enrichment",
                "content": build_report_enrichment_prompt(barrier),
            }
        ],
        "pending_tool_calls": [],
        "enrichment": None,
        "step_count": 0,
    }


def _reason_node(llm: LlmClient, model: str):
    async def reason(state: ReportEnrichmentState) -> dict:
        try:
            response = await llm.infer(state["history"], model, use_tools=False)
            assert_plain_text_reasoning(response["message"]["content"])
        except Exception as error:
            return {"enrichment": _manual_investigation_enrichment(state["barrier"], str(error))}
        return {"history": [*state["history"], response["message"]]}

    return reason


def _act_node(llm: LlmClient, model: str):
    async def act(state: ReportEnrichmentState) -> dict:
        try:
            response = await llm.infer(state["history"], model)
        except Exception as error:
            return {"enrichment": _manual_investigation_enrichment(state["barrier"], str(error))}
        tool_calls = response.get("tool_calls", [])
        return {
            "history": [*state["history"], _action_message(response["message"], tool_calls)],
            "pending_tool_calls": [_serialize_tool_call(call) for call in tool_calls],
            "step_count": state["step_count"] + 1,
        }

    return act


def _observe_node(llm: LlmClient, tools: list[Tool]):
    tools_by_name = {tool["name"]: tool for tool in tools}

    async def observe(state: ReportEnrichmentState) -> dict:
        history = list(state["history"])
        enrichment = state["enrichment"]
        try:
            for call in state["pending_tool_calls"]:
                tool_call = {"id": call["id"], "tool": tools_by_name[call["name"]], "arguments": call["arguments"]}
                history.append(await llm.execute_tool_call(tool_call))
                if call["name"] == "complete_report_enrichment":
                    enrichment = {**call["arguments"]}
        except Exception as error:
            enrichment = _manual_investigation_enrichment(state["barrier"], str(error))
        return {"history": history, "pending_tool_calls": [], "enrichment": enrichment}

    return observe


def _after_act(max_steps: int):
    def continue_or_stop(state: ReportEnrichmentState) -> str:
        if state["enrichment"] is not None or state["step_count"] >= max_steps:
            return "done"
        return "observe" if state["pending_tool_calls"] else "reason"

    return continue_or_stop


def _after_reason(state: ReportEnrichmentState) -> str:
    return "done" if state["enrichment"] is not None else "act"


def _after_observe(max_steps: int):
    def continue_or_stop(state: ReportEnrichmentState) -> str:
        if state["enrichment"] is not None or state["step_count"] >= max_steps:
            return "done"
        return "reason"

    return continue_or_stop


def _action_message(message: Message, tool_calls: list[ToolCall]) -> Message:
    return {
        **{key: value for key, value in message.items() if key != "tool_calls"},
        "tool_calls": [serialize_tool_call(tool_call) for tool_call in tool_calls],
    }


def _serialize_tool_call(tool_call: ToolCall) -> EnrichmentToolCall:
    return {"id": tool_call["id"], "name": tool_call["tool"]["name"], "arguments": tool_call["arguments"]}


def _manual_investigation_enrichment(barrier: Barrier, error: str) -> BarrierEnrichment:
    return {
        "title": barrier["description"],
        "implementation_context": "",
        "remediation_target": "",
        "suggested_fix": "manual investigation",
        "error": error,
    }