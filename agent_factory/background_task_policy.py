"""Tool-visibility rules for child runs owned by a background task."""

DELEGATED_RESULT_TOOL_ID = "deliver_result"
DELEGATED_ASK_USER_TOOL_ID = "ask_user"
DELEGATED_CONTEXT_TOOL_IDS = frozenset({DELEGATED_RESULT_TOOL_ID, DELEGATED_ASK_USER_TOOL_ID})
