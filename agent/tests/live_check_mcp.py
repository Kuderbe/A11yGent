"""Manual live check against the running NVDA MCP Bridge (not a unit test).

Run explicitly against the VM; requires network access to the NVDA host:

    A11Y_GENT_MCP_URL=http://192.168.64.4:8765/mcp \\
        PYTHONPATH=src python tests/live_check_mcp.py

It connects, registers the server's tools as agent Tools, prints the tool
inventory and the synthesized OpenAI schemas for a few representative tools,
and performs one real round-trip (get_focus_info) through a registered closure.
"""

import asyncio
import json
import os

from mcp import Client

from a11y_gent.adaptor.mcp_tools import register_mcp_tools
from a11y_gent.adaptor.openai_llm_client import OpenaiLlmClient


async def _run() -> None:
    url = os.environ.get("A11Y_GENT_MCP_URL", "http://192.168.64.4:8765/mcp")
    print(f"connecting to {url}")
    async with Client(url) as session:
        tools = await register_mcp_tools(session)
        print("registered tools:", [t["name"] for t in tools])

        for t in tools:
            if t["name"] in ("send_keys", "get_speech_log", "send_key"):
                conv = OpenaiLlmClient._convert_tool(t)
                print(t["name"], "schema:", json.dumps(conv["function"]["parameters"]))

        by_name = {t["name"]: t for t in tools}
        if "get_focus_info" in by_name:
            res = await by_name["get_focus_info"]["tool_function"]()
            print("get_focus_info result:", res[:400])


if __name__ == "__main__":
    asyncio.run(_run())
