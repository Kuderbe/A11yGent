import asyncio
import os

from a11y_gent.adaptor.mcp_tools import register_mcp_tools
from a11y_gent.adaptor.openai_llm_client import OpenaiLlmClient
from a11y_gent.model.task import Task
from a11y_gent.runner import AgentRunner
from a11y_gent.tooling.barrier import make_barrier_tool
from a11y_gent.tooling.verdict import make_verdict_tool
from dotenv import load_dotenv
from mcp import Client

load_dotenv()


MODEL = "gpt-5-mini"

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

        result = await AgentRunner(
            llm, task, MODEL, MAX_STEPS, "trajectory.jsonl"
        ).run()

        print("Verdict:", result["verdict"])





