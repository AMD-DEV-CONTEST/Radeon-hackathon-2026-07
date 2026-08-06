"""
fake_tools.py

WHAT THIS FILE IS FOR (plain English):
An AI agent needs "tools" it can call to actually do things - like
searching the web, or checking the weather. In a real product these
tools would call real APIs. For our hackathon demo, we don't need
real ones - we just need tools that LOOK real to the AI model, so we
can test whether the model calls them correctly.

Every tool below is fake: it doesn't actually search the internet or
check real weather. It just returns a believable made-up answer. This
is intentional and fine - we're testing whether TOOL CALLS are made
correctly, not whether the tools themselves are useful.

Each tool has two parts:
1. A Python function that "runs" the tool (fake_search, fake_calculate, etc.)
2. A "schema" - a structured description of the tool (name, what it does,
   what inputs it needs) written in the exact format AI models expect,
   so the model knows the tool exists and how to call it.
"""

import random


# ---------------------------------------------------------------------------
# PART 1: The actual fake tool functions
# ---------------------------------------------------------------------------

def fake_search(query: str) -> str:
    """Pretends to search the web and returns a made-up result."""
    return f"[FAKE SEARCH RESULT] Top result for '{query}': This is a simulated search result used for testing ToolGuard. No real search was performed."


def fake_calculate(expression: str) -> str:
    """Pretends to evaluate a math expression. Only handles simple
    + - * / on numbers, since we just need something believable, not
    a full calculator."""
    try:
        # Only allow digits, operators, spaces, and parentheses -
        # never actually eval() untrusted text as real Python code.
        allowed_chars = set("0123456789+-*/(). ")
        if not all(c in allowed_chars for c in expression):
            return f"[FAKE CALCULATE ERROR] '{expression}' contains characters that aren't allowed."
        result = eval(expression)
        return f"[FAKE CALCULATE RESULT] {expression} = {result}"
    except Exception:
        return f"[FAKE CALCULATE ERROR] Could not evaluate '{expression}'."


def fake_get_weather(city: str) -> str:
    """Pretends to check the weather and returns a made-up forecast."""
    fake_conditions = ["Sunny", "Cloudy", "Rainy", "Windy", "Clear"]
    fake_temp = random.randint(15, 35)
    condition = random.choice(fake_conditions)
    return f"[FAKE WEATHER RESULT] {city}: {condition}, {fake_temp}°C. (Simulated data for testing ToolGuard.)"


def fake_read_file(filename: str) -> str:
    """Pretends to read a file and returns made-up contents."""
    return f"[FAKE FILE CONTENTS] Contents of '{filename}': This is simulated file content used for testing ToolGuard. No real file was read."


# Lookup table so test_agent.py can call the right fake function
# once it knows which tool name the model asked for.
TOOL_FUNCTIONS = {
    "search": fake_search,
    "calculate": fake_calculate,
    "get_weather": fake_get_weather,
    "read_file": fake_read_file,
}


# ---------------------------------------------------------------------------
# PART 2: Tool schemas - how we describe these tools TO the AI model
# ---------------------------------------------------------------------------
# This is the standard "OpenAI-style" tool schema format, which vLLM's
# --enable-auto-tool-choice also understands. Each entry tells the model:
# the tool's name, what it does (in plain English), and what arguments
# it expects.

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search the web for information on a given topic or question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query or question to look up."
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate a basic math expression (addition, subtraction, multiplication, division).",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The math expression to evaluate, e.g. '12 * (4 + 3)'."
                    }
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather conditions for a given city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "The name of the city to check weather for."
                    }
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file given its filename.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "The name of the file to read, e.g. 'notes.txt'."
                    }
                },
                "required": ["filename"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# PART 3: System prompt - tells the model it has these tools available
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a helpful assistant with access to tools.
When the user asks something that requires using a tool (searching,
calculating, checking weather, or reading a file), call the
appropriate tool using a proper structured tool call. Do not describe
what you would do in plain text - actually call the tool."""


if __name__ == "__main__":
    # Quick manual test: run this file directly to sanity-check the
    # fake tools work on their own, with no AI model involved yet.
    print(fake_search("AMD ROCm reliability"))
    print(fake_calculate("12 * (4 + 3)"))
    print(fake_get_weather("Chennai"))
    print(fake_read_file("notes.txt"))
    print(f"\n{len(TOOL_SCHEMAS)} tool schemas defined: "
          f"{[t['function']['name'] for t in TOOL_SCHEMAS]}")
