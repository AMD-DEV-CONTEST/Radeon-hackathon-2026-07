"""The agent loop: stream a VTE response, run at most one tool call per
round if the model asks for one, feed the result back, and repeat until
the model answers without calling a tool (or a round limit is hit).

Emits the same SSE shapes the Flutter client already parses
(`{"delta": ...}`, `{"type": "tool_start"/"tool_output", ...}`, `[DONE]`),
so nothing on the frontend needs to change.
"""

import asyncio
import json
import logging
from typing import AsyncGenerator, Dict, List, Optional, Tuple

from core.utils.tools import (
    TOOLS_SYSTEM_PROMPT, TOOL_REGISTRY, CLIENT_EXECUTED_TOOLS, ALL_TOOL_NAMES, parse_tool_call,
    strip_tool_call, is_risky_bash_command, render_todo_action, find_unmatched_tool_attempt,
)
from core.audit.flight_recorder import audit_enabled, audited_tool_call, get_recorder
from core.rag.cartographer import cartographer_auto_inject_enabled, looks_like_codebase_query, query_map
from core.utils.project_path import get_active_project_path

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
# rollback_action (Fase C, Time-Travel) is added here too even though the
# tool doesn't exist yet in TOOL_REGISTRY until that phase lands -- undoing
# an action is itself a write and must be gated the same as any other
# (invariant I4), and there's no cost to declaring that now.
TOOLS_REQUIRING_CONFIRMATION = {"write_file", "write_files", "edit_file", "rollback_action"}


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

# Same one-shot-nudge shape as MAX_REPEAT_NUDGES, for a different failure
# mode: a fenced block whose tag isn't any real tool (see
# tools.py::find_unmatched_tool_attempt). One correction naming the real
# tools is usually enough; a model that still can't produce a valid name
# after that isn't going to succeed by being told again.
MAX_UNMATCHED_TOOL_RETRIES = 1

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
BUILDER_ONLY_TOOLS = {"write_file", "write_files", "edit_file", "bash"}
PLANNER_ONLY_TOOLS = {"write_plan"}

PLANNER_MODE_PROMPT = (
    "\n\nYou are in PLANNING mode. Explore the project with read-only tools "
    "(list_files, read_file, bash for read-only commands, etc.) as needed, then write a complete "
    "implementation plan with the write_plan tool and stop -- do not write_file/edit_file/bash to "
    "make changes yet. The user reviews the plan and either approves it (you'll be told to "
    "start implementing, in a new turn) or sends feedback for you to revise the plan with another "
    "write_plan call.\n\n"
    "The plan MUST be delivered as a write_plan tool call, never as plain prose in your reply -- "
    "a plan written as regular text (even a long, detailed one) is invisible to the user: no "
    "approval popup appears, and there is nothing structured for a later Builder-mode turn to "
    "execute against. Use exactly this shape, with your actual plan on the lines after the fence:\n\n"
    "```write_plan\n"
    "<the full implementation plan, in markdown>\n"
    "```"
)


def _build_system_prompt(mode: str) -> str:
    prompt = f"{IDENTITY_PROMPT}\n\n{TOOLS_SYSTEM_PROMPT}"
    if mode == "planner":
        prompt += PLANNER_MODE_PROMPT
    return prompt


