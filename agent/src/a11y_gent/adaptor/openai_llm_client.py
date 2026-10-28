from a11y_gent.adaptor.llm_response import LlmResponse, ToolCallConversionError
from a11y_gent.model.message import Message, MessageOrigin
from a11y_gent.adaptor.llm_client import LlmClient
from a11y_gent.model.tool import Tool
from a11y_gent.model.tool_call import ToolCall, serialize_tool_call
from collections.abc import Callable
import inspect
import json
import time
from openai import AsyncOpenAI
from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam
from openai.types.chat.chat_completion_tool_union_param import ChatCompletionToolUnionParam
from typing import Any, cast, get_args, get_origin

from a11y_gent import observability


class OpenaiLlmClient(LlmClient):
    _client: AsyncOpenAI
    _tools: list[Tool]
    

    def __init__(
        self,
        base_url: str,
        api_key: str,
        tools: list[Tool],
        additional_headers: dict[str, str] = {},
    ):
        super().__init__()

        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            default_headers=additional_headers,
        )
        self._tools = tools



    async def infer(
        self, history: list[Message], model: str, use_tools: bool = True
    ) -> LlmResponse:
        messages = [OpenaiLlmClient._convert_message(m) for m in history]
        phase = "act" if use_tools else "think"
        request: dict[str, Any] = {"model": model, "messages": messages}
        if use_tools:
            tools = [self._convert_tool(tool) for tool in self._tools]
            request["tools"] = tools
            request["tool_choice"] = "required"
        observability.debug(
            "llm.request",
            phase=phase,
            model=model,
            messages=messages,
            tools=request.get("tools", []),
            tool_choice=request.get("tool_choice"),
        )

        started = time.perf_counter()
        res = await self._client.chat.completions.create(**request)
        elapsed_ms = round((time.perf_counter() - started) * 1000)

        choice = res.choices[0]
        response_message = choice.message
        content = response_message.content or ""
        raw_tool_calls = [
            {
                "id": tool_call.id,
                "name": tool_call.function.name,
                "arguments_raw": tool_call.function.arguments,
            }
            for tool_call in response_message.tool_calls or []
        ]
        observability.verbose(
            "llm.response",
            phase=phase,
            content=content,
            tool_calls=raw_tool_calls,
            elapsed_ms=elapsed_ms,
        )
        observability.debug(
            "llm.response",
            phase=phase,
            content=content,
            tool_calls=raw_tool_calls,
            finish_reason=getattr(choice, "finish_reason", None),
            elapsed_ms=elapsed_ms,
        )

        message: Message = {
                "origin": MessageOrigin.ASSISTANT,
                "content": content,
                "name": "assistant",
        }
        llm_response: LlmResponse = {"message": message}

        if response_message.tool_calls:
            tool_calls = [
                self._convert_tool_call(tool_call.id, tool_call.function.name, tool_call.function.arguments)
                for tool_call in response_message.tool_calls
            ]
            message["tool_calls"] = [serialize_tool_call(tool_call) for tool_call in tool_calls]
            llm_response["tool_calls"] = tool_calls

        return llm_response



    @staticmethod
    def _convert_message(message: Message) -> ChatCompletionMessageParam:
        content = message["content"] or ""
        if message["origin"] == MessageOrigin.ASSISTANT and message.get("tool_calls") and not content:
            content = "Tool call."
        res: dict[str, Any] = {
            "role": str(message["origin"]),
            "content": content,
            "name": message["name"]
        }

        if message["origin"] == MessageOrigin.TOOL:
            if "reference_id" not in message:
                raise ValueError("Tool messages require reference_id")
            res["tool_call_id"] = message["reference_id"]

        if message["origin"] == MessageOrigin.ASSISTANT and "tool_calls" in message:
            res["tool_calls"] = [
                {
                    "id": tool_call["id"],
                    "type": "function",
                    "function": {
                        "name": tool_call["tool"]["name"],
                        "arguments": json.dumps(tool_call["arguments"]),
                    },
                }
                for tool_call in message["tool_calls"]
            ]

        return cast(ChatCompletionMessageParam, res)


    async def execute_tool_call(self, tool_call: ToolCall) -> Message:
        tool_name = tool_call["tool"]["name"]
        observability.verbose(
            "tool.call", tool=tool_name, call_id=tool_call["id"], arguments=tool_call["arguments"]
        )
        observability.debug(
            "tool.call", tool=tool_name, call_id=tool_call["id"], arguments=tool_call["arguments"]
        )
        result = tool_call["tool"]["tool_function"](**tool_call["arguments"])
        if inspect.isawaitable(result):
            result = await result

        content = str(result)
        if tool_name not in {"report_barrier", "report_verdict"}:
            observability.observe(tool_name, content)
        observability.verbose("tool.result", tool=tool_name, call_id=tool_call["id"], result=content)
        observability.debug("tool.result", tool=tool_name, call_id=tool_call["id"], result=content)
        if tool_name == "report_barrier":
            observability.info("barrier.reported", **tool_call["arguments"])
        if tool_name == "report_verdict":
            observability.info("verdict.reported", **tool_call["arguments"])
        return {
            "origin": MessageOrigin.TOOL,
            "content": content,
            "name": tool_name,
            "reference_id": tool_call["id"],
        }


    def _convert_tool_call(self, tool_call_id: str, tool_name: str, arguments: str) -> ToolCall:
        observability.debug(
            "tool.arguments_raw", tool=tool_name, call_id=tool_call_id, arguments_raw=arguments
        )
        try:
            tool = self._get_tool(tool_name)
        except ValueError as error:
            raise ToolCallConversionError(tool_call_id, tool_name, arguments, str(error)) from error
        try:
            decoded_arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError as error:
            raise ToolCallConversionError(
                tool_call_id,
                tool_name,
                arguments,
                f"Invalid JSON arguments for '{tool_name}': {error}",
            ) from error

        return {
            "id": tool_call_id,
            "tool": tool,
            "arguments": decoded_arguments,
        }


    def _get_tool(self, tool_name: str) -> Tool:
        for tool in self._tools:
            if tool["name"] == tool_name:
                return tool

        raise ValueError(f"Unknown tool: {tool_name}")


    @staticmethod
    def _convert_tool(tool: Tool) -> ChatCompletionToolUnionParam:
        tool_function = tool["tool_function"]
        tool_name = tool["name"]
        signature = inspect.signature(tool_function)

        parameters: dict[str, Any] = {
            "type": "object",
            "properties": {},
            "required": [],
        }

        for parameter in signature.parameters.values():
            # OpenAI function tools require explicit named JSON properties;
            # Python's *args/**kwargs do not map to such fixed properties.
            if parameter.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue

            property_schema: dict[str, Any] = {
                "type": OpenaiLlmClient._json_schema_type(parameter.annotation),
            }
            if property_schema["type"] == "array":
                property_schema["items"] = {
                    "type": OpenaiLlmClient._json_schema_array_item_type(
                        parameter.annotation
                    ),
                }
            parameters["properties"][parameter.name] = property_schema

            if parameter.default is inspect.Parameter.empty:
                parameters["required"].append(parameter.name)

        res: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": tool["description"],
                "parameters": parameters,
            },
        }

        return cast(ChatCompletionToolUnionParam, res)


    @staticmethod
    def _json_schema_type(annotation: Any) -> str:
        origin = get_origin(annotation)
        match annotation:
            case inspect.Parameter.empty:
                return "string"
            case _ if annotation is str:
                return "string"
            case _ if annotation is int:
                return "integer"
            case _ if annotation is float:
                return "number"
            case _ if annotation is bool:
                return "boolean"
            case _ if annotation is list or origin in (list, tuple, set):
                return "array"
            case _ if annotation is dict or origin is dict:
                return "object"
            case _:
                return "string"


    @staticmethod
    def _json_schema_array_item_type(annotation: Any) -> str:
        # For parameterised generics like list[int] use the element type;
        # bare `list` (or anything unparameterised) defaults to string.
        args = get_args(annotation)
        if args:
            return OpenaiLlmClient._json_schema_type(args[0])
        return "string"