# Radeon expense-routing take (Aug 5) — live second-domain build, 0.88 exact

One-liner: the video take built the expense-claim router live on the
gfx1100 from a toddler-simple prompt with zero code changes — base
0.24 → tuned 0.88 exact (category 0.98 / routing 0.88, n=100,
json_valid 1.0 both), full pipeline including an autonomous
improvement round. Triage (0.97) stays the headline; this is the
generality/live story. Artifacts: Downloads/radeon-expense-take.tar.gz,
run dir build-expense-classifier-20260805-112259.

Stage sequence (all agent-driven, one approval): datagen 900/100 →
train (3 ep) → eval → augment 100 focus=equipment → retrain →
re-eval → export q8_0 → bench ladder. All registry-verified EXCEPT a
diagnose step: the registry does not log diagnose_failures, so only
the augment focus choice evidences it (and the recording). Spec quirk
found in verification: the routing enum lists needs_finance twice
(5 entries, 4 distinct values) — harmless to eval, worth a validator
dedupe later. Training-set rarity (verified): auto_approve 94/1005,
rejected 10/1005; the 100-claim holdout has ZERO rejected cases, so
the 0.88 never tested that outcome.

Ladder (gfx1100, llama.cpp master built on-instance):
| Quant | MB | tg tok/s | Exact |
|---|---|---|---|
| Q4_K_M | 378 | 305.2 | 0.880 |
| Q5_K_M | 424 | 300.4 | 0.890 |
| Q6_K | 472 | 291.3 | 0.860 |
| Q8_0 | 610 | 270.1 | 0.890 |
| teacher 30B | 17,697 | 112.4 | (labels) |
Teacher tg 112.4 vs July's 110.2 on the same class of build — the
serving numbers reproduce across llama.cpp versions.

Approval gate fired LIVE on the 30B: it attempted generate_dataset in
the spec turn, the code brake blocked it, it apologized and waited.
The prompt-level gate alone would not have held — mechanism beat prose
(see generality-second-task note for the full Aug 5 hardening).

Cold-open audition (9 policy claims vs the served Q4): 6/9 correct.
Systematic residuals, good limitations material for the report:
- auto_approve and rejected are under-learned — balance_field was
  category, so rare ROUTING outcomes stayed rare in 900 examples. The
  improvement round targeted a weak CATEGORY (equipment), not the weak
  routing classes. Lesson: balance (or at least diagnose) on every
  output field, not just one.
- One out-of-enum emission ("category": "parking") — json_valid can be
  1.0 while a value is out of schema; parse_response counts it wrong,
  so eval is honest, but don't claim "always valid labels".
- Correct on nuanced rules: recurring-subscription precedence at $12,
  3+-employee lunch rule, bundle-total-over-$500. The three on-camera
  cold-open claims are these, all verified correct against policy.

Session logistics that cost time (all now fixed or documented):
cloudflared missing from the new image (fetch static binary or use the
Jupyter /proxy/8300/ path), notebook cells are not terminals (cold-open
blocks need File → New → Terminal), and a backgrounded compound command
resolves $() in the wrong cwd — cd first, then serve.
