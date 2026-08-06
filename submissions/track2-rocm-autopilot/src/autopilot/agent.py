"""The Autopilot loop: Gemma 4 optimizes its own deployment.

Native function calling via the vLLM OpenAI-compatible endpoint
(--tool-call-parser gemma4). Fallback: if the server returns no parsed
tool_calls, we ask for a bare-JSON action and parse it ourselves -
same dispatch path, so the demo cannot die on a parser edge case.
"""

from __future__ import annotations

import argparse
import json
import os

import requests

from autopilot.journal import Journal
from autopilot.tools import TOOL_SCHEMAS, Ctx, dispatch

BRAIN_MODEL = os.environ.get("BRAIN_MODEL", "google/gemma-4-26B-A4B-it")

SYSTEM_PROMPT = """You are Autopilot, an inference-optimization agent. You are the deployed \
model optimizing your own vLLM deployment on a single GPU: every benchmark you run measures \
the very server that produces your reasoning.

Objective: maximize tokens/s subject to TTFT <= 500 ms. Report joules/token as the \
efficiency axis: energy matters as much as speed.

Rules:
- Act ONLY through the provided tools, ONE call at a time.
- Before each call, explain your diagnosis in 2-3 sentences grounded in the previous \
metrics (memory-bound vs latency-bound, queueing delay, cache behavior, power/perf tradeoff).
- Start by probing the aggressive end of the configuration range, then adapt from what fails.
- If a result violates the TTFT constraint or a guardrail rejects your action, diagnose \
why and recover with a corrected action.
- Use search_web or search_papers when you need external knowledge about a surprising result.
- When further gains look below ~3%, call report_done with a summary."""


def chat(base_url: str, messages: list, tools: list) -> dict:
    payload = {"model": BRAIN_MODEL, "messages": messages,
               "temperature": 0.4, "max_tokens": 1024}
    if os.environ.get("BRAIN_DISABLE_THINKING") == "1":
        # Reasoning-tuned brains (Qwen3) think for minutes per decision by
        # default; the loop needs decisions, not essays.
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    if tools:  # vLLM rejects tool_choice with an empty tools list
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    r = requests.post(f"{base_url}/v1/chat/completions", json=payload, timeout=300)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]


def _json_fallback(base_url: str, messages: list) -> dict | None:
    """Ask for a bare-JSON action when native tool parsing yields nothing."""
    forced = messages + [{"role": "user", "content":
        'Reply ONLY with JSON: {"tool": "<name>", "args": {...}}: no prose.'}]
    msg = chat(base_url, forced, tools=[])
    text = (msg.get("content") or "").strip().strip("`")
    text = text[text.find("{"): text.rfind("}") + 1]
    try:
        obj = json.loads(text)
        return {"name": obj["tool"], "args": obj.get("args", {})}
    except Exception:
        return None


def run_loop(max_iters: int = 8, base_url: str = "http://localhost:8000",
             journal: Journal | None = None) -> None:
    journal = journal or Journal()
    ctx = Ctx(base_url=base_url, journal=journal)
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content":
                 "The deployment is live. Begin optimizing. Previous best runs, if any, "
                 "are in your tool results. Explain, then act."}]

    for i in range(1, max_iters + 1):
        msg = chat(base_url, messages, TOOL_SCHEMAS)
        # gemma4's reasoning parser routes thinking to reasoning_content
        reasoning = ((msg.get("reasoning_content") or "") + "\n" + (msg.get("content") or "")).strip()
        calls = msg.get("tool_calls") or []

        if calls:
            call = calls[0]
            name = call["function"]["name"]
            args = json.loads(call["function"]["arguments"] or "{}")
            messages.append({"role": "assistant", "content": reasoning,
                             "tool_calls": [call]})
        else:
            fb = _json_fallback(base_url, messages + [{"role": "assistant", "content": reasoning}])
            if fb is None:
                journal.add_note(f"[iter {i}] no action parsed; reasoning: {reasoning[:300]}")
                continue
            name, args = fb["name"], fb["args"]
            messages.append({"role": "assistant", "content": reasoning})

        if not reasoning and name != "report_done":
            # the model acted silently: ask it to voice the diagnosis it acted on
            probe = chat(base_url, messages + [{"role": "user", "content":
                f"In 2-3 sentences, state the diagnosis behind your {name} call "
                "(grounded in the previous metrics). Reply with prose only."}], tools=[])
            reasoning = ((probe.get("reasoning_content") or "") + " " + (probe.get("content") or "")).strip()

        print(f"\n=== iter {i} · {name}({json.dumps(args)})\n{reasoning}\n")

        # Mark benchmark as "running" on the live dashboard before executing
        if name == "run_benchmark":
            run_label = f"agent-iter-{sum(1 for r in journal.runs if str(r.get('label','')).startswith('agent-iter')) + 1}"
            journal.push_live_running(run_label, reasoning)

        result = dispatch(name, args, ctx)

        if name == "run_benchmark" and "error" not in json.loads(result):
            journal.add_run(json.loads(result), reasoning)
        else:
            journal.add_note(f"[iter {i}] {name}({json.dumps(args)}) -> {result[:400]} | {reasoning[:300]}")

        nudge = "\n\nBefore your next tool call, explain your diagnosis of THIS result in 2-3 sentences."
        if calls:
            messages.append({"role": "tool", "tool_call_id": call.get("id", "0"),
                             "content": result + nudge})
        else:
            messages.append({"role": "user", "content": f"Tool result: {result}{nudge}"})

        if name == "report_done":
            print(f"Agent done: {json.loads(result).get('summary', '')}")
            break

    print(f"\nLeaderboard:\n{json.dumps(journal.leaderboard(), indent=1)}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--iters", type=int, default=8)
    p.add_argument("--base-url", default="http://localhost:8000")
    args = p.parse_args()
    run_loop(max_iters=args.iters, base_url=args.base_url)
