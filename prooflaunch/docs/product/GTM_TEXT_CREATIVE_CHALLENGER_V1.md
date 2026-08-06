# ProofLaunch Text Creative Challenger V1

Date: 2026-08-01  
Machine contract: `src/prooflaunch_remix/gtm_text_challenger.py`

## Outcome

The deterministic channel copy is now a visible baseline, not the presumed
creative winner. Every compiled strategy carries three model-ready challenger
territories:

1. **Decision x-ray** — expose and name the unresolved decision friction;
2. **Proof before promise** — make the approved evidence and its limitation the
   dramatic center;
3. **Voluntary relay** — create a useful decision object a recipient may choose
   to pass to a relevant peer.

This is an execution-ready request plan. It is not evidence that a model was
called, a candidate was generated, a blind reviewer preferred it, or an effect
was observed.

## Closed creative contract

Each territory binds the exact strategy ID, proof claim ID, evidence digest,
approved proof text, CTA, primary/secondary channels, native formats, audience,
budget, lifecycle and breakout mechanism. The gateway receives at most three
development-core calls and must route official-first.

Candidate admission is fail-closed:

- exactly one JSON object with a closed field set and two channel drafts;
- exact approved factual-claim list, exact proof in both drafts and no new
  numeric claim;
- exact CTA, channel and native-format order;
- no rankings, unsupported effect language or invented capabilities;
- no verbatim cross-channel duplicate;
- explicit `draft_pending_human_review` disclosure;
- content digest covering the candidate plus winner, blind-review and external
  publish locks.

Execution defaults to sequential fail-fast operation: concurrency one, one
official Qwen request per territory, zero automatic retry rounds, and a
1,400-token output ceiling. Additional official models or reviewed
development-only fallbacks must be selected explicitly. This prevents repeated
502 waits or quota burning from being mistaken for useful training work.

Validated candidates remain `winner_selected=false`,
`blind_review_completed=false` and `external_publish_executed=false`. A receipt
can bind all three candidate hashes, but it still cannot establish quality.

## Effect ladder

```text
planned request
  -> official/local model response
  -> mechanical contract validation
  -> randomized identity-hidden human comparison
  -> approved experiment
  -> aggregate observed effect
```

No stage may be inferred from a previous stage. In particular, an LLM response
or mechanical score cannot establish 4A preference, publication, lift,
virality, conversion or revenue.

## Evidence

`tests/test_gtm_text_challenger.py` attacks request tampering, markdown-wrapped
responses, extra fields, factual-claim drift, numeric hallucination, CTA drift,
cross-channel duplication and post-validation mutation. The 48-scenario matrix
proves that B2B/B2C, every lifecycle, every budget and both risk tiers compile
the same three bounded territories without selecting a winner or publishing.

Real model and blind-review evidence remain outstanding until a credentialed
official gateway or admitted Radeon-local route is available.

## Credentialed execution

Use the exact plan and baseline copy from an `awaiting_release` run. The API key
must exist only in the process environment:

```bash
export RADEON_TOKEN_FACTORY_API_KEY='session-only-secret'
PYTHONPATH=src ./.venv/bin/python scripts/run_gtm_text_challenger.py \
  --plan path/to/text-creative-challenger-plan.json \
  --channel-copy path/to/channel-copy.json \
  --output-dir artifacts/text-challenger-real-run
```

On three validated responses the command creates six randomized
candidate-versus-baseline content pairs and thirty empty human assignments
(five reviewers per pair). Provider, model, territory and candidate side are
absent from the public packet; the private mapping is mode `0600`, and the
randomization secret is never persisted. No model judge fills human ratings.

After five real reviewers complete the JSONL rows, aggregate them without
exposing candidate identity during review:

```bash
PYTHONPATH=src ./.venv/bin/python scripts/aggregate_gtm_text_blind_reviews.py \
  --public-packet artifacts/text-challenger-real-run/text-creative-blind-review-public.json \
  --private-mapping artifacts/text-challenger-real-run/text-creative-blind-review-private.json \
  --reviews-jsonl artifacts/text-challenger-real-run/completed-human-reviews.jsonl \
  --output artifacts/text-challenger-real-run/blind-review-aggregate.json
```

Every row requires the exact human attestation, a stable pseudonym per reviewer
slot, timezone-aware timestamp, reason, critical-failure flag and content hash.
The aggregate uses binary left/right/abstain choices and Wilson lower bounds;
ties, identity drift, missing rows, critical failures or weak confidence produce
no recommendation. Even a unique passing recommendation remains
`winner_selected=false` until a separate accountable human decision.
