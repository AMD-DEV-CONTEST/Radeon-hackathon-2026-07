import random
import sys
import os
import time

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "toolguard"))

from test_agent import (
    ask_model,
    trigger_normal_tool_call,
    trigger_pattern_plain_text,
    trigger_pattern_schema_leak,
    trigger_pattern_wrong_tool_name,
)
from guard import guard_response, guard_dropped_stream

SYSTEM_MESSAGES = [
    {"role": "system", "content": "You are a helpful assistant with access to tools."},
    {"role": "user", "content": "What's the weather in Paris?"},
]

SCENARIOS = ["normal", "plain_text", "schema_leak", "dropped_stream", "wrong_tool_name"]


def run_one_scenario():
    scenario = random.choice(SCENARIOS)
    if scenario == "normal":
        response = trigger_normal_tool_call()
        guard_response(response, SYSTEM_MESSAGES, ask_model)
    elif scenario == "plain_text":
        response = trigger_pattern_plain_text()
        guard_response(response, SYSTEM_MESSAGES, ask_model)
    elif scenario == "schema_leak":
        response = trigger_pattern_schema_leak()
        guard_response(response, SYSTEM_MESSAGES, ask_model)
    elif scenario == "dropped_stream":
        guard_dropped_stream(SYSTEM_MESSAGES, ask_model)
    elif scenario == "wrong_tool_name":
        response = trigger_pattern_wrong_tool_name()
        guard_response(response, SYSTEM_MESSAGES, ask_model)


if __name__ == "__main__":
    print("ToolGuard live agent loop running - simulating continuous tool-call traffic.")
    print("Watch dashboard/terminal_dashboard.py in another terminal to see it live.")
    while True:
        run_one_scenario()
        time.sleep(4)
