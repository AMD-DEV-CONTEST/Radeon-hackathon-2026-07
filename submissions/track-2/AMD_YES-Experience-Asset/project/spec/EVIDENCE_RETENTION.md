# Engineering Evidence Retention Contract

Status: `MANDATORY / TEAM-VISIBLE`

This contract tells every teammate and coding Agent how to preserve the history
needed for quality review, ROCm optimization, the final demo, and contest
submission. It defines observable evidence responsibilities, but it does not
publish the quality owner's hidden fixtures, gold outputs, exact scoring,
weights, cutoffs, seeds, or aggregation.

## 1. Preserve two different kinds of snapshots

Do not confuse product history with engineering evidence:

1. **Product version snapshot** — the complete validated canonical Experience
   Asset JSON saved after an accepted user/content change. It belongs to the
   product datastore and supports edit, correction, pause/resume, route review,
   and prior-version inspection.
2. **Engineering evidence packet** — a sanitized, reproducible record of a PR,
   milestone gate, GPU run, Baseline, Candidate, or final demo rehearsal. It
   proves what code/configuration ran and what happened.

A product snapshot must not contain model weights, uploads, exports, or raw
traces. An engineering packet must not contain private user content, secrets,
the product database, or private QA material.

## 2. Evidence checkpoints

Create or update an engineering evidence packet at all of these boundaries:

- before and after a risky dependency, model, GPU, migration, load, or
  performance experiment;
- for every implementation PR;
- when M1, M2, M3, M4, M5, rendering/deletion, or an implementation/evidence
  bundle is proposed for promotion, regardless of whether it uses one
  milestone owner or paired evidence lanes;
- at the E1 real-model viability gate, E2 first vertical-slice reference run,
  E8 Baseline v1 freeze, every post-baseline Candidate, and E9 submission/demo
  freeze;
- before a Radeon Cloud instance is stopped, rebuilt, or intentionally placed
  under stress.

Do not wait until the final video to reconstruct evidence from memory.

## 3. Minimum packet

Every packet records, when applicable:

| Area | Required record |
|---|---|
| Identity | UTC timestamp, `run_id`, Git commit SHA, branch, primary Issue/PR, affected `AC-*`, L1 milestone, and L2 gate |
| Environment | W7900 identity, CPU/RAM quota, container/OS, driver, ROCm, HIP, PyTorch, vLLM, application and schema/workflow versions |
| Model/config | Model source, immutable revision or file hash, license, dtype/quantization, context/output limits, server and generation arguments |
| Input boundary | Public fixture ID/version/hash or an approved sanitized demo-case ID; never copy private source material into Git |
| Commands | Exact reproducible setup, run, test, and measurement commands plus exit status |
| Results | Sanitized milestone/output snapshot or hash, terminal state, all relevant measurements, failures, retries, recovery, and unverified items |
| UI/product | State-derived progress, milestone artifact, route/privacy/approval state, and browser capture for changed visible behavior |
| Retrieval phase | For M4/M5 or cross-asset work: Knowledge Card version/hash, current-source versus cross-asset scope, candidate/no-match result, user confirmation/decline, bounded detail provenance and proof current statements were not silently changed |
| Decision | `PASS`, `CONDITIONAL`, `FAIL`, or `NOT VERIFIED`; known risk, owner/deadline when conditional, and rollback/known-good profile |

Performance packets additionally follow
[`BENCHMARK_PLAN.md`](../docs/team-alignment/BENCHMARK_PLAN.md): preserve all
successful and failed observations, sample size, frozen conditions, and the
Baseline/Candidate difference. Never preserve only the best run.

## 4. Storage and publication boundary

Use these locations:

```text
Git (small, sanitized, reproducible)
  evidence/
    milestones/<checkpoint>/<run_id>/
      manifest.json
      summary.md
      artifacts/                 # bounded public fixture/output snapshots
  benchmarks/                    # public fixtures, profiles, manifests, summaries

Radeon Cloud PVC (large or raw working evidence)
  /workspace/amd-track2-agent/evidence/<run_id>/raw/
  /workspace/amd-track2-agent/benchmarks/<run_group_id>/raw/

Approved external storage (large final media)
  demo video, full-resolution captures, PPT/Poster export
  -> keep a stable reference and checksum in the Git evidence index

Quality-owner-only storage (never in this repository or shared pod)
  hidden fixtures, gold labels, evaluator code, exact scoring and private traces
```

GitHub is the durable source for source code and small public evidence.
`/workspace` is a persistent working disk, not a backup. Run
`bash scripts/pre_stop_checkpoint.sh` and push the reviewed task branch before
stopping or stressing the instance.

## 5. History rules

- Evidence packets are append-only after a gate decision. A correction creates
  a new packet or version and links the superseded one; it does not overwrite
  the old conditions or failed result.
- Every packet references the exact commit it describes. A packet generated
  from a dirty tree must say so and cannot freeze a Baseline or submission.
- A milestone promotion is not complete until its sanitized packet is committed
  and pushed. The quality owner may create a Git tag after acceptance, but a
  coding Agent may not tag, merge, or push without current authorization.
- Failed compatibility experiments remain in the sanitized summary with error
  class and rollback result. Large raw logs stay in `/workspace` or approved
  external storage.
- Private content may be represented only by opaque IDs, hashes, counts, schema
  versions, and approved redacted excerpts.

## 6. Secret, privacy, and size gate

Before adding evidence to Git:

- remove API keys, tokens, cookies, email addresses, usernames, SSH material,
  signed URLs, and local/private paths that reveal sensitive data;
- do not commit raw prompts/responses from private experiences, databases,
  uploads, full debug traces, model weights, caches, or unrestricted logs;
- crop or redact browser/terminal captures and check hidden image content;
- prefer JSON/Markdown summaries and hashes over large binaries;
- record why any evidence field is `null` instead of silently omitting a
  required condition.

If a secret or private source enters history, stop the PR and use the approved
incident/removal process. Do not merely add the file to `.gitignore` afterward.

## 7. Coding-Agent obligations

Before implementation, the Agent's alignment/proposal must name:

1. the evidence checkpoint it will produce;
2. the public fixture or sanitized scenario;
3. the expected packet files and storage tier;
4. the exact verification commands;
5. the failure and rollback evidence it will retain.

During implementation, create evidence at the same time as the behavior. At PR
handoff, link the packet and state what is still only an assumption. Missing
evidence is `NOT VERIFIED`, not a reason to infer success.

## 8. Final submission harvest

E9 assembles, rather than invents, the retained history into the official
English submission described in the
[official contest repository](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07):

- Project Specification Document: scenario, Agent architecture, core
  capabilities, model/local deployment, and AMD Radeon inference optimization;
- complete source plus reproducible README;
- recommended 3–5 minute demo showing the real workflow and actual W7900 run;
- one PPT or Poster;
- official contest-repository Pull Request titled
  `Track 2, <Team Name>, <Application Name>`.

The final performance comparison must use the accepted immutable Baseline and
a promoted comparable Candidate, with the environment and failed observations
still available for review.
