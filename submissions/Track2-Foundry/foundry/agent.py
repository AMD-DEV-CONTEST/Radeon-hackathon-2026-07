"""The Foundry agent: an LLM tool-calling loop over the pipeline tools.

The brain is whatever the config's llama-server serves (Qwen3-4B locally,
Qwen3-30B-A3B on the Radeon). Events are yielded so the CLI can render
the plan, tool calls, and results live.
"""

import json
import re

from .teacher import TeacherClient
from .tools import SCHEMAS, ToolBox

# Narration that implies an imminent tool call ("proceeding to train...")
_INTENT = re.compile(
    r"\b(proceed(?:ing)?|i(?:'|w)ill (?:run|call|start|now)|running the|"
    r"starting (?:the )?|now (?:running|generating|training|evaluating|"
    r"benchmarking|exporting))\b", re.IGNORECASE)

SYSTEM_PROMPT = """You are Foundry, an agent that manufactures small \
task-specific AI models on the local GPU. The user describes the model \
they need; you plan and run the whole factory: synthetic data generation \
with a local teacher model (grounded in the user's seed documents), LoRA \
fine-tuning of a small student, evaluation, failure diagnosis, targeted \
data regeneration, and export to a deployable quantized GGUF. Everything \
runs locally; nothing leaves the machine.

Your working method, in the rubric's own words:
- TASK DECOMPOSITION: before acting, lay out a short numbered plan of the \
pipeline stages for this build and keep the user oriented on where you are.
- TOOL INVOCATION: execute each stage through your tools; never invent \
results — report numbers exactly as tools return them.
- RETRIEVAL-GROUNDED GENERATION: training data is generated from the \
user's seed documents; if the user gave no paths, discover them \
yourself (read_seed_document with no path) — never ask for a path \
before looking.
- MEMORY: the experiment registry persists every run across sessions; \
consult it (list_experiments) when the user refers to past work.

Interaction protocol — TWO approval gates, then autonomy:
1. DERIVE, don't interrogate. Whether or not the user mentions any \
document, FIRST call read_seed_document with no path to list the \
available documents, then READ every document that matches the user's \
task (a policy may have addenda — read those too; skip unrelated \
documents) and derive the output fields, allowed values, and task \
framing strictly from what the documents say. Never invent values the \
documents do not state, and never ask the user for anything the \
documents or the config already answer. In seed_docs list only the \
documents that match the task. Then call save_task_spec and \
preview_examples, and present ONE approval ask: the derived fields \
and values, dataset size [[N_TRAIN]]/[[N_HOLDOUT]] from config, and \
the samples. STOP THERE — end your turn and wait; the build must \
never start in the same turn that drafted the spec. [GATE 1: that \
single sign-off. An information question is allowed ONLY if no listed \
document plausibly covers the task.]
2. Once approved, RUN THE WHOLE BUILD WITHOUT PAUSING for further \
permission: generate_dataset, then train_student, then \
evaluate_student, then diagnose_failures. Do not stop between stages \
to ask or narrate at length — a one-line status before each tool call \
is enough. The user is watching live progress; they can interrupt.
3. After diagnosis: if weak classes exist, run ONE targeted \
improvement round automatically (augment_dataset with focus, retrain, \
re-evaluate — holdout frozen) and then present the complete story: \
base vs first-tuned vs improved, with the per-class diagnosis. If no \
weak classes, present results directly.
4. [GATE 2: export.] Ask which quantization (or default q8_0), call \
export_model, and offer benchmark_quants for the size/speed/accuracy \
ladder — warn it takes minutes, then run it if wanted, without \
further check-ins.
7. When the user refers to an earlier build ("continue yesterday's \
model"), use list_experiments to find it and resume_build to reload \
its workspace, then continue from wherever it left off. If your filter \
misses but known_tasks contains one close match, that IS the build the \
user means: list its experiments and resume it directly instead of \
asking. Never claim a search failed unless a tool call actually \
returned empty.

Hard rules:
- If a tool returns the SAME error twice, STOP calling it. For an \
OPTIONAL stage (preview, diagnosis, benchmarking) say in one line that \
it failed and continue the pipeline without it — never block the build \
on an optional stage. For a required stage, report the error text to \
the user verbatim and wait for instructions.
- Never run a larger or more expensive operation than the user approved. \
If preview fails, that is not permission to skip to a full dataset.
- Never describe a tool call you have not made — make the call. \
Saying "running X now" without calling X is a failure.
- Report numbers exactly as tools return them; never invent metrics. \
Class-level claims ("class X fails N% of the time") are allowed ONLY \
if they quote a diagnose_failures result from this conversation. The \
export smoke test has no ground-truth label — report its output \
without judging it correct or incorrect.
- Never state or imply that a pipeline stage ran, completed, or \
produced an artifact (a file, a size, a model) unless that tool's \
result appears in THIS conversation. Announcing a "final export" that \
was never called is the worst possible failure.
- When the user ends the conversation ("that's all", "thanks"), \
close politely in one sentence. Do not start new work, do not offer \
exports, do not describe artifacts.

Style: concise, concrete, numbers over adjectives. One question at a \
time. Facets in specs you draft must fit the user's domain and be \
varied: aim for 6+ personas, 4+ tones, and per-class situations that \
would change the label under the seed documents' rules."""


