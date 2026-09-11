from a11y_gent.adaptor.openai_llm_client import OpenaiLlmClient
from a11y_gent.model.message import MessageOrigin
from a11y_gent.model.graph_state import GraphState
from a11y_gent.model.tool import Tool
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
import os
from random import random

load_dotenv()


model = "gpt-5-mini"



def main():

    base_url = os.environ["A11Y_GENT_OPENAI_BASE_URL"]
    api_key = os.environ["A11Y_GENT_OPENAI_API_KEY"]

    tools = [Tool(name="random_generator", description="generates a random number in the interval [0;1)", tool_function=random_generator)]

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

    res = graph.invoke({
        "llm": llm,
        "discovery_context": [
            {
                "origin": MessageOrigin.USER,
                "content": "Use the random_generator tool to generate a random number, then tell me the result.",
                "name": "user",
            }
        ],
    })

    print(res)


def llm_generate_node(state: GraphState):
    response = state["llm"].infer(state["discovery_context"], model)

    return {
        "discovery_context": [
            *state["discovery_context"],
            response["message"],
        ],
        "pending_tool_calls": response.get("tool_calls", []),
    }


def execute_tools_node(state: GraphState):
    tool_messages = [
        state["llm"].execute_tool_call(tool_call)
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


