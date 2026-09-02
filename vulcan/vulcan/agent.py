"""ReAct-style agent loop with JSON tool calls.

Uses a plain-text JSON protocol instead of native tool-calling so the same
loop works on every backend (Ollama, vLLM, llama.cpp) regardless of
tool-call support.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import tools
from .config import Config
from .llm import LLM
from .memory import Memory
from .rag import Index

SYSTEM = """You are Vulcan, a local developer-productivity agent. All inference runs on-device; never claim to access the internet.

You work in a loop. On each turn reply with EXACTLY ONE JSON object, nothing else:
  {"thought": "...", "tool": "<name>", "args": {...}}
or, when you have the answer:
  {"thought": "...", "final": "<answer for the user, cite files as path:line>"}

{planning}
Strategy: start with search_code, it is almost always the fastest route. Answer as soon as you have enough evidence; do not keep exploring.

Tools:
- search_code {"query": str}            semantic search over the indexed codebase
- read_file   {"path": str, "start": int, "end": int}
- list_dir    {"path": str}
- grep        {"pattern": str, "glob": str}
- run_cmd     {"command": str}          allowlisted: tests, linters, git
- write_file  {"path": str, "content": str}
- remember    {"note": str}             persist a durable fact for future sessions

Prior session notes:
{memory}
"""

PLANNING = """If the request has more than one part, make your FIRST reply a plan instead:
  {"thought": "...", "plan": ["first part", "second part"]}
One plan per request, at most 5 parts, and only when there is genuinely more
than one thing to find out. A single question needs no plan; go straight to a
tool. After planning, work through the parts and answer all of them in `final`.
"""

#: A search observation is the largest thing the agent ever reads. Six full
#: chunks blew a 4096-token window on their own, so both the count and each
#: hit are bounded; the model can always read_file for the full text.
SEARCH_HITS = 4
SEARCH_HIT_CHARS = 900

#: How much of the conversation so far is carried into the next turn. Without
#: any, `vulcan chat` was multi-turn in name only: each question started from an
#: empty conversation, so "what about the other one?" had no referent. Bounded
#: because an unbounded history is the same context overflow in slow motion:
#: oldest exchanges are dropped first, and tool observations are never kept.
HISTORY_CHARS = 4000

JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class Agent:
    def __init__(self, cfg: Config, root: Path, index_name: str = "default"):
        self.cfg = cfg
        self.root = root
        self.llm = LLM(cfg)
        self.index = Index(cfg, self.llm, index_name)
        self.memory = Memory(cfg, project=str(root))
        #: Completed turns only: the question and the answer, never the tool
        #: chatter in between, which is what made a single turn overflow.
        self.history: list[dict] = []

    def _dispatch(self, tool: str, args: dict) -> str:
        if tool == "search_code":
            hits = self.index.search(args.get("query", ""))
            # Every other tool clips its output; this one did not, and six
            # 60-line chunks is a single observation big enough to exceed a
            # 4096-token context on its own. That surfaced as an opaque 400
            # from the backend part way through a session.
            parts = [
                f"{h['path']}:{h['start']}-{h['end']} (score {h['score']:.2f})\n"
                + tools.clip(h["text"], SEARCH_HIT_CHARS)
                for h in hits[:SEARCH_HITS]
            ]
            return "\n---\n".join(parts) or "no results"
        if tool == "read_file":
            return tools.read_file(self.root, args.get("path", ""), args.get("start", 1), args.get("end"))
        if tool == "list_dir":
            return tools.list_dir(self.root, args.get("path", "."))
        if tool == "grep":
            return tools.grep(self.root, args.get("pattern", ""), args.get("glob", "**/*"))
        if tool == "run_cmd":
            return tools.run_cmd(self.root, args.get("command", ""))
        if tool == "write_file":
            return tools.write_file(self.root, args.get("path", ""), args.get("content", ""))
        if tool == "remember":
            self.memory.remember(args.get("note", ""))
            return "noted"
        return f"ERROR: unknown tool {tool}"

    def run(self, task: str, on_step=None) -> str:
        notes = "\n".join(f"- {n}" for n in self.memory.recall()) or "(none)"
        messages = [
            {"role": "system", "content": SYSTEM.replace("{memory}", notes)
                                            .replace("{planning}", PLANNING if self.cfg.plan else "")},
            *self.history,
            {"role": "user", "content": task},
        ]
        plan: list[str] = []
        for _ in range(self.cfg.max_steps):
            reply = self.llm.chat(messages, stream=True).text
            match = JSON_RE.search(reply)
            if not match:
                messages.append({"role": "assistant", "content": reply})
                messages.append({"role": "user", "content": "Reply with exactly one JSON object per the protocol."})
                continue
            try:
                step = json.loads(match.group())
            except json.JSONDecodeError as e:
                messages.append({"role": "assistant", "content": reply})
                messages.append({"role": "user", "content": f"Invalid JSON ({e}). Retry."})
                continue
            if "plan" in step and not plan:
                plan = [str(p) for p in step["plan"]][:5]
                if on_step:
                    on_step(step)
                messages.append({"role": "assistant", "content": match.group()})
                messages.append({"role": "user", "content": "Plan noted. Begin the first part."})
                continue
            if "plan" in step:
                # A second plan means the model is re-planning instead of
                # working, which burns steps and never terminates.
                messages.append({"role": "assistant", "content": match.group()})
                messages.append({"role": "user", "content": "You already planned. Use a tool or give final."})
                continue

            if "tool" not in step and "final" not in step:
                # A reply of just {"thought": ...} used to be dispatched as a
                # tool named "", which answers ERROR: unknown tool. A few of
                # those in a row and the model concludes its tools are broken
                # and gives up, which is what it did: "I cannot proceed because
                # all tools are unavailable."
                messages.append({"role": "assistant", "content": match.group()})
                messages.append({"role": "user", "content":
                                 "That reply had no `tool` and no `final`. "
                                 "Reply with one JSON object containing either."})
                continue

            if on_step:
                on_step(step)
            if "final" in step:
                self._remember_turn(task, step["final"])
                return step["final"]
            obs = self._dispatch(step.get("tool", ""), step.get("args", {}))
            messages.append({"role": "assistant", "content": match.group()})
            # The plan is repeated with each observation rather than stated once.
            # Left in the first message alone it scrolls out of attention, and
            # the model answers part one of a three-part question and stops.
            tail = f"\n\nStill to cover: {'; '.join(plan)}" if plan else ""
            messages.append({"role": "user", "content": f"Observation:\n{obs}{tail}"})
        give_up = "Step limit reached without a final answer."
        self._remember_turn(task, give_up)
        return give_up

    def _remember_turn(self, task: str, answer: str) -> None:
        """Keep the exchange for the next turn, oldest dropped first."""
        self.history += [{"role": "user", "content": task},
                         {"role": "assistant", "content": answer}]
        while sum(len(m["content"]) for m in self.history) > HISTORY_CHARS and len(self.history) > 2:
            del self.history[:2]
