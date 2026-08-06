"""Tests for tool call parsing (structured + text format)."""

import pytest
from src.tool_parser import (
    parse_tool_calls,
    parse_structured_tool_calls,
    parse_text_tool_calls,
    ToolCall,
)


class TestStructuredParsing:
    def test_structured_with_tool_calls(self):
        message = {
            "role": "assistant",
            "content": "Let me search for that.",
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "search_code",
                        "arguments": '{"query": "authentication"}',
                    }
                }
            ],
        }
        result = parse_structured_tool_calls(message)
        assert result.mode == "structured"
        assert len(result.calls) == 1
        assert result.calls[0].name == "search_code"
        assert result.calls[0].arguments == {"query": "authentication"}
        assert result.text_before == "Let me search for that."

    def test_structured_no_tool_calls(self):
        message = {
            "role": "assistant",
            "content": "Here is the answer.",
            "tool_calls": [],
        }
        result = parse_structured_tool_calls(message)
        assert result.mode == "none"
        assert len(result.calls) == 0

    def test_structured_multiple_calls(self):
        message = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "1", "function": {"name": "search_code", "arguments": '{"query": "auth"}'}},
                {"id": "2", "function": {"name": "read_file", "arguments": '{"path": "main.py"}'}},
            ],
        }
        result = parse_structured_tool_calls(message)
        assert len(result.calls) == 2
        assert result.calls[0].name == "search_code"
        assert result.calls[1].name == "read_file"

    def test_structured_dict_arguments(self):
        """Arguments can be a dict (not just string)."""
        message = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "1", "function": {"name": "grep_code", "arguments": {"pattern": "TODO"}}},
            ],
        }
        result = parse_structured_tool_calls(message)
        assert result.calls[0].arguments == {"pattern": "TODO"}


class TestTextParsing:
    def test_text_tool_call_xml_tags(self):
        text = (
            'I need to search for that.\n'
            '<tool_call>\n{"name": "search_code", "arguments": {"query": "login"}}\n</tool_call>'
        )
        result = parse_text_tool_calls(text)
        assert result.mode == "text"
        assert len(result.calls) == 1
        assert result.calls[0].name == "search_code"
        assert result.calls[0].arguments == {"query": "login"}

    def test_text_no_tool_call(self):
        text = "This is a regular response with no tool calls."
        result = parse_text_tool_calls(text)
        assert result.mode == "none"
        assert len(result.calls) == 0

    def test_text_parameters_key(self):
        """Some models use 'parameters' instead of 'arguments'."""
        text = '<tool_call>{"name": "read_file", "parameters": {"path": "app.py"}}</tool_call>'
        result = parse_text_tool_calls(text)
        assert len(result.calls) == 1
        assert result.calls[0].arguments == {"path": "app.py"}


class TestUnifiedParsing:
    def test_unified_prefers_structured(self):
        message = {
            "content": "text",
            "tool_calls": [
                {"id": "1", "function": {"name": "search_code", "arguments": "{}"}}
            ],
        }
        result = parse_tool_calls(message, prefer_structured=True)
        assert result.mode == "structured"

    def test_unified_falls_back_to_text(self):
        message = {
            "content": '<tool_call>{"name": "grep_code", "arguments": {"pattern": "TODO"}}</tool_call>',
            "tool_calls": None,
        }
        result = parse_tool_calls(message, prefer_structured=True)
        assert result.mode == "text"
        assert len(result.calls) == 1

    def test_unified_no_calls(self):
        message = {"content": "Just a regular answer."}
        result = parse_tool_calls(message)
        assert result.mode == "none"
