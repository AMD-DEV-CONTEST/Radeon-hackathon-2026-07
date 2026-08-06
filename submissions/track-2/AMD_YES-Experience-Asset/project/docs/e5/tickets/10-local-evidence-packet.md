# 10 — Local deterministic evidence packet

**What to build:** Everything about E5 that can be proven on a machine without a Radeon
GPU is proven and packaged: the full external behavior matrix at the authoritative
public seam, public QA gate ordering, contract synchronization, migration upgrade and
rebuild, restart, invalidation, and non-contamination. The packet records commands,
versions, outcomes, and failures, and contains nothing private.

**Why this is separate from the W7900 gate:** the two need different hardware. Bundling
them means the ticket cannot close anywhere the GPU is unavailable, and the person
holding it faces a choice between leaving E5 permanently open and marking a claim they
did not verify. Splitting them lets the local work reach a real terminal state while the
GPU claim waits for the environment that can actually produce it.

**Why the packet records failures and rollbacks rather than only passes:** its purpose
is to let a reviewer who does not trust the author reconstruct what happened. A packet
containing only successes gives them no way to distinguish "nothing failed" from
"failures were omitted", so its passes carry less weight, not more.

**Terminal states for this ticket:** `prepared` or `not-run`. It cannot report `PASS`
for any claim requiring W7900/ROCm/vLLM — those belong to ticket 11. Writing a fake or
inferred `PASS` fails in a way that is not local to that line: once a packet is known to
contain one unreproducible claim, a reviewer has to treat every other claim in it as
unverified too.

**Blocked by:** 09 — Invalidation, staleness, and restart resume.

**Owns:** the local sanitized evidence packet and the public QA run.

**Not in this ticket:** no W7900/ROCm/vLLM run and no claim derived from one; no
performance measurement or Baseline; no private blind fixtures or thresholds. The
packet will look incomplete without the local-model result, and the tempting repair is
to run the deterministic fake and record it as the model evidence. That fails because
the fake was written to return what the validator accepts — it demonstrates the
validator and the workflow, and says nothing about whether a real model can produce a
schema-valid proposal over these graphs, which is the only claim ticket 11 makes.

Put the effort into making the local half airtight instead: every GRAG behaviour at the
public seam, migration upgrade and rebuild, the disclosure scan, and failure and
rollback notes. A packet that is honestly incomplete in one named place is worth more
than one that is complete and partly unreproducible.

**Verify with:** `python3 scripts/export_contracts.py --check`,
`bash qa/gates/pr_gate.sh --mode contract`,
`python3 -m unittest discover -s qa/tests -v`, `python3 -m pytest -q`, the affected web
tests, and the retrieval-phase checker.

**Status:** ready-for-agent

## Acceptance criteria

- [ ] GRAG-01 through GRAG-18 pass at the authoritative external seam using the
      deterministic model fake, with focused unit coverage limited to projection hashing,
      bilingual normalization, fingerprint canonicalization, role-pair admissibility,
      strict proposal validation, and deterministic evidence rendering.
- [ ] Contract synchronization and migration upgrade/rebuild behavior pass without
      losing existing accepted data.
- [ ] Public QA proves readiness ordering, explicit trigger, pre-confirmation denial,
      positive candidate, semantic no-match, decline, invalid proposal, invalidation, and
      current-asset non-contamination, using only public fixtures. Private blind cases or
      guessed thresholds in a public packet would either leak evaluation material or
      report a threshold nobody agreed to.
- [ ] Complete affected regression and the live product path run against the stable
      evidence head.
- [ ] One exact-commit sanitized packet records commands, contract and migration
      versions, outcomes, failures, retry behavior, rollback notes, and retained failure
      observations.
- [ ] The packet contains no raw prompts, responses, private source text, credentials,
      model weights, or hidden QA material, and a disclosure/credential scan confirms it.
- [ ] Every claim needing W7900/ROCm/vLLM is recorded as `BLOCKED` or `NOT_VERIFIED`
      with a pointer to ticket 11, never as `PASS`.
