import asyncio
import os

from a11y_gent.adaptor.mcp_tools import register_mcp_tools
from a11y_gent.adaptor.openai_llm_client import OpenaiLlmClient
from a11y_gent.model.graph_state import GraphState
from a11y_gent.model.message import Message, MessageOrigin
from a11y_gent.model.task import Task
from a11y_gent.prompts import build_system_prompt, few_shot_exemplars
from a11y_gent.tooling.barrier import make_barrier_tool
from a11y_gent.tooling.extract import extract_verdict
from a11y_gent.tooling.verdict import make_verdict_tool
from a11y_gent.trajectory import write_jsonl
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from mcp import Client

load_dotenv()


model = "gpt-5-mini"

# Safety net for a run that never reports a verdict.
MAX_STEPS = 30


def main():
    asyncio.run(main_async())


async def main_async():
    base_url = os.environ["A11Y_GENT_OPENAI_BASE_URL"]
    api_key = os.environ["A11Y_GENT_OPENAI_API_KEY"]
    mcp_url = os.environ.get("A11Y_GENT_MCP_URL", "http://192.168.64.4:8765/mcp")

    # Fixed demo task until a task provider supplies these.
    task: Task = {
        "url": "http://127.0.0.1:8080/barrier.html",
        "goal": "Subscribe to the newsletter using the Subscribe button.",
    }

    local_tools = [make_verdict_tool(), make_barrier_tool()]

    # One persistent MCP session shared by every tool for the whole run.
    async with Client(mcp_url) as session:
        mcp_tools = await register_mcp_tools(session)
        tools = [*local_tools, *mcp_tools]

        llm = OpenaiLlmClient(base_url, api_key, tools)

        graph = _build_graph()

        seed_context = [
            {
                "origin": MessageOrigin.SYSTEM,
                "content": build_system_prompt(task),
                "name": "system",
            },
            *few_shot_exemplars(),
            {
                "origin": MessageOrigin.USER,
                "content": (
                    f"Begin the task now. URL: {task['url']}. "
                    f"Goal: {task['goal']}"
                ),
                "name": "user",
            },
        ]

        res = await graph.ainvoke(
            {
                "llm": llm,
                "task": task,
                "discovery_context": seed_context,
                "step_count": 0,
            }
        )

        history = res["discovery_context"]
        write_jsonl(history, "trajectory.jsonl")
        print("Verdict:", extract_verdict(history))


def _build_graph():
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
        state["discovery_context"], model, use_tools=False
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
        state["discovery_context"], model, use_tools=True
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
        for tool_call in state.get("pending_tool_calls", [])
    ]

    return {
        "discovery_context": [
            *state["discovery_context"],
            *tool_messages,
        ],
        "pending_tool_calls": [],
    }


def should_continue(state: GraphState) -> str:
    """End the run once report_verdict was called or the step cap is reached."""
    history = state["discovery_context"]
    if _latest_message_calls(history, "report_verdict"):
        return "done"

    if state["step_count"] >= MAX_STEPS:
        return "done"

    # Run any tool calls (including report_barrier) and loop back to reasoning.
    return "tools"


def _latest_message_calls(history: list[Message], tool_name: str) -> bool:
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



