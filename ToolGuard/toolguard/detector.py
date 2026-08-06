TOOL_NAMES = ["search", "calculate", "get_weather", "read_file"]

NORMAL = "NORMAL"
FAIL_PLAIN_TEXT = "FAIL_PLAIN_TEXT"
FAIL_SCHEMA_LEAK = "FAIL_SCHEMA_LEAK"
FAIL_WRONG_TOOL_NAME = "FAIL_WRONG_TOOL_NAME"


def detect(response_json, known_tool_names=TOOL_NAMES):
    message = response_json["choices"][0]["message"]
    tool_calls = message.get("tool_calls")
    content = message.get("content") or ""

    if tool_calls:
        called_name = tool_calls[0]["function"]["name"]
        if called_name not in known_tool_names:
            return FAIL_WRONG_TOOL_NAME, f"Unknown tool name: '{called_name}'"
        return NORMAL, f"Valid call to '{called_name}'"

    mentioned = set(name for name in known_tool_names if name in content)

    if "<tool_call>" in content:
        if len(mentioned) >= 2:
            return FAIL_SCHEMA_LEAK, "Multiple tool signatures listed instead of one real call"
        return FAIL_PLAIN_TEXT, "Tool call written as plain text instead of a structured call"

    if len(mentioned) >= 2:
        return FAIL_SCHEMA_LEAK, "Tool definitions leaked instead of a real answer"

    return FAIL_PLAIN_TEXT, "Plain text reply instead of a tool call"