async def _cancel_and_close(next_task: "asyncio.Task", token_gen) -> None:
    """Cancel the in-flight `token_gen.__anext__()` task and only then close
    `token_gen` -- calling `.aclose()` immediately after `.cancel()`, with no
    await in between, is a real and reliably reproducible race, not just an
    artifact of a synthetic disconnect mock: `Task.cancel()` only *schedules*
    CancelledError delivery, it doesn't synchronously unwind the task, so at
    the moment `.aclose()` used to run here, the previous `__anext__()` call
    still owned the async generator's frame (`ag_running`) and Python raised
    "aclose(): asynchronous generator is already running". Confirmed directly
    with a standalone repro against a real pending Future (a genuine
    `asyncio.sleep`/socket-read suspension, not an eagerly-resolving mock):
    the error reproduced on every trial once the task had actually started
    and suspended on that inner await -- the normal state token_gen is in at
    both call sites below: the idle-wait branch only gets here after
    `asyncio.wait(..., timeout=...)` already found the task not-yet-done
    (definitely still deep in the network read), and the every-20-tokens
    branch runs right after a fresh `next_task` was created for the next
    token, which the intervening `await request.is_disconnected()` gives the
    loop enough of a tick to actually start and suspend on. Awaiting
    `next_task` first lets the cancellation
    actually propagate through token_gen's own awaits (and any try/finally
    along the way, e.g. `_generate_with_retry`'s own `await gen.aclose()`) so
    the frame is fully unwound before this `aclose()` touches it -- verified
    to remove the race across repeated trials of the same repro."""
    next_task.cancel()
    try:
        await next_task
    except asyncio.CancelledError:
        pass
    except Exception:
        pass
    await token_gen.aclose()


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
        gen = stream_generate(
            model, conversation, temperature=temperature, max_tokens=max_tokens,
            guided_choices=sorted(ALL_TOOL_NAMES), guided_choice_trigger="```",
        )
        # `gen` wraps an `async with client.stream(...)` in vte_bridge.py --
        # its httpx connection to vte-server only actually closes when THAT
        # block exits. If this whole function's own generator gets
        # cancelled (.aclose() called on it, e.g. because the caller
        # detected the end user disconnected), an `async for` loop over
        # `gen` does NOT automatically close `gen` just because the outer
        # generator is being torn down -- confirmed by checking CPython's
        # actual behavior, not assumed. Without this try/finally, cancelling
        # here left the httpx request to vte-server running to completion
        # regardless, which is exactly why Cancelar in the UI never
        # actually stopped the remote generation.
        try:
            # Only "content" chunks count toward the degenerate-response
            # peek/retry -- "reasoning" is never the reply, so it can't be
            # degenerate in the sense _is_degenerate checks (echoing the
            # user's own message back), and buffering it here would just
            # delay a real reasoning-capable model's visible "thinking"
            # signal behind an arbitrary DEGENERATE_PEEK_TOKENS threshold
            # for no reason. Reasoning chunks pass straight through,
            # uncounted and unbuffered.
            buffer: List[Tuple[str, str]] = []
            exhausted = True
            async for chunk in gen:
                kind, text = chunk
                if kind == "reasoning":
                    yield chunk
                    continue
                buffer.append(chunk)
                if len(buffer) >= DEGENERATE_PEEK_TOKENS:
                    exhausted = False
                    break

            peeked_text = "".join(text for _, text in buffer)
            if exhausted and attempt < MAX_DEGENERATE_RETRIES and _is_degenerate(peeked_text, last_user_message):
                logger.warning("Degenerate response on attempt %d, retrying: %r", attempt + 1, peeked_text)
                continue

            for chunk in buffer:
                yield chunk
            if not exhausted:
                async for chunk in gen:
                    yield chunk
            return
        finally:
            await gen.aclose()


