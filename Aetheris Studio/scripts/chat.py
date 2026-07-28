"""
Aetheris terminal chat client. Talks to the same backend (app.py) and the
same agent loop (core/utils/agent.py::stream_agent) the Flutter UI uses,
not a separate or lighter agent, just a different front end for it.
Works identically on Windows and Linux (pure Python + requests), which
matters since the Flutter UI itself only ships a Windows build today.

Usage:
    1. Start the backend once, in its own terminal:
         python app.py
    2. In another terminal, from this same folder:
         python scripts/chat.py [project_path]

`project_path` (optional) is the folder the agent's file/git/search tools
operate on, defaults to the current directory if omitted. Type your
message and press Enter; Ctrl+C or an empty message to quit.
"""
import json
import os
import sys

import requests

BASE_URL = "http://127.0.0.1:8001"


def _load_token() -> str:
    token = os.environ.get("AETHERIS_INTERNAL_TOKEN")
    if token:
        return token
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("AETHERIS_INTERNAL_TOKEN="):
                    return line.strip().split("=", 1)[1].strip("\"'")
    raise SystemExit(
        "Could not find AETHERIS_INTERNAL_TOKEN. Start the backend once with "
        "`python app.py` first (it writes .env on first boot), then re-run this script."
    )


def _iter_sse_events(response):
    for raw_line in response.iter_lines(decode_unicode=True):
        if not raw_line or not raw_line.startswith("data: "):
            continue
        payload = raw_line[len("data: "):]
        if payload == "[DONE]":
            return
        yield json.loads(payload)


def send_turn(session, headers, history, mode="builder"):
    """Streams one assistant turn (including any tool rounds) and returns
    the plain-text reply to append to history. Tool output is echoed so you
    can see what the agent actually did, not just its final words.

    A turn's deltas are the concatenation of EVERY round's raw text,
    including the fenced tool-call blocks that already ran, e.g.
    "```read_file\nfoo.py\n```\n\nfoo.py contains..." for a single-tool
    turn. Storing that whole blob as the assistant's history entry feeds
    the model its own past tool-call syntax on the next turn, which this
    project's own backend explicitly avoids for the same reason
    (core/utils/tools.py::strip_tool_call's docstring: models that see
    their own unresolved tool calls in history tend to hallucinate or
    merge content next round). So `final_answer` is tracked separately
    and reset every time a tool-round boundary event fires (tool_start/
    tool_output/confirm_tool); only the text streamed AFTER the last such
    event, the actual final answer, gets returned for history."""
    resp = session.post(
        f"{BASE_URL}/v1/chat/completions/stream",
        headers=headers,
        json={"messages": history, "mode": mode, "temperature": 0.3, "max_tokens": 4096},
        stream=True,
    )
    resp.raise_for_status()

    final_answer = ""
    for event in _iter_sse_events(resp):
        if "delta" in event:
            print(event["delta"], end="", flush=True)
            final_answer += event["delta"]
            continue

        etype = event.get("type")
        if etype == "tool_start":
            print(f"\n  [tool: {event['tool']}]", flush=True)
            final_answer = ""
        elif etype == "tool_output":
            result = event.get("result", {})
            # Tool handlers don't share one key name for their payload:
            # most use "output", read_file's success path uses "content",
            # any failure uses "error" (core/utils/tools.py).
            out = result.get("output") or result.get("content") or result.get("error") or ""
            print(f"  -> {out[:300]}{'...' if len(out) > 300 else ''}", flush=True)
            final_answer = ""
        elif etype == "confirm_tool":
            # The server pauses here (this SSE response ends right after
            # this event, nothing more will arrive on it); on approval, feed
            # the real result back as a hidden follow-up turn so the agent
            # can actually acknowledge what happened, same as the Flutter
            # client's respondToolConfirm -> sendMessage(isHidden: true).
            executed, result_text = _handle_confirm(session, headers, event)
            if executed:
                history.append({"role": "user", "content": f"[{event['tool']} result]\n{result_text}"})
                return send_turn(session, headers, history, mode=mode)
            final_answer = ""
        elif etype == "plan_update":
            print(f"\n  [plan]\n{event['plan']}\n", flush=True)
        elif etype == "browser_action":
            print(f"\n  [browser tool '{event['tool']}' requested, not available from this terminal client, only in the Flutter UI's embedded browser]", flush=True)
        elif etype == "rounds_exhausted":
            print("\n  [stopped: too many tool rounds without a final answer]", flush=True)
    print()
    return final_answer.strip()


def _handle_confirm(session, headers, event):
    """write_file/edit_file/risky bash all pause here and wait for a real
    y/n, the same gate the Flutter UI's confirm dialog enforces, just typed
    instead of clicked. Returns (executed, result_text)."""
    tool, content = event["tool"], event["content"]
    print(f"\n  [confirm required] {tool}:\n{content}\n")
    answer = input("  Approve? [y/N] ").strip().lower()
    if answer != "y":
        print("  [skipped]")
        return False, ""
    exec_resp = session.post(
        f"{BASE_URL}/api/tools/execute", headers=headers,
        json={"tool": tool, "content": content},
    )
    exec_resp.raise_for_status()
    result = exec_resp.json()
    print(f"  -> {result}")
    return True, result.get("output", str(result))


def main():
    token = _load_token()
    headers = {"X-Internal-Token": token, "Content-Type": "application/json"}
    session = requests.Session()

    try:
        session.get(f"{BASE_URL}/", timeout=3)
    except requests.exceptions.ConnectionError:
        raise SystemExit(
            "Aetheris backend isn't running. Start it first, in its own terminal:\n"
            "    python app.py"
        )

    project_path = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    set_resp = session.post(f"{BASE_URL}/api/project-path", headers=headers, json={"path": project_path})
    if set_resp.ok:
        print(f"Project: {set_resp.json()['path']}")
    else:
        print(f"(could not set project path to {project_path!r}: {set_resp.text})")

    print("Aetheris terminal chat. Empty message or Ctrl+C to quit.\n")

    history = []
    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            break

        history.append({"role": "user", "content": user_input})
        print("aetheris> ", end="", flush=True)
        reply = send_turn(session, headers, history)
        history.append({"role": "assistant", "content": reply})


if __name__ == "__main__":
    main()
