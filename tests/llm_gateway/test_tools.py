"""Tests for llm-gateway tool format translation.

Tests translation between OpenAI, Anthropic, and Bedrock tool formats,
plus ReAct prompt generation and response parsing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "llm-gateway"))

from src.models import Tool, ToolCall, ToolCallFunction, ToolFunction
from src.tools import (
    get_translator_for_provider,
    normalize_anthropic_tool_calls,
    normalize_bedrock_tool_calls,
    parse_react_response,
    translate_tools_to_anthropic,
    translate_tools_to_bedrock,
    translate_tools_to_openai,
    translate_tools_to_react_prompt,
)


class TestTranslateToolsToAnthropic:
    """Tests for OpenAI -> Anthropic tool format conversion."""

    def test_basic_translation(self, sample_tools: list[Tool]) -> None:
        """Translates tool name, description, and parameters."""
        result = translate_tools_to_anthropic(sample_tools)
        assert len(result) == 2

        first = result[0]
        assert first["name"] == "search_evidence"
        assert first["description"] == "Search for compliance evidence files"
        assert first["input_schema"]["type"] == "object"
        assert "query" in first["input_schema"]["properties"]

    def test_tool_without_parameters(self) -> None:
        """Tool with empty parameters gets default schema."""
        tools = [
            Tool(
                type="function",
                function=ToolFunction(
                    name="get_status",
                    description="Get system status",
                    parameters={},
                ),
            )
        ]
        result = translate_tools_to_anthropic(tools)
        assert result[0]["input_schema"] == {"type": "object", "properties": {}}

    def test_empty_tools_list(self) -> None:
        """Empty list returns empty list."""
        result = translate_tools_to_anthropic([])
        assert result == []


class TestTranslateToolsToBedrock:
    """Tests for OpenAI -> Bedrock tool format conversion."""

    def test_basic_translation(self, sample_tools: list[Tool]) -> None:
        """Translates to Bedrock toolConfig format."""
        result = translate_tools_to_bedrock(sample_tools)
        assert "tools" in result
        assert len(result["tools"]) == 2

        first = result["tools"][0]
        assert first["toolSpec"]["name"] == "search_evidence"
        assert first["toolSpec"]["description"] == "Search for compliance evidence files"
        assert first["toolSpec"]["inputSchema"]["json"]["type"] == "object"

    def test_tool_without_parameters(self) -> None:
        """Tool with empty parameters gets default schema in Bedrock format."""
        tools = [
            Tool(
                type="function",
                function=ToolFunction(
                    name="simple_tool",
                    description="A simple tool",
                    parameters={},
                ),
            )
        ]
        result = translate_tools_to_bedrock(tools)
        tool_spec = result["tools"][0]["toolSpec"]
        assert tool_spec["inputSchema"]["json"] == {"type": "object", "properties": {}}

    def test_empty_tools_list(self) -> None:
        """Empty tools returns empty tools array."""
        result = translate_tools_to_bedrock([])
        assert result == {"tools": []}


class TestTranslateToolsToOpenAI:
    """Tests for passthrough OpenAI format."""

    def test_preserves_format(self, sample_tools: list[Tool]) -> None:
        """OpenAI format is preserved as-is."""
        result = translate_tools_to_openai(sample_tools)
        assert len(result) == 2
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "search_evidence"
        assert result[0]["function"]["parameters"]["type"] == "object"

    def test_empty_tools_list(self) -> None:
        """Empty list returns empty list."""
        result = translate_tools_to_openai([])
        assert result == []


class TestTranslateToolsToReactPrompt:
    """Tests for ReAct-style system prompt tool description."""

    def test_generates_react_prompt(self, sample_tools: list[Tool]) -> None:
        """Creates a ReAct prompt with tool descriptions."""
        prompt = translate_tools_to_react_prompt(sample_tools)
        assert "search_evidence" in prompt
        assert "get_control_status" in prompt
        assert "Action:" in prompt
        assert "Action Input:" in prompt
        assert "Thought:" in prompt

    def test_includes_parameter_info(self, sample_tools: list[Tool]) -> None:
        """Parameter details are included in the prompt."""
        prompt = translate_tools_to_react_prompt(sample_tools)
        assert "query" in prompt
        assert "required" in prompt.lower()
        assert "framework" in prompt

    def test_empty_tools_returns_empty(self) -> None:
        """No tools returns empty string."""
        prompt = translate_tools_to_react_prompt([])
        assert prompt == ""

    def test_tool_without_parameters(self) -> None:
        """Tool without parameters still renders correctly."""
        tools = [
            Tool(
                type="function",
                function=ToolFunction(
                    name="ping",
                    description="Ping the service",
                ),
            )
        ]
        prompt = translate_tools_to_react_prompt(tools)
        assert "ping" in prompt
        assert "Ping the service" in prompt


class TestParseReactResponse:
    """Tests for parsing ReAct tool calls from model text."""

    def test_parse_single_tool_call(self) -> None:
        """Parses a single Action/Action Input pair."""
        content = (
            "Thought: I need to search for evidence.\n"
            'Action: search_evidence\n'
            'Action Input: {"query": "SOC2 controls"}\n'
        )
        result = parse_react_response(content)
        assert result is not None
        assert len(result) == 1
        assert result[0].function.name == "search_evidence"
        args = json.loads(result[0].function.arguments)
        assert args["query"] == "SOC2 controls"

    def test_parse_multiple_tool_calls(self) -> None:
        """Parses multiple Action/Action Input pairs."""
        content = (
            "Thought: Let me check both.\n"
            "Action: search_evidence\n"
            'Action Input: {"query": "policy"}\n'
            "Thought: Now get the status.\n"
            "Action: get_control_status\n"
            'Action Input: {"control_id": "CC6.1"}\n'
        )
        result = parse_react_response(content)
        assert result is not None
        assert len(result) == 2
        assert result[0].function.name == "search_evidence"
        assert result[1].function.name == "get_control_status"

    def test_parse_invalid_json_wraps_as_string(self) -> None:
        """Non-JSON Action Input is wrapped as {input: ...}."""
        content = (
            "Thought: Let me search.\n"
            "Action: search_evidence\n"
            "Action Input: just a plain string query\n"
        )
        result = parse_react_response(content)
        assert result is not None
        args = json.loads(result[0].function.arguments)
        assert args["input"] == "just a plain string query"

    def test_parse_empty_content(self) -> None:
        """Empty content returns None."""
        assert parse_react_response("") is None
        assert parse_react_response(None) is None

    def test_parse_no_action_found(self) -> None:
        """Normal text without Action/Action Input returns None."""
        content = "This is just a normal response without any tool calls."
        assert parse_react_response(content) is None

    def test_tool_call_has_unique_id(self) -> None:
        """Each parsed tool call gets a unique ID starting with 'react_'."""
        content = (
            "Action: tool1\n"
            'Action Input: {"a": 1}\n'
            "Action: tool2\n"
            'Action Input: {"b": 2}\n'
        )
        result = parse_react_response(content)
        assert result is not None
        assert result[0].id.startswith("react_")
        assert result[1].id.startswith("react_")
        assert result[0].id != result[1].id


class TestNormalizeAnthropicToolCalls:
    """Tests for Anthropic -> OpenAI tool call normalization."""

    def test_normalizes_tool_use_blocks(self) -> None:
        """Converts Anthropic tool_use blocks to OpenAI format."""
        blocks = [
            {
                "type": "text",
                "text": "Let me search for that.",
            },
            {
                "type": "tool_use",
                "id": "toolu_123",
                "name": "search_evidence",
                "input": {"query": "SOC2 controls"},
            },
        ]
        result = normalize_anthropic_tool_calls(blocks)
        assert len(result) == 1
        assert result[0].id == "toolu_123"
        assert result[0].type == "function"
        assert result[0].function.name == "search_evidence"
        args = json.loads(result[0].function.arguments)
        assert args["query"] == "SOC2 controls"

    def test_multiple_tool_use_blocks(self) -> None:
        """Handles multiple tool_use blocks."""
        blocks = [
            {"type": "tool_use", "id": "t1", "name": "search", "input": {"q": "a"}},
            {"type": "tool_use", "id": "t2", "name": "get_status", "input": {"id": "c1"}},
        ]
        result = normalize_anthropic_tool_calls(blocks)
        assert len(result) == 2
        assert result[0].function.name == "search"
        assert result[1].function.name == "get_status"

    def test_skips_non_tool_use_blocks(self) -> None:
        """Non-tool_use blocks are ignored."""
        blocks = [
            {"type": "text", "text": "thinking..."},
            {"type": "image", "data": "base64..."},
        ]
        result = normalize_anthropic_tool_calls(blocks)
        assert result == []

    def test_empty_input(self) -> None:
        """Empty input returns empty list."""
        assert normalize_anthropic_tool_calls([]) == []

    def test_missing_fields_use_defaults(self) -> None:
        """Missing fields default to empty values."""
        blocks = [{"type": "tool_use"}]
        result = normalize_anthropic_tool_calls(blocks)
        assert len(result) == 1
        assert result[0].function.name == ""
        assert json.loads(result[0].function.arguments) == {}


class TestNormalizeBedrockToolCalls:
    """Tests for Bedrock -> OpenAI tool call normalization."""

    def test_normalizes_tool_use_output(self) -> None:
        """Converts Bedrock toolUse output to OpenAI format."""
        output = [
            {
                "toolUse": {
                    "toolUseId": "bedrock_call_456",
                    "name": "search_evidence",
                    "input": {"query": "ISO 27001 controls"},
                }
            }
        ]
        result = normalize_bedrock_tool_calls(output)
        assert len(result) == 1
        assert result[0].id == "bedrock_call_456"
        assert result[0].function.name == "search_evidence"
        args = json.loads(result[0].function.arguments)
        assert args["query"] == "ISO 27001 controls"

    def test_skips_non_tool_use_blocks(self) -> None:
        """Blocks without toolUse key are ignored."""
        output = [
            {"text": "some text"},
            {"toolUse": {"toolUseId": "t1", "name": "search", "input": {"q": "x"}}},
        ]
        result = normalize_bedrock_tool_calls(output)
        assert len(result) == 1
        assert result[0].function.name == "search"

    def test_empty_output(self) -> None:
        """Empty output returns empty list."""
        assert normalize_bedrock_tool_calls([]) == []

    def test_missing_fields_use_defaults(self) -> None:
        """Missing fields default to empty values with generated UUID."""
        output = [{"toolUse": {}}]
        result = normalize_bedrock_tool_calls(output)
        assert len(result) == 1
        assert result[0].function.name == ""
        assert result[0].id != ""  # UUID generated


class TestGetTranslatorForProvider:
    """Tests for provider -> translation strategy mapping."""

    def test_openai_is_passthrough(self) -> None:
        assert get_translator_for_provider("openai") == "passthrough"

    def test_vllm_is_passthrough(self) -> None:
        assert get_translator_for_provider("vllm") == "passthrough"

    def test_azure_is_passthrough(self) -> None:
        assert get_translator_for_provider("azure") == "passthrough"

    def test_ollama_is_passthrough(self) -> None:
        assert get_translator_for_provider("ollama") == "passthrough"

    def test_anthropic(self) -> None:
        assert get_translator_for_provider("anthropic") == "anthropic"

    def test_bedrock(self) -> None:
        assert get_translator_for_provider("bedrock") == "bedrock"

    def test_unknown_provider_uses_react(self) -> None:
        """Unknown providers default to ReAct style."""
        assert get_translator_for_provider("custom-local") == "react"
        assert get_translator_for_provider("") == "react"
