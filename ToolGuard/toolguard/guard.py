import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "dashboard"))
try:
    from logger import log_call
except ImportError:
    def log_call(*args, **kwargs):
        pass

from detector import detect, NORMAL, FAIL_PLAIN_TEXT, FAIL_SCHEMA_LEAK, FAIL_WRONG_TOOL_NAME
from fixer import fix_plain_text_call, fix_wrong_tool_name, fix_schema_leak, fix_dropped_stream


def _build_and_log(outcome, detail, fixed, final_call):
    log_call(outcome, detail, fixed, final_call)
    return {"outcome": outcome, "detail": detail, "fixed_by_toolguard": fixed, "final_call": final_call}


def guard_response(response_json, original_messages, ask_model_fn):
    label, detail = detect(response_json)

    if label == NORMAL:
        call = response_json["choices"][0]["message"]["tool_calls"][0]["function"]
        final_call = {"name": call["name"], "arguments": call.get("arguments", "{}")}
        return _build_and_log(label, detail, False, final_call)

    if label == FAIL_PLAIN_TEXT:
        content = response_json["choices"][0]["message"].get("content", "")
        repaired = fix_plain_text_call(content, original_messages, ask_model_fn)
        repaired_label, _ = detect(repaired)
        if repaired_label == NORMAL:
            call = repaired["choices"][0]["message"]["tool_calls"][0]["function"]
            final_call = {"name": call["name"], "arguments": call.get("arguments", "{}")}
            return _build_and_log(label, detail, True, final_call)
        return _build_and_log(label, detail, False, None)

    if label == FAIL_WRONG_TOOL_NAME:
        repaired = fix_wrong_tool_name(response_json, original_messages, ask_model_fn)
        repaired_label, _ = detect(repaired)
        if repaired_label == NORMAL:
            call = repaired["choices"][0]["message"]["tool_calls"][0]["function"]
            final_call = {"name": call["name"], "arguments": call.get("arguments", "{}")}
            return _build_and_log(label, detail, True, final_call)
        return _build_and_log(label, detail, False, None)

    if label == FAIL_SCHEMA_LEAK:
        retry_response = fix_schema_leak(original_messages, ask_model_fn)
        retry_label, _ = detect(retry_response)
        if retry_label == NORMAL:
            call = retry_response["choices"][0]["message"]["tool_calls"][0]["function"]
            final_call = {"name": call["name"], "arguments": call.get("arguments", "{}")}
            return _build_and_log(label, detail, True, final_call)
        return _build_and_log(label, detail, False, None)

    return _build_and_log(label, detail, False, None)


def guard_dropped_stream(original_messages, ask_model_fn):
    retry_response = fix_dropped_stream(original_messages, ask_model_fn)
    retry_label, _ = detect(retry_response)
    if retry_label == NORMAL:
        call = retry_response["choices"][0]["message"]["tool_calls"][0]["function"]
        final_call = {"name": call["name"], "arguments": call.get("arguments", "{}")}
        return _build_and_log("FAIL_DROPPED_STREAM", "Stream was cut off before completion", True, final_call)
    return _build_and_log("FAIL_DROPPED_STREAM", "Stream was cut off before completion", False, None)
