from __future__ import annotations

import json
import re
import uuid
from typing import Any

import structlog

from src.models import Tool, ToolCall, ToolCallFunction, ToolFunction

logger = structlog.get_logger(__name__)


def translate_tools_to_anthropic(tools: list[Tool]) -> list[dict[str, Any]]:
    """Translate OpenAI-format tools to Anthropic format.

    OpenAI: [{type: "function", function: {name, description, parameters}}]
    Anthropic: [{name, description, input_schema}]
    """
    result: list[dict[str, Any]] = []
    for tool in tools:
        result.append({
            "name": tool.function.name,
            "description": tool.function.description,
            "input_schema": tool.function.parameters or {"type": "object", "properties": {}},
        })
    return result


def translate_tools_to_bedrock(tools: list[Tool]) -> dict[str, Any]:
    """Translate OpenAI-format tools to Bedrock toolConfig format.

    Bedrock: {tools: [{toolSpec: {name, description, inputSchema: {json: ...}}}]}
    """
    bedrock_tools: list[dict[str, Any]] = []
    for tool in tools:
        bedrock_tools.append({
            "toolSpec": {
                "name": tool.function.name,
                "description": tool.function.description,
                "inputSchema": {
                    "json": tool.function.parameters or {"type": "object", "properties": {}},
                },
            }
        })
    return {"tools": bedrock_tools}


def translate_tools_to_openai(tools: list[Tool]) -> list[dict[str, Any]]:
    """Pass-through: tools are already in OpenAI format."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.function.name,
                "description": tool.function.description,
                "parameters": tool.function.parameters,
            },
        }
        for tool in tools
    ]


def translate_tools_to_react_prompt(tools: list[Tool]) -> str:
    """Convert tools to ReAct-style system prompt injection.

    For models without native function calling support, tools are
    described in the system prompt with Action/Action Input format.
    """
    if not tools:
        return ""

    lines = [
        "You have access to the following tools:",
        "",
    ]

    for tool in tools:
        params_desc = ""
        params = tool.function.parameters
        if params and "properties" in params:
            props = params["properties"]
            param_parts = []
            for prop_name, prop_schema in props.items():
                prop_type = prop_schema.get("type", "string")
                prop_desc = prop_schema.get("description", "")
                required_mark = ""
                if prop_name in params.get("required", []):
                    required_mark = " (required)"
                param_parts.append(f"    - {prop_name} ({prop_type}){required_mark}: {prop_desc}")
            if param_parts:
                params_desc = "\n  Parameters:\n" + "\n".join(param_parts)

        lines.append(f"- {tool.function.name}: {tool.function.description}{params_desc}")
        lines.append("")

    lines.extend([
        "To use a tool, respond EXACTLY in this format:",
        "",
        "Thought: [your reasoning about which tool to use]",
        "Action: [tool name]",
        'Action Input: [JSON object with parameters, e.g. {"param1": "value1"}]',
        "",
        "After receiving the tool result, continue reasoning or provide your final answer.",
        "If you don't need to use a tool, just respond normally.",
    ])

    return "\n".join(lines)


def parse_react_response(content: str) -> list[ToolCall] | None:
    """Parse ReAct-formatted tool calls from model response text.

    Looks for:
        Action: tool_name
        Action Input: {"key": "value"}

    Returns:
        List of ToolCall objects, or None if no tool calls found.
    """
    if not content:
        return None

    tool_calls: list[ToolCall] = []

    # Match Action/Action Input pairs
    pattern = r"Action:\s*(.+?)\s*\n\s*Action Input:\s*(.+?)(?:\n|$)"
    matches = re.finditer(pattern, content, re.DOTALL)

    for match in matches:
        tool_name = match.group(1).strip()
        raw_input = match.group(2).strip()

        # Try to parse the input as JSON
        try:
            # Handle multi-line JSON
            parsed = json.loads(raw_input)
            arguments = json.dumps(parsed)
        except json.JSONDecodeError:
            # If not valid JSON, wrap as a string argument
            arguments = json.dumps({"input": raw_input})

        tool_calls.append(ToolCall(
            id=f"react_{uuid.uuid4().hex[:8]}",
            type="function",
            function=ToolCallFunction(
                name=tool_name,
                arguments=arguments,
            ),
        ))

    return tool_calls if tool_calls else None


def normalize_anthropic_tool_calls(content_blocks: list[dict[str, Any]]) -> list[ToolCall]:
    """Normalize Anthropic tool_use content blocks to OpenAI format.

    Anthropic: [{type: "tool_use", id, name, input: {...}}]
    OpenAI: [{id, type: "function", function: {name, arguments: "..."}}]
    """
    tool_calls: list[ToolCall] = []
    for block in content_blocks:
        if block.get("type") != "tool_use":
            continue
        tool_calls.append(ToolCall(
            id=block.get("id", str(uuid.uuid4())),
            type="function",
            function=ToolCallFunction(
                name=block.get("name", ""),
                arguments=json.dumps(block.get("input", {})),
            ),
        ))
    return tool_calls


def normalize_bedrock_tool_calls(output_content: list[dict[str, Any]]) -> list[ToolCall]:
    """Normalize Bedrock toolUse output to OpenAI format.

    Bedrock: [{toolUse: {toolUseId, name, input: {...}}}]
    OpenAI: [{id, type: "function", function: {name, arguments: "..."}}]
    """
    tool_calls: list[ToolCall] = []
    for block in output_content:
        tool_use = block.get("toolUse")
        if tool_use is None:
            continue
        tool_calls.append(ToolCall(
            id=tool_use.get("toolUseId", str(uuid.uuid4())),
            type="function",
            function=ToolCallFunction(
                name=tool_use.get("name", ""),
                arguments=json.dumps(tool_use.get("input", {})),
            ),
        ))
    return tool_calls


def get_translator_for_provider(provider: str) -> str:
    """Get the translation strategy name for a provider.

    Returns one of: 'passthrough', 'anthropic', 'bedrock', 'react'
    """
    passthrough_providers = {"openai", "vllm", "azure", "ollama"}
    if provider in passthrough_providers:
        return "passthrough"
    if provider == "anthropic":
        return "anthropic"
    if provider == "bedrock":
        return "bedrock"
    # Unknown providers default to ReAct
    return "react"
