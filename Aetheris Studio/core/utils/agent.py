"""The agent loop: stream a VTE response, run at most one tool call per
round if the model asks for one, feed the result back, and repeat until
the model answers without calling a tool (or a round limit is hit).

Emits the same SSE shapes the Flutter client already parses
(`{"delta": ...}`, `{"type": "tool_start"/"tool_output", ...}`, `[DONE]`),
so nothing on the frontend needs to change.
"""

import json
import logging
from typing import AsyncGenerator, Dict, List, Optional

from core.utils.tools import (
    TOOLS_SYSTEM_PROMPT, TOOL_REGISTRY, CLIENT_EXECUTED_TOOLS, parse_tool_call, strip_tool_call,
    is_risky_bash_command, render_todo_action,
)

logger = logging.getLogger(__name__)

# High enough for a real multi-file task (explore the project, read a
# reference file, then write several files one at a time -- e.g. index.html
# + style.css + script.js is already 3+ rounds before counting any reads).
MAX_ROUNDS = 20

# File-mutating tools always pause for the user's approval before running
# (see the `confirm_tool` branch below); bash only pauses when the command
# itself matches a destructive pattern (core/utils/tools.py::
# is_risky_bash_command) -- gating every bash call, even a plain `ls`, would
# make the agent unusably slow for the normal traffic a coding assistant
# needs to run constantly.
TOOLS_REQUIRING_CONFIRMATION = {"write_file", "edit_file"}


def _needs_confirmation(tool_name: str, tool_content: str) -> bool:
    if tool_name in TOOLS_REQUIRING_CONFIRMATION:
        return True
    if tool_name == "bash" and is_risky_bash_command(tool_content):
        return True
    return False


# A model stuck in a loop proposes the exact same tool call again right
# after already seeing its result (the "Preciso pesquisar X" -> "Pesquisei
# X, mas preciso pesquisar X" pattern). MAX_ROUNDS bounds the worst case,
# but without this it would still burn every one of those rounds repeating
# itself instead of making progress. One repeat gets a nudge instead of a
# re-execution; a second consecutive repeat breaks the loop outright.
MAX_REPEAT_NUDGES = 1

IDENTITY_PROMPT = (
    "You are Aetheris, a local AI coding/personal assistant running entirely on the "
    "user's own AMD GPU via the VTE inference engine -- no cloud API involved. "
    "Be direct and concise. Always reply in the same language the user's message is written in. "
    "If no tool is needed, always give a real conversational reply -- never answer by only "
    "repeating the user's message back."
)

# Builder/Planner mode: which tools are only meaningful in one mode or the
# other. Everything NOT in either set (list_files, read_file, manage_memory,
# navigate_browser, read_browser_page, bash for read-only commands, etc.)
# stays available in both -- Planner mode is meant to explore freely before
# proposing a plan, not to be read-only itself.
BUILDER_ONLY_TOOLS = {"write_file", "edit_file", "bash"}
PLANNER_ONLY_TOOLS = {"write_plan"}

PLANNER_MODE_PROMPT = (
    "\n\nYou are in PLANNING mode. Explore the project with read-only tools "
    "(list_files, read_file, bash for read-only commands, etc.) as needed, then write a complete "
    "implementation plan with the write_plan tool and stop -- do not write_file/edit_file/bash to "
    "make changes yet. The user reviews the plan and either approves it (you'll be told to "
    "start implementing, in a new turn) or sends feedback for you to revise the plan with another "
    "write_plan call."
)


def _build_system_prompt(mode: str) -> str:
    prompt = f"{IDENTITY_PROMPT}\n\n{TOOLS_SYSTEM_PROMPT}"
    if mode == "planner":
        prompt += PLANNER_MODE_PROMPT
    return prompt


def _sse_delta(text: str) -> str:
    return f"data: {json.dumps({'delta': text})}\n\n"


