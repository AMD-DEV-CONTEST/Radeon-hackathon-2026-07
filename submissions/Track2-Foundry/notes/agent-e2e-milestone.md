# Agent E2E passed July 17: conversation → deployed GGUF, no human in the pipeline

One-liner: the Foundry agent (Qwen3-4B brain via llama-server tool
calling) drove the full factory from one natural-language request —
spec drafting, preview, datagen (71 ex, 98.6% acceptance), LoRA train,
eval (base 0.083 → tuned 0.667 exact match), failure diagnosis that
correctly flagged the weak class and proposed focus regeneration,
GGUF export + smoke — with the registry recording all four stages.

Run: runs/build-northbeam-support-ticket-triage-20260717-115730,
transcript reproducible via chat.py --script (see git history of this
session's command). GPU orchestration (teacher stop/start around
train/eval/export on 8GB) worked without losing conversation state.

Lessons burned in:
- **Agent-drafted specs are a validation boundary**, same class as
  teacher JSON: the 4B wrote input_length as {"min":10,"max":500}
  where code expected [lo,hi]; dict unpacking yielded string keys and
  a TypeError three calls later. Fix: _normalize_length() accepts
  list/dict/string-numbers; all tool args get boundary casts
  (int()/float()/str()).
- **Never catch TypeError as "bad tool arguments"** — in-tool
  TypeErrors got mislabeled as argument errors, so the agent retried a
  correct call into a doom loop. Dispatch now reports the raw
  exception type + message; the agent's prompt orders a hard stop
  after the same error twice.
- Windows console is cp1252; the agent emits emoji — chat.py forces
  sys.stdout utf-8.
- 4B-brain quirks to expect (should improve on the 30B): sometimes
  narrates an action ("Generating dataset...") without emitting the
  tool call until the next user nudge; asserted the smoke test was
  "correct" without ground truth (prompt now forbids judging it).
