"""Discover ordinary-user tasks with a DevTools-configured LLM client."""

from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.config import RunConfig
from a11y_gent.model.message import MessageOrigin
from a11y_gent.model.workflow import WorkflowTask
from a11y_gent.prompts import build_discovery_prompt


async def discover_tasks(config: RunConfig, llm: LlmClient) -> list[WorkflowTask]:
    """Return tasks supplied through the explicit discovery completion call."""
    history = [
        {
            "origin": MessageOrigin.USER,
            "name": "discovery",
            "content": build_discovery_prompt(config.application_url, config.discovery_instructions),
        }
    ]
    for _ in range(config.discovery_max_steps):
        response = await llm.infer(history, config.model)
        history.append(response["message"])
        for tool_call in response.get("tool_calls", []):
            if tool_call["tool"]["name"] == "complete_discovery":
                await llm.execute_tool_call(tool_call)
                return _tasks_from_completion(config.application_url, tool_call["arguments"])
            history.append(await llm.execute_tool_call(tool_call))
    raise RuntimeError("Discovery did not complete within the configured step limit")


def _tasks_from_completion(application_url: str, arguments: dict) -> list[WorkflowTask]:
    return [
        {"number": number, "url": application_url, "description": description}
        for number, description in enumerate(arguments["task_descriptions"], start=1)
    ]