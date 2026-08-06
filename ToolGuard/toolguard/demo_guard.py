import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "agent"))

from test_agent import (
    ask_model,
    trigger_pattern_plain_text,
    trigger_pattern_schema_leak,
)
from guard import guard_response, guard_dropped_stream

SYSTEM_PROMPT_MESSAGES = [
    {"role": "system", "content": "You are a helpful assistant with access to tools."},
    {"role": "user", "content": "What's the weather in Paris?"},
]


def show_result(pattern_name, result):
    print(f"\n--- {pattern_name} ---")
    print(f"  What happened:      {result['outcome']} - {result['detail']}")
    print(f"  Fixed by ToolGuard:  {result['fixed_by_toolguard']}")
    print(f"  Final usable call:   {result['final_call']}")


if __name__ == "__main__":
    print("Testing ToolGuard: does OUR code catch and fix each failure?\n")

    response = trigger_pattern_plain_text()
    result = guard_response(response, SYSTEM_PROMPT_MESSAGES, ask_model)
    show_result("Pattern 1: Plain text instead of tool call", result)

    response = trigger_pattern_schema_leak()
    result = guard_response(response, SYSTEM_PROMPT_MESSAGES, ask_model)
    show_result("Pattern 2: Schema leak", result)

    result = guard_dropped_stream(SYSTEM_PROMPT_MESSAGES, ask_model)
    show_result("Pattern 3: Dropped streamed call", result)
