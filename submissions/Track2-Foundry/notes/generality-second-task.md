# Generality proven July 17: second domain built with zero code changes

One-liner: from one conversation and a never-before-seen seed policy
(seeds/expense_policy.md), the agent drafted its own spec (its own
field names: routing_decision + spending_category, 4+6 enum values,
balance on routing), generated data, trained, evaluated, and exported a
GGUF — no code or config edits. Foundry is a factory, not a demo.

Run: runs/build-expense_claim_routing-20260717-123236, pilot scale
(54 train / 12 holdout). Eval: base 0.167 → tuned 0.417 exact match;
spending_category 0.917, routing_decision 0.417.

Read on the numbers: routing is genuinely harder than triage — the
policy routes on amount thresholds, receipt presence, and precedence
rules (reject > needs_finance > needs_manager > auto_approve), which a
0.6B student can't absorb from 54 examples. That's not a failure of the
pipeline; it's the demo story for the improvement loop (more data +
focus rounds) and for teacher-scale runs on the Radeon. Expect routing
to climb at 1K examples / 30B teacher labels.

Behavioral flaw caught: the 4B agent asserted class-level weakness
("reject only 33% correct") WITHOUT having called diagnose_failures —
fabricated analysis. Prompt now restricts class-level claims to quoted
diagnose_failures output. Watch for this in every demo rehearsal; it is
the failure mode most likely to embarrass us live.

UPDATE Aug 5 (pre-video hardening, all verified on the 4B stand-in):
- The agent now discovers seed documents itself — no file path in the
  user prompt needed. Two mechanisms, because prompt-only failed twice:
  the read_seed_document list result carries "read before drafting"
  guidance (without it the 4B invented enum values and attributed them
  to the documents), and generate_dataset is code-blocked in the same
  user turn that called save_task_spec (tests/test_approval_gate.py).
  Before the block existed, the 4B ran a full unapproved 50-min build
  from one opening sentence.
- Schema-derivation bias: an opening prompt phrased "who approves it"
  made the model drop the reject queue from the enum (a reject is not
  an approver). Phrase demo openers as "who approves it, or whether
  it's not allowed at all". Check the on-screen confirmation for a
  reject-like value before approving; if missing, asking "what about
  claims that should be rejected?" is a natural on-camera recovery.
- Residual 4B tic: a closing line that claims "Approved. Proceeding"
  and then correctly waits. Cosmetic here; the 30B held real gates in
  all four full-scale runs, but it has NOT run with this prompt yet —
  watch the first live turn.

Cosmetic: chat transcript shows utf-8 mojibake when captured through
PowerShell redirection (console codepage); fine in a real terminal.
Decide the demo UI question (terminal vs thin web view) at week-3 start.
