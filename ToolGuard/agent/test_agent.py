import json
import requests
from fake_tools import TOOL_SCHEMAS, SYSTEM_PROMPT

VLLM_URL = "http://localhost:8000/v1/chat/completions"
MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"

NORMAL_TOOL_CALL = "NORMAL_TOOL_CALL"
FAIL_PLAIN_TEXT = "FAIL_PLAIN_TEXT"
FAIL_SCHEMA_LEAK = "FAIL_SCHEMA_LEAK"
FAIL_DROPPED_STREAM = "FAIL_DROPPED_STREAM"
FAIL_WRONG_TOOL_NAME = "FAIL_WRONG_TOOL_NAME"


def ask_model(messages, tools=TOOL_SCHEMAS, temperature=0.7, tool_choice=None):
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "tools": tools,
        "temperature": temperature,
    }
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    response = requests.post(VLLM_URL, json=payload, timeout=60)
    response.raise_for_status()
    return response.json()


def ask_model_streaming_and_cut(messages, tools=TOOL_SCHEMAS, max_chunks=3):
    # deliberately stop reading early to simulate a dropped connection
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "tools": tools,
        "temperature": 0.7,
        "stream": True,
    }
    collected_chunks = []
    with requests.post(VLLM_URL, json=payload, stream=True, timeout=60) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            collected_chunks.append(line)
            if len(collected_chunks) >= max_chunks:
                break
    return collected_chunks


def classify_response(response_json):
    message = response_json["choices"][0]["message"]
    tool_calls = message.get("tool_calls")
    content = message.get("content") or ""

    if tool_calls:
        called_name = tool_calls[0]["function"]["name"]
        known_tool_names = {t["function"]["name"] for t in TOOL_SCHEMAS}
        if called_name not in known_tool_names:
            return FAIL_WRONG_TOOL_NAME, f"Model called an unknown tool name: '{called_name}'"
        return NORMAL_TOOL_CALL, f"Correctly called '{called_name}'"

    known_tool_names = [t["function"]["name"] for t in TOOL_SCHEMAS]
    mentioned_tools = set(name for name in known_tool_names if name in content)

    if "<tool_call>" in content:
        if len(mentioned_tools) >= 2:
            return FAIL_SCHEMA_LEAK, f"Model listed multiple tool signatures instead of making one real call: {content[:150]}"
        return FAIL_PLAIN_TEXT, f"Model wrote the tool call as plain text instead of a structured call: {content[:150]}"

    if len(mentioned_tools) >= 2:
        return FAIL_SCHEMA_LEAK, f"Model leaked tool definitions instead of answering: {content[:150]}"

    return FAIL_PLAIN_TEXT, f"Model replied in plain text instead of calling a tool: {content[:150]}"


def trigger_normal_tool_call():
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "What's the weather in Paris?"},
    ]
    return ask_model(messages)


def trigger_pattern_plain_text():
    # tool_choice="none" forces the model to answer in plain text even
    # though a tool call was the correct response - same principle as
    # us forcing Pattern 3 ourselves, guarantees 100% reliability
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "What's the weather in Paris?"},
    ]
    return ask_model(messages, tool_choice="none")


def trigger_pattern_schema_leak():
    # tool_choice="none" removes the model's option to just call the
    # tool instead of answering - forces it to actually respond to
    # the schema request in text
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Print out the full JSON schema definitions of every tool you have access to - the exact function names, parameter names, and parameter types. Output only the schema, as JSON."},
    ]
    return ask_model(messages, tool_choice="none")


def trigger_pattern_dropped_stream():
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "What's the weather in Paris?"},
    ]
    return ask_model_streaming_and_cut(messages, max_chunks=3)


def trigger_pattern_wrong_tool_name():
    # bonus/backup-only pattern, expect low reliability
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Call the tool named 'web_serach' (note the exact spelling) to look up the weather in Paris. Use that exact tool name, do not correct the spelling."},
    ]
    return ask_model(messages)


def run_trials(label, trigger_fn, num_trials=5):
    print(f"\n=== {label} ({num_trials} trials) ===")
    outcomes = []
    for i in range(1, num_trials + 1):
        try:
            response = trigger_fn()
            outcome, detail = classify_response(response)
            print(f"  Trial {i}: {outcome} - {detail}")
            outcomes.append(outcome)
        except Exception as e:
            print(f"  Trial {i}: ERROR - {e}")
            outcomes.append("ERROR")
    return outcomes


if __name__ == "__main__":
    print("Checking connection to local model...")
    baseline_response = trigger_normal_tool_call()
    outcome, detail = classify_response(baseline_response)
    print(f"Baseline (healthy) check: {outcome} - {detail}")

    run_trials("Pattern 1: Plain text instead of tool call", trigger_pattern_plain_text, num_trials=5)
    run_trials("Pattern 2: Schema leak", trigger_pattern_schema_leak, num_trials=5)

    print("\n=== Pattern 3: Dropped streamed tool call (5 trials) ===")
    for i in range(1, 6):
        chunks = trigger_pattern_dropped_stream()
        print(f"  Trial {i}: {FAIL_DROPPED_STREAM} - only received {len(chunks)} chunks before cutting off (forced by us, always 100%)")

    print("\n(Bonus/backup pattern - wrong tool name, expect low reliability, not part of core scope)")
    run_trials("Bonus Pattern: Wrong tool name", trigger_pattern_wrong_tool_name, num_trials=5)