async def stream_agent(
    model: str,
    messages: List[Dict],
    temperature: float = 0.3,
    max_tokens: int = 4096,
    owner: Optional[str] = None,
    mode: str = "builder",
    request=None,
    session_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Drive one full agent turn against `model`, streaming SSE lines.

    `mode` is "builder" (default -- tools act immediately) or "planner"
    (the agent explores with read-only tools and proposes a plan via
    write_plan instead of making changes; see BUILDER_ONLY_TOOLS/
    PLANNER_ONLY_TOOLS below).

    `request` (a starlette Request, or None -- kept untyped so this module
    doesn't need a hard FastAPI/Starlette import) lets the token loop below
    poll request.is_disconnected() and actually tear down the in-flight
    generation when the end user cancels, instead of continuing to consume
    and forward tokens from a client nobody's listening to anymore.
    StreamingResponse does not do this on its own -- confirmed directly,
    see _generate_with_retry's docstring for the full chain this closes.

    `session_id` (the chat's own id -- always present by the time a message
    can be sent, see chat_provider.dart's sendMessage guard) scopes the
    Flight Recorder audit trail (Fase A) to this conversation. None is
    tolerated (audited_tool_call/get_recorder just no-op / are never
    reached) so this stays optional for any caller that hasn't been
    updated, not just the live one in app.py."""
    conversation: List[Dict] = [{"role": "system", "content": _build_system_prompt(mode)}]
    conversation += [m for m in messages if m.get("role") != "system"]

    # Cartographer auto-injection (Fase D.2) -- the one genuinely new piece
    # of context-assembly plumbing in this whole module (confirmed: no
    # automatic memory/skill injection precedent exists anywhere else in
    # this codebase, everything else is on-demand via a tool call). Behind
    # its own sub-flag, separate from D.1's search_map tool, specifically
    # so it can be disabled without losing the on-demand fallback if it
    # ever misbehaves. Queried once per turn (not per round) against the
    # turn's own last user message -- that doesn't change across the tool
    # loop within one turn.
    if cartographer_auto_inject_enabled():
        try:
            last_user_for_map = next(
                (m["content"] for m in reversed(messages) if m.get("role") == "user"), ""
            )
            active_project = get_active_project_path()
            # looks_like_codebase_query gate: confirmed live, without it a
            # bare "hi" got the map injected anyway (query_map never
            # returns empty for a non-empty corpus by design) and the
            # model replied about "the Cartographer map" instead of just
            # greeting back.
            if active_project and looks_like_codebase_query(last_user_for_map):
                # 6, not 3: each MAP/*.md is one whole file's summary (see
                # build_bm25_index), so top_k also caps how many distinct
                # files a broad "what's in this project" question can ever
                # surface. Confirmed live on a real 6-file test project --
                # 3 silently left half the files out of the answer with no
                # sign anything was missing. Still small enough not to
                # bloat context on a real, larger codebase.
                map_results = query_map(active_project, last_user_for_map, top_k=6)
                if map_results:
                    map_context = "\n\n---\n\n".join(r["text"] for r in map_results)
                    conversation.append({"role": "system", "content": f"[CARTOGRAPHER MAP]: {map_context}"})
        except Exception as e:
            logger.warning("Cartographer auto-injection failed (turn proceeds without it): %s", e)

    last_executed_call: Optional[tuple] = None
    consecutive_repeats = 0
    unmatched_tool_retries = 0
    # Scoped to this one turn only -- not persisted to disk or across
    # separate chat messages, see tools.py::render_todo_action's docstring.
    todo_list: List[Dict] = []

    # Cartographer's idle-detection signal (Fase D) -- published
    # unconditionally, not gated behind any Cartographer flag, since the
    # worker itself already checks cartographer_enabled() before ever
    # acting on it; publishing costs nothing when there's no subscriber.
    from core.event_bus import bus
    bus.publish("chat_turn_start", {"session_id": session_id})

    _audit = audit_enabled() and bool(session_id)
    if _audit:
        get_recorder(session_id).append("turn_start", {"mode": mode}, actor=owner or "unknown")
    # Set right before the two `return` sites below (disconnect); every
    # other exit (break, or the for loop running out of rounds) leaves this
    # at "completed" -- see the try/finally right after the round loop,
    # which guarantees turn_end is written on every exit path, including
    # cancellation (the specific case the try/finally exists to cover).
    _turn_reason = "completed"
    # TTFT (Fase E metric): logged once, the first time ANY token (content
    # or reasoning) is actually yielded this turn -- not per round. This is
    # the one new audit entry type Fase E needed that wasn't already a
    # byproduct of Fase A's tool/confirm-gate logging (raw token deltas
    # themselves are deliberately never logged, one entry per token would
    # defeat the point of a sparse audit trail).
    _first_token_logged = False

    try:
        for round_num in range(1, MAX_ROUNDS + 1):
            last_user_message = next(
                (m["content"] for m in reversed(conversation) if m.get("role") == "user"), ""
            )

            full_text = ""
            token_gen = _generate_with_retry(model, conversation, max_tokens, temperature, last_user_message)
            # Fetches run as a standalone Task, not a bare `await
            # token_gen.__anext__()` wrapped in asyncio.wait_for: wait_for
            # CANCELS its awaitable on timeout, and cancelling an async
            # generator's __anext__() mid-flight corrupts the generator --
            # confirmed directly, the very first version of this idle-poll
            # (wait_for around __anext__() on every 1s tick) made every
            # response come back completely empty, just a bare [DONE], because
            # prefill alone commonly runs past 1s and the timeout fired mid-
            # prefill every time. asyncio.wait() below only OBSERVES whether
            # the task finished within the timeout; the task itself is left
            # running (and re-awaited next loop iteration) unless a real
            # disconnect is confirmed and cancellation is actually intended.
            next_task = asyncio.ensure_future(token_gen.__anext__())
            try:
                token_count = 0
                while True:
                    done, _ = await asyncio.wait({next_task}, timeout=1.0)
                    if next_task not in done:
                        if request is not None and await request.is_disconnected():
                            await _cancel_and_close(next_task, token_gen)
                            _turn_reason = "disconnected"
                            return
                        continue
                    try:
                        kind, text = next_task.result()
                    except StopAsyncIteration:
                        break
                    next_task = asyncio.ensure_future(token_gen.__anext__())
                    if kind == "reasoning":
                        # Never touches full_text -- parse_tool_call/
                        # find_unmatched_tool_attempt must only ever see real
                        # content, not a model's internal scratch reasoning
                        # (which routinely contains stray ``` sequences that
                        # would otherwise get misread as an attempted tool
                        # call). Surfaced as its own SSE event instead of a
                        # delta so the client can show it as live "thinking"
                        # activity distinct from the actual reply -- see
                        # chat_provider.dart's 'reasoning_delta' handling.
                        if not _first_token_logged:
                            _first_token_logged = True
                            if _audit:
                                get_recorder(session_id).append("first_token", {}, actor="system")
                        yield _sse_event("reasoning_delta", {"text": text})
                        token_count += 1
                        continue
                    if not _first_token_logged:
                        _first_token_logged = True
                        if _audit:
                            get_recorder(session_id).append("first_token", {}, actor="system")
                    full_text += text
                    yield _sse_delta(text)
                    token_count += 1
                    # Also checked here, not just on the idle-wait above: once
                    # tokens start flowing, they can arrive faster than 1/sec
                    # and the not-done-within-1s branch above would rarely
                    # fire. Every 20, not every token -- checking on every
                    # single one during VTE's own earlier streaming rewrite
                    # turned out to be a real ~20% throughput bug from over-
                    # frequent disconnect polling (see vte/server/
                    # http_server.py's sse_stream history); same risk applies
                    # to calling is_disconnected() here.
                    if request is not None and token_count % 20 == 0 and await request.is_disconnected():
                        await _cancel_and_close(next_task, token_gen)
                        _turn_reason = "disconnected"
                        return
            except Exception as e:
                next_task.cancel()
                logger.error("VTE generation failed: %s", e)
                yield f'event: error\ndata: {json.dumps({"error": str(e), "status": 500})}\n\n'
                _turn_reason = "error"
                return

            tool_call = parse_tool_call(full_text)
            if not tool_call:
                bad_tag = find_unmatched_tool_attempt(full_text)
                if bad_tag and unmatched_tool_retries < MAX_UNMATCHED_TOOL_RETRIES:
                    unmatched_tool_retries += 1
                    conversation.append({"role": "assistant", "content": full_text})
                    conversation.append({
                        "role": "user",
                        "content": (
                            f"`{bad_tag}` isn't a real tool -- nothing ran. Available tools: "
                            f"{', '.join(sorted(ALL_TOOL_NAMES))}. Pick one of these exact names, "
                            "or reply in plain text if no tool is actually needed."
                        ),
                    })
                    continue
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
                # assistant_text here for the same reason confirm_tool/
                # browser_action carry it: the client renders `plan` in its own
                # dedicated panel (PlanPanel), not the chat bubble, so it must
                # persist THIS (not its raw streamed buffer, which still has
                # the ```write_plan fence and everything after it) as the
                # turn's history, or the next round's context claims the model
                # said things it never actually said in the kept history.
                yield _sse_event("plan_update", {"plan": plan_text, "round": round_num, "assistant_text": assistant_text})
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
                yield _sse_event(
                    "browser_action",
                    {"tool": tool_name, "content": tool_content, "round": round_num, "assistant_text": assistant_text},
                )
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
                #
                # assistant_text (not the client's own raw streamed buffer) is
                # what the client must persist as this turn's history: a model
                # that bundles two file writes into one response (a real,
                # observed failure mode -- small models don't reliably follow
                # "one tool call per response") only ever gets the FIRST one
                # turned into a real tool call here; the second fenced block was
                # never executed or confirmed. strip_tool_call already cuts the
                # unexecuted second block out for exactly the reason documented
                # on strip_tool_call itself (a model reading its own past turn
                # full of tool calls it never got results for hallucinates/
                # merges content next round). That protection only holds if the
                # client saves THIS text, not its own unstripped buffer.
                if _audit:
                    entry = get_recorder(session_id).append(
                        "confirm_request", {"tool": tool_name, "round": round_num}, actor=owner or "unknown",
                    )
                    yield _sse_event("audit_entry", {"entry": entry})
                yield _sse_event(
                    "confirm_tool",
                    {"tool": tool_name, "content": tool_content, "round": round_num, "assistant_text": assistant_text},
                )
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
            _new_entries: List[Dict] = []
            result = await audited_tool_call(
                session_id, tool_name, tool_content, owner, handler, on_entry=_new_entries.append,
            )
            for _entry in _new_entries:
                yield _sse_event("audit_entry", {"entry": _entry})
            yield _sse_event("tool_output", {"tool": tool_name, "result": result, "round": round_num})
            last_executed_call = current_call

            # The visible reply keeps only the prose before/after the tool
            # fence; the fence itself becomes the assistant's tool-call turn
            # in the conversation history, followed by the tool's result as a
            # user-role message so the next round can react to it.
            conversation.append({"role": "assistant", "content": assistant_text})
            result_text = result.get("output") or result.get("content") or result.get("error") or json.dumps(result)
            # bash returns a non-zero exit_code as part of a normal {"output":
            # ..., "exit_code": N} result (a command that ran and failed, e.g.
            # `mv` hitting "cannot move X to a subdirectory of itself", isn't a
            # Python-level exception, so it never goes through the "error" key
            # above) -- the failure was always IN result_text's prose, but nothing
            # marked it as a failure. Confirmed directly: a real mv error came
            # back with exit_code 1 and full stderr text, and the model still
            # replied "The files have been moved" and moved on, then repeated
            # the same broken mkdir+mv pattern rather than reacting to it,
            # something a smaller/quantized model skims past far more easily
            # than a human would. An explicit marker in front of the same text
            # doesn't change what happened, just makes it unmissable.
            exit_code = result.get("exit_code")
            if isinstance(exit_code, int) and exit_code != 0:
                result_text = f"[FALHOU - exit code {exit_code}]\n{result_text}"
            conversation.append({"role": "user", "content": f"[{tool_name} result]\n{result_text}"})

            if round_num == MAX_ROUNDS:
                yield _sse_event("rounds_exhausted", {"max_rounds": MAX_ROUNDS})
    finally:
        if _audit:
            get_recorder(session_id).append("turn_end", {"reason": _turn_reason}, actor=owner or "unknown")
        bus.publish("chat_turn_end", {"session_id": session_id, "reason": _turn_reason})

    yield "data: [DONE]\n\n"
