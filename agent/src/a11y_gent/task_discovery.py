"""Discover ordinary-user tasks through a checkpointed LangGraph stage."""

import re
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.config import RunConfig
from a11y_gent.model.message import Message, MessageOrigin
from a11y_gent.model.tool import Tool
from a11y_gent.model.tool_call import ToolCall, serialize_tool_call
from a11y_gent.model.workflow import DiscoveryResult, WorkflowTask
from a11y_gent.prompts import build_discovery_prompt
from a11y_gent.runtime.reasoning import assert_plain_text_reasoning


class DiscoveryState(TypedDict):
    """State persisted for one discovery stage."""

    history: list[Message]
    tasks: list[WorkflowTask]
    incomplete: bool
    completed: bool
    pending_tool_calls: list["DiscoveryToolCall"]
    step_count: int


class DiscoveryToolCall(TypedDict):
    """A serializable discovery tool call awaiting observation."""

    id: str
    name: str
    arguments: dict[str, Any]


async def discover_tasks(
    config: RunConfig, llm: LlmClient, tools: list[Tool]
) -> DiscoveryResult:
    """Discover tasks through a standalone local phase invocation."""
    graph = build_discovery_graph(config, llm, tools)
    state = await graph.ainvoke(initial_discovery_state(config))
    if state["tasks"]:
        return DiscoveryResult(tasks=state["tasks"], incomplete=state["incomplete"])
    raise RuntimeError("Discovery found no suitable task")


def build_discovery_graph(config: RunConfig, llm: LlmClient, tools: list[Tool]):
    graph = StateGraph(DiscoveryState)
    graph.add_node("reason", _reason_node(llm, config.model))
    graph.add_node("act", _act_node(llm, config.model))
    graph.add_node("observe", _observe_node(llm, config.application_url, tools))
    graph.add_edge(START, "reason")
    graph.add_edge("reason", "act")
    graph.add_conditional_edges("act", _after_act, {"observe": "observe", "reason": "reason"})
    graph.add_conditional_edges("observe", _after_observe(config.discovery_max_steps), {"reason": "reason", "done": END})
    return graph.compile()


def initial_discovery_state(config: RunConfig) -> DiscoveryState:
    return {
        "history": [
            {
                "origin": MessageOrigin.USER,
                "name": "discovery",
                "content": build_discovery_prompt(config.application_url, config.discovery_instructions),
            }
        ],
        "tasks": [],
        "incomplete": False,
        "completed": False,
        "pending_tool_calls": [],
        "step_count": 0,
    }


def _reason_node(llm: LlmClient, model: str):
    async def reason(state: DiscoveryState) -> DiscoveryState:
        response = await llm.infer(state["history"], model, use_tools=False)
        assert_plain_text_reasoning(response["message"]["content"])
        return {**state, "history": [*state["history"], response["message"]]}

    return reason


def _act_node(llm: LlmClient, model: str):
    async def act(state: DiscoveryState) -> DiscoveryState:
        response = await llm.infer(state["history"], model)
        return {
            **state,
            "history": [*state["history"], _action_message(response["message"], response.get("tool_calls", []))],
            "pending_tool_calls": [_serialize_tool_call(call) for call in response.get("tool_calls", [])],
            "step_count": state["step_count"] + 1,
        }

    return act


def _observe_node(llm: LlmClient, application_url: str, tools: list[Tool]):
    tools_by_name = {tool["name"]: tool for tool in tools}

    async def observe(state: DiscoveryState) -> DiscoveryState:
        history = list(state["history"])
        tasks = state["tasks"]
        incomplete = state["incomplete"]
        completed = state["completed"]
        for call in state["pending_tool_calls"]:
            tool_call = _tool_call(call, tools_by_name)
            history.append(await llm.execute_tool_call(tool_call))
            if call["name"] == "complete_discovery":
                tasks = _tasks_from_completion(application_url, call["arguments"])
                incomplete = call["arguments"]["incomplete"]
                completed = not incomplete
        return {
            **state,
            "history": history,
            "tasks": tasks,
            "incomplete": incomplete,
            "completed": completed,
            "pending_tool_calls": [],
        }

    return observe


def _after_act(state: DiscoveryState) -> str:
    if state["pending_tool_calls"]:
        return "observe"
    return "reason"



def _after_observe(max_steps: int):
    def continue_or_stop(state: DiscoveryState) -> str:
        if state["completed"] or state["step_count"] >= max_steps:
            return "done"
        return "reason"

    return continue_or_stop


def _action_message(message: Message, tool_calls: list[ToolCall]) -> Message:
    return {
        **{key: value for key, value in message.items() if key != "tool_calls"},
        "tool_calls": [serialize_tool_call(tool_call) for tool_call in tool_calls],
    }


def _serialize_tool_call(tool_call: ToolCall) -> DiscoveryToolCall:
    return {
        "id": tool_call["id"],
        "name": tool_call["tool"]["name"],
        "arguments": tool_call["arguments"],
    }


def _tool_call(call: DiscoveryToolCall, tools_by_name: dict[str, Tool]) -> ToolCall:
    return {"id": call["id"], "tool": tools_by_name[call["name"]], "arguments": call["arguments"]}


def _tasks_from_completion(application_url: str, arguments: dict) -> list[WorkflowTask]:
    tasks = [
        {"number": number, "url": application_url, "description": description}
        for number, description in enumerate(arguments["task_descriptions"], start=1)
    ]
    return _deduplicate_tasks(tasks)


def _deduplicate_tasks(tasks: list[WorkflowTask]) -> list[WorkflowTask]:
    unique: list[WorkflowTask] = []
    descriptions: set[str] = set()
    for task in tasks:
        normalized = _normalize_description(task["description"])
        if normalized not in descriptions:
            descriptions.add(normalized)
            unique.append({**task, "number": len(unique) + 1})
    return unique


def _normalize_description(description: str) -> str:
    words = re.findall(r"\w+", description.lower())
    return " ".join(word for word in words if word not in {"a", "an", "the"})