import asyncio
import os
from random import random

from a11y_gent.adaptor.mcp_tools import register_mcp_tools
from a11y_gent.adaptor.openai_llm_client import OpenaiLlmClient
from a11y_gent.model.graph_state import GraphState
from a11y_gent.model.message import MessageOrigin
from a11y_gent.model.tool import Tool
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from mcp import Client

load_dotenv()


model = "gpt-5-mini"


def main():
    asyncio.run(main_async())


async def main_async():
    base_url = os.environ["A11Y_GENT_OPENAI_BASE_URL"]
    api_key = os.environ["A11Y_GENT_OPENAI_API_KEY"]
    mcp_url = os.environ.get("A11Y_GENT_MCP_URL", "http://192.168.64.4:8765/mcp")

    local_tools = [
        Tool(
            name="random_generator",
            description="generates a random number in the interval [0;1)",
            tool_function=random_generator,
        )
    ]

    # One persistent MCP session, shared by every registered tool for the whole
    # agent run. All tool calls reuse this connection instead of re-handshaking.
    async with Client(mcp_url) as session:
        mcp_tools = await register_mcp_tools(session)
        tools = [*local_tools, *mcp_tools]

        llm = OpenaiLlmClient(base_url, api_key, tools)

        graph = StateGraph(GraphState)
        graph.add_node("llm_generate", llm_generate_node)
        graph.add_node("execute_tools", execute_tools_node)

        graph.add_edge(START, "llm_generate")
        graph.add_conditional_edges(
            "llm_generate",
            should_continue,
            {
                "tools": "execute_tools",
                "done": END,
            },
        )
        graph.add_edge("execute_tools", "llm_generate")
        graph = graph.compile()

        res = await graph.ainvoke(
            {
                "llm": llm,
                "discovery_context": [
                    {
                        "origin": MessageOrigin.USER,
                        "content": "Tell me what tools you have availiable",
                        "name": "user",
                    }
                ],
            }
        )

        print(res)


async def llm_generate_node(state: GraphState):
    response = await state["llm"].infer(state["discovery_context"], model)

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
    if state.get("pending_tool_calls"):
        return "tools"

    return "done"


def random_generator() -> float:
    return random()