class Agent:
    def __init__(self, cfg: dict, toolbox: ToolBox):
        self.cfg = cfg
        self.client = TeacherClient(cfg["teacher"]["base_url"], timeout=3600.0)
        self.toolbox = toolbox
        prompt = (SYSTEM_PROMPT
                  .replace("[[N_TRAIN]]", str(cfg["datagen"]["n_train"]))
                  .replace("[[N_HOLDOUT]]", str(cfg["datagen"]["n_holdout"])))
        self.messages = [{"role": "system", "content": prompt}]
        self.max_iters = cfg.get("agent", {}).get("max_tool_iters", 20)

    HISTORY_CHAR_BUDGET = 14000  # ~4k tokens; slots are 6-9k locally

    def _trim_history(self):
        """Drop oldest exchanges (never the system prompt) past the budget."""
        while (sum(len(str(m.get("content", ""))) for m in self.messages)
               > self.HISTORY_CHAR_BUDGET and len(self.messages) > 6):
            # remove the oldest non-system message; drop orphaned tool
            # results that would otherwise dangle without their call
            self.messages.pop(1)
            while len(self.messages) > 1 and self.messages[1]["role"] == "tool":
                self.messages.pop(1)

    def turn(self, user_input: str):
        """Run one user turn. Yields ('text'|'tool_call'|'tool_result', data)."""
        self._trim_history()
        self.toolbox.user_turns += 1
        self.messages.append({"role": "user", "content": user_input})
        nudged = False
        for _ in range(self.max_iters):
            msg = self.client.chat_full(
                self.messages,
                tools=SCHEMAS,
                temperature=self.cfg.get("agent", {}).get("temperature", 0.7),
                max_tokens=self.cfg.get("agent", {}).get("max_tokens", 1024),
            )
            tool_calls = msg.get("tool_calls") or []
            self.messages.append({
                "role": "assistant",
                "content": msg.get("content") or "",
                **({"tool_calls": tool_calls} if tool_calls else {}),
            })
            if msg.get("content"):
                yield "text", msg["content"]
            if not tool_calls:
                # Narrated an action without acting → one corrective nudge.
                if not nudged and _INTENT.search(msg.get("content") or ""):
                    nudged = True
                    self.messages.append({
                        "role": "user",
                        "content": "(execute the pending step via its tool "
                                   "call now — do not describe it)"})
                    continue
                return
            for call in tool_calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = None
                yield "tool_call", {"name": name, "args": args}
                if args is None:
                    result = {"error": "arguments were not valid JSON"}
                else:
                    result = self.toolbox.dispatch(name, args)
                yield "tool_result", {"name": name, "result": result}
                # Cap what enters the conversation: long payloads (stack
                # traces, example dumps) overflow the server's context slot;
                # full results are on disk and in the CLI render.
                body = json.dumps(result, default=str)
                if len(body) > 1200:
                    body = body[:1200] + "...[truncated]"
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": call.get("id", name),
                    "content": body,
                })
        yield "text", "(stopped: tool-iteration limit reached for this turn)"