def _sse_event(event_type: str, data: Dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


# Observed Granite failure mode (reproduced directly against VTEModel.generate,
# no FastAPI/networking involved): with the tools system prompt in context, a
# short/ambiguous user turn like "oi" occasionally makes the model echo the
# input verbatim and hit EOS immediately, instead of a real reply. Buffer the
# first few tokens of each round so a degenerate echo-and-stop can be retried
# once, silently, before anything reaches the client -- once real content is
# flowing (buffer fills without the generator ending), stream normally.
MAX_DEGENERATE_RETRIES = 2
DEGENERATE_PEEK_TOKENS = 12


def _is_degenerate(text: str, last_user_message: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    return stripped.lower() == last_user_message.strip().lower()


async def _generate_with_retry(
    model: str, conversation: List[Dict], max_tokens: int, temperature: float, last_user_message: str
):
    from core.utils.vte_bridge import stream_generate

    for attempt in range(MAX_DEGENERATE_RETRIES + 1):
        gen = stream_generate(model, conversation, temperature=temperature, max_tokens=max_tokens)
        buffer: List[str] = []
        exhausted = True
        async for token in gen:
            buffer.append(token)
            if len(buffer) >= DEGENERATE_PEEK_TOKENS:
                exhausted = False
                break

        if exhausted and attempt < MAX_DEGENERATE_RETRIES and _is_degenerate("".join(buffer), last_user_message):
            logger.warning("Degenerate response on attempt %d, retrying: %r", attempt + 1, "".join(buffer))
            continue

        for token in buffer:
            yield token
        if not exhausted:
            async for token in gen:
                yield token
        return


async def stream_agent(
    model: str,
    messages: List[Dict],
    temperature: float = 0.3,
    max_tokens: int = 4096,
    owner: Optional[str] = None,
    mode: str = "builder",
) -> AsyncGenerator[str, None]:
    """Drive one full agent turn against `model`, streaming SSE lines.

    `mode` is "builder" (default -- tools act immediately) or "planner"
    (the agent explores with read-only tools and proposes a plan via
    write_plan instead of making changes; see BUILDER_ONLY_TOOLS/
    PLANNER_ONLY_TOOLS below)."""
    conversation: List[Dict] = [{"role": "system", "content": _build_system_prompt(mode)}]
    conversation += [m for m in messages if m.get("role") != "system"]

    last_executed_call: Optional[tuple] = None
    consecutive_repeats = 0
    # Scoped to this one turn only -- not persisted to disk or across
    # separate chat messages, see tools.py::render_todo_action's docstring.
    todo_list: List[Dict] = []

    for round_num in range(1, MAX_ROUNDS + 1):
        last_user_message = next(
            (m["content"] for m in reversed(conversation) if m.get("role") == "user"), ""
        )

        full_text = ""
        try:
            async for token in _generate_with_retry(model, conversation, max_tokens, temperature, last_user_message):
                full_text += token
                yield _sse_delta(token)
        except Exception as e:
            logger.error("VTE generation failed: %s", e)
            yield f'event: error\ndata: {json.dumps({"error": str(e), "status": 500})}\n\n'
            return

        tool_call = parse_tool_call(full_text)
        if not tool_call:
            break

        tool_name, tool_content = tool_call
        assistant_text = strip_tool_call(full_text) or f"[called {tool_name}]"

        wrong_mode_hint = None
        if mode == "planner" and tool_name in BUILDER_ONLY_TOOLS:
            wrong_mode_hint = "write_plan to describe what you'd do, or keep exploring with read-only tools"
        elif mode == "builder" and tool_name in PLANNER_ONLY_TOOLS:
            wrong_mode_hint = "the normal tools to make the change directly -- you're not in planning mode"
        if wrong_mode_hint:
            conversation.append({"role": "assistant", "content": assistant_text})
            conversation.append({
                "role": "user",
                "content": f"{tool_name} isn't available in {mode} mode right now. Use {wrong_mode_hint}.",
            })
            continue

        if tool_name == "write_plan":
            plan_text = tool_content.strip()
            yield _sse_event("plan_update", {"plan": plan_text, "round": round_num})
            conversation.append({"role": "assistant", "content": assistant_text})
            conversation.append({"role": "user", "content": "[write_plan result]\nPlan saved. Waiting for user review."})
            break

        if tool_name == "manage_todo":
            # Mutates the local todo_list directly -- no TOOL_REGISTRY
            # handler could hold this state between rounds itself, see
            # tools.py::SPECIAL_DISPATCH_TOOLS. Reuses the normal tool_
            # start/tool_output shape (no dedicated SSE event needed), so
            # the Flutter side already surfaces it in the Log tab with no
            # extra work.
            result_text = render_todo_action(todo_list, tool_content)
            yield _sse_event("tool_start", {"tool": tool_name, "round": round_num})
            yield _sse_event("tool_output", {"tool": tool_name, "result": {"output": result_text, "exit_code": 0}, "round": round_num})
            conversation.append({"role": "assistant", "content": assistant_text})
            conversation.append({"role": "user", "content": f"[manage_todo result]\n{result_text}"})
            continue

        if tool_name in CLIENT_EXECUTED_TOOLS:
            # This process can't run it -- the embedded browser lives in
            # the Flutter process. Pause the same way the confirm_tool
            # branch does: the client performs the action (navigate/read)
            # on its own follow-up call and feeds the result back as a
            # hidden continuation turn. No confirmation gate here --
            # navigating/reading isn't destructive, unlike write_file/
            # edit_file/risky bash.
            yield _sse_event("browser_action", {"tool": tool_name, "content": tool_content, "round": round_num})
            break

        handler = TOOL_REGISTRY.get(tool_name)
        if handler is None:
            # Shouldn't happen (parse_tool_call only matches registered
            # names), but don't loop forever on a stale/bad match.
            break

        if _needs_confirmation(tool_name, tool_content):
            # Pause here rather than executing: the client shows a
            # confirm/deny dialog and, on its own separate follow-up call,
            # either runs the tool via POST /api/tools/execute and continues
            # the conversation, or tells the model the user declined. This
            # backend is stateless per request (like every other route
            # here), so there's nothing to keep paused server-side -- the
            # stream just ends, same as the "no tool call" exit above.
            yield _sse_event("confirm_tool", {"tool": tool_name, "content": tool_content, "round": round_num})
            break

        current_call = (tool_name, tool_content)
        if current_call == last_executed_call:
            consecutive_repeats += 1
            if consecutive_repeats > MAX_REPEAT_NUDGES:
                yield _sse_event("loop_detected", {"tool": tool_name, "round": round_num})
                break
            conversation.append({"role": "assistant", "content": assistant_text})
            conversation.append({
                "role": "user",
                "content": (
                    "You just called this exact tool with identical input and already received its "
                    "result above -- repeating it won't help. Try something different, or explain what's "
                    "blocking you."
                ),
            })
            continue
        consecutive_repeats = 0

        yield _sse_event("tool_start", {"tool": tool_name, "round": round_num})
        try:
            result = await handler(tool_content, owner)
        except Exception as e:
            result = {"error": str(e), "exit_code": 1}
        yield _sse_event("tool_output", {"tool": tool_name, "result": result, "round": round_num})
        last_executed_call = current_call

        # The visible reply keeps only the prose before/after the tool
        # fence; the fence itself becomes the assistant's tool-call turn
        # in the conversation history, followed by the tool's result as a
        # user-role message so the next round can react to it.
        conversation.append({"role": "assistant", "content": assistant_text})
        result_text = result.get("output") or result.get("content") or result.get("error") or json.dumps(result)
        conversation.append({"role": "user", "content": f"[{tool_name} result]\n{result_text}"})

        if round_num == MAX_ROUNDS:
            yield _sse_event("rounds_exhausted", {"max_rounds": MAX_ROUNDS})

    yield "data: [DONE]\n\n"
