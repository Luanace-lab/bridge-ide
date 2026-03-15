"""
Tests for tool_bridge.py — MCP-to-API Tool Format Conversion

Tests cover:
  - MCP → Anthropic conversion (tools, tool calls, results)
  - MCP → OpenAI conversion (tools, tool calls, results)
  - MCP → Gemini conversion (tools, tool calls, results)
  - Schema extraction and cleaning
  - Batch conversion (convert_tools)
  - Validation (single tool, batch)
  - Edge cases (missing fields, empty schemas)
"""

import os
import sys
import unittest

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tool_bridge import (
    anthropic_tool_call_to_mcp,
    convert_tools,
    gemini_tool_call_to_mcp,
    mcp_result_to_anthropic,
    mcp_result_to_gemini,
    mcp_result_to_openai,
    mcp_to_anthropic,
    mcp_to_gemini,
    mcp_to_openai,
    openai_tool_call_to_mcp,
    validate_mcp_tool,
    validate_mcp_tools,
)

# Sample MCP tool definitions for testing
SAMPLE_MCP_TOOLS = [
    {
        "name": "bridge_send",
        "description": "Send message via Bridge API",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient agent ID"},
                "content": {"type": "string", "description": "Message content"},
            },
            "required": ["to", "content"],
        },
    },
    {
        "name": "bridge_receive",
        "description": "Receive buffered messages",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


class TestMCPToAnthropic(unittest.TestCase):
    """Test MCP → Anthropic conversion."""

    def test_basic_conversion(self):
        result = mcp_to_anthropic(SAMPLE_MCP_TOOLS)
        self.assertEqual(len(result), 2)
        tool = result[0]
        self.assertEqual(tool["name"], "bridge_send")
        self.assertEqual(tool["description"], "Send message via Bridge API")
        self.assertIn("input_schema", tool)
        self.assertEqual(tool["input_schema"]["type"], "object")

    def test_schema_uses_input_schema_key(self):
        result = mcp_to_anthropic(SAMPLE_MCP_TOOLS)
        # Anthropic uses input_schema (not inputSchema or parameters)
        self.assertIn("input_schema", result[0])
        self.assertNotIn("inputSchema", result[0])
        self.assertNotIn("parameters", result[0])

    def test_preserves_required(self):
        result = mcp_to_anthropic(SAMPLE_MCP_TOOLS)
        self.assertEqual(result[0]["input_schema"]["required"], ["to", "content"])

    def test_empty_schema(self):
        result = mcp_to_anthropic(SAMPLE_MCP_TOOLS)
        self.assertEqual(result[1]["input_schema"]["properties"], {})

    def test_no_mutation_of_input(self):
        import copy
        original = copy.deepcopy(SAMPLE_MCP_TOOLS)
        mcp_to_anthropic(SAMPLE_MCP_TOOLS)
        self.assertEqual(SAMPLE_MCP_TOOLS, original)


class TestAnthropicToolCallConversion(unittest.TestCase):
    """Test Anthropic tool call and result conversion."""

    def test_tool_call_to_mcp(self):
        result = anthropic_tool_call_to_mcp(
            tool_use_id="tu_123",
            name="bridge_send",
            input_data={"to": "agent_b", "content": "hello"},
        )
        self.assertEqual(result["id"], "tu_123")
        self.assertEqual(result["name"], "bridge_send")
        self.assertEqual(result["arguments"]["to"], "agent_b")

    def test_result_to_anthropic(self):
        result = mcp_result_to_anthropic(
            tool_use_id="tu_123",
            result="Message sent",
        )
        self.assertEqual(result["type"], "tool_result")
        self.assertEqual(result["tool_use_id"], "tu_123")
        self.assertEqual(result["content"], "Message sent")
        self.assertFalse(result["is_error"])

    def test_result_error(self):
        result = mcp_result_to_anthropic(
            tool_use_id="tu_123",
            result="Agent not found",
            is_error=True,
        )
        self.assertTrue(result["is_error"])


class TestMCPToOpenAI(unittest.TestCase):
    """Test MCP → OpenAI conversion."""

    def test_basic_conversion(self):
        result = mcp_to_openai(SAMPLE_MCP_TOOLS)
        self.assertEqual(len(result), 2)
        tool = result[0]
        self.assertEqual(tool["type"], "function")
        self.assertIn("function", tool)
        self.assertEqual(tool["function"]["name"], "bridge_send")

    def test_schema_uses_parameters_key(self):
        result = mcp_to_openai(SAMPLE_MCP_TOOLS)
        func = result[0]["function"]
        self.assertIn("parameters", func)
        self.assertNotIn("inputSchema", func)
        self.assertNotIn("input_schema", func)

    def test_wraps_in_function(self):
        result = mcp_to_openai(SAMPLE_MCP_TOOLS)
        for tool in result:
            self.assertEqual(tool["type"], "function")
            self.assertIn("function", tool)
            self.assertIn("name", tool["function"])
            self.assertIn("description", tool["function"])
            self.assertIn("parameters", tool["function"])


class TestOpenAIToolCallConversion(unittest.TestCase):
    """Test OpenAI tool call and result conversion."""

    def test_tool_call_to_mcp(self):
        result = openai_tool_call_to_mcp(
            call_id="call_abc",
            name="bridge_send",
            arguments={"to": "agent_b", "content": "hello"},
        )
        self.assertEqual(result["id"], "call_abc")
        self.assertEqual(result["name"], "bridge_send")

    def test_result_to_openai(self):
        result = mcp_result_to_openai(
            call_id="call_abc",
            result="Message sent",
        )
        self.assertEqual(result["type"], "function_call_output")
        self.assertEqual(result["call_id"], "call_abc")
        self.assertEqual(result["output"], "Message sent")


class TestMCPToGemini(unittest.TestCase):
    """Test MCP → Gemini conversion."""

    def test_basic_conversion(self):
        result = mcp_to_gemini(SAMPLE_MCP_TOOLS)
        self.assertEqual(len(result), 2)
        tool = result[0]
        self.assertEqual(tool["name"], "bridge_send")
        self.assertIn("parameters", tool)

    def test_strips_dollar_schema(self):
        tools = [
            {
                "name": "test",
                "description": "Test tool",
                "inputSchema": {
                    "$schema": "http://json-schema.org/draft-07/schema#",
                    "type": "object",
                    "properties": {"x": {"type": "number"}},
                },
            }
        ]
        result = mcp_to_gemini(tools)
        self.assertNotIn("$schema", result[0]["parameters"])

    def test_strips_additional_properties(self):
        tools = [
            {
                "name": "test",
                "description": "Test",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            }
        ]
        result = mcp_to_gemini(tools)
        self.assertNotIn("additionalProperties", result[0]["parameters"])


class TestGeminiToolCallConversion(unittest.TestCase):
    """Test Gemini tool call and result conversion."""

    def test_tool_call_to_mcp(self):
        result = gemini_tool_call_to_mcp(
            name="bridge_send",
            args={"to": "agent_b", "content": "hello"},
            call_id="gem_123",
        )
        self.assertEqual(result["id"], "gem_123")
        self.assertEqual(result["name"], "bridge_send")

    def test_tool_call_auto_id(self):
        result = gemini_tool_call_to_mcp(
            name="bridge_send",
            args={"to": "agent_b"},
        )
        self.assertEqual(result["id"], "gemini_bridge_send")

    def test_result_to_gemini(self):
        result = mcp_result_to_gemini(
            name="bridge_send",
            result={"ok": True, "message_id": 42},
        )
        self.assertEqual(result["name"], "bridge_send")
        self.assertEqual(result["response"]["ok"], True)


class TestSchemaExtraction(unittest.TestCase):
    """Test schema extraction edge cases."""

    def test_inputSchema_key(self):
        tools = [{"name": "t", "inputSchema": {"type": "object", "properties": {"x": {"type": "number"}}}}]
        result = mcp_to_anthropic(tools)
        self.assertIn("x", result[0]["input_schema"]["properties"])

    def test_input_schema_key(self):
        tools = [{"name": "t", "input_schema": {"type": "object", "properties": {"y": {"type": "string"}}}}]
        result = mcp_to_anthropic(tools)
        self.assertIn("y", result[0]["input_schema"]["properties"])

    def test_missing_schema(self):
        tools = [{"name": "t", "description": "No schema"}]
        result = mcp_to_anthropic(tools)
        self.assertEqual(result[0]["input_schema"]["type"], "object")

    def test_missing_description(self):
        tools = [{"name": "t", "inputSchema": {"type": "object", "properties": {}}}]
        result = mcp_to_anthropic(tools)
        self.assertEqual(result[0]["description"], "")


class TestBatchConversion(unittest.TestCase):
    """Test convert_tools batch function."""

    def test_anthropic(self):
        result = convert_tools(SAMPLE_MCP_TOOLS, "anthropic")
        self.assertEqual(len(result), 2)
        self.assertIn("input_schema", result[0])

    def test_openai(self):
        result = convert_tools(SAMPLE_MCP_TOOLS, "openai")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["type"], "function")

    def test_gemini(self):
        result = convert_tools(SAMPLE_MCP_TOOLS, "gemini")
        self.assertEqual(len(result), 2)
        self.assertIn("parameters", result[0])

    def test_unknown_target_raises(self):
        with self.assertRaises(ValueError) as ctx:
            convert_tools(SAMPLE_MCP_TOOLS, "cohere")
        self.assertIn("cohere", str(ctx.exception))

    def test_empty_tools(self):
        result = convert_tools([], "anthropic")
        self.assertEqual(result, [])


