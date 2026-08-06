def fix_plain_text_call(content, original_messages, ask_model_fn):
    repair_messages = original_messages + [
        {"role": "assistant", "content": content},
        {"role": "user", "content": "That was not a valid tool call. Based on what you were trying to do above, call the correct tool now, using the proper tool-calling format."},
    ]
    return ask_model_fn(repair_messages, tool_choice="auto")


def fix_wrong_tool_name(response_json, original_messages, ask_model_fn):
    wrong_call = response_json["choices"][0]["message"]["tool_calls"][0]
    repair_messages = original_messages + [
        {"role": "assistant", "content": None, "tool_calls": [wrong_call]},
        {"role": "user", "content": f"'{wrong_call['function']['name']}' is not a real tool name. Based on what you were trying to do, call the correct real tool now."},
    ]
    return ask_model_fn(repair_messages, tool_choice="auto")


def fix_schema_leak(original_messages, ask_model_fn):
    retry_messages = original_messages + [
        {"role": "user", "content": "Do not describe or list your tools. Actually call the correct tool now to answer the question."}
    ]
    return ask_model_fn(retry_messages)


def fix_dropped_stream(original_messages, ask_model_fn):
    return ask_model_fn(original_messages)