class TestValidation(unittest.TestCase):
    """Test MCP tool validation."""

    def test_valid_tool(self):
        errors = validate_mcp_tool(SAMPLE_MCP_TOOLS[0])
        self.assertEqual(errors, [])

    def test_missing_name(self):
        errors = validate_mcp_tool({"description": "No name"})
        self.assertTrue(any("name" in e for e in errors))

    def test_empty_name(self):
        errors = validate_mcp_tool({"name": "", "description": "Empty name"})
        self.assertTrue(any("name" in e for e in errors))

    def test_missing_description(self):
        errors = validate_mcp_tool({"name": "test"})
        self.assertTrue(any("description" in e for e in errors))

    def test_bad_schema_type(self):
        errors = validate_mcp_tool({
            "name": "test",
            "description": "Bad schema",
            "inputSchema": "not a dict",
        })
        self.assertTrue(any("dict" in e for e in errors))

    def test_schema_wrong_type(self):
        errors = validate_mcp_tool({
            "name": "test",
            "description": "Wrong schema type",
            "inputSchema": {"type": "array"},
        })
        self.assertTrue(any("object" in e for e in errors))

    def test_validate_batch(self):
        tools = [
            SAMPLE_MCP_TOOLS[0],
            {"description": "missing name"},
        ]
        errors = validate_mcp_tools(tools)
        self.assertEqual(len(errors), 1)  # Only tool[1] has errors


class TestGeminiSchemaClean(unittest.TestCase):
    """Test nested schema cleaning for Gemini."""

    def test_nested_additional_properties(self):
        tools = [
            {
                "name": "test",
                "description": "Nested",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "config": {
                            "type": "object",
                            "additionalProperties": True,
                            "properties": {
                                "key": {"type": "string"},
                            },
                        },
                    },
                },
            }
        ]
        result = mcp_to_gemini(tools)
        nested = result[0]["parameters"]["properties"]["config"]
        self.assertNotIn("additionalProperties", nested)
        self.assertIn("key", nested["properties"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
