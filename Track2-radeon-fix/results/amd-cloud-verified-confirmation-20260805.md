# SWE-bench Verified fixed-task confirmation

Hardware: **AMD Radeon Graphics (gfx1100), 51.52 GB VRAM, RadeonX Cloud**
Model: **Qwen3-14B BF16**, local loopback vLLM, xgrammar/Hermes, INT8 KV,
32K context, prefix caching enabled

This is an Agent-side fixed-task confirmation. The public manifests were frozen
before execution and contain no gold patch, test patch, `FAIL_TO_PASS`, or
`PASS_TO_PASS` fields. The seed-0 patches were subsequently scored with the
official SWE-bench Docker evaluator after freezing; the first-ten seed-1
stability patches are still pending because the local Docker approval quota was
exhausted. The official seed-0 results are reported separately below.

Manifest files:

- `tasks/swebench-verified-confirmation-public.jsonl`
  (`bf6e46ac25b2b3669c89f977bdbcf75a7069452745ef259578e893002beb35ef`)
- `tasks/swebench-verified-confirmation-first10-public.jsonl`
  (`0d94b0f4012448bac04c79590c1fd2b273f5bcc3f80283fffa0f2ea60dd11282`)

## Agent-side results

`non-empty patch` is an engineering proxy only; it is not equivalent to
SWE-bench Full Resolve.

| Harness | Run | Tasks | Non-empty patches | Structured actions | JSON valid | API-error tasks | Integrity violations |
|---|---|---:|---:|---:|---:|---:|---:|
| `mini-original` | seed 0 | 20 | 1/20 | n/a (J0) | n/a | 0 | 1 |
| `mini-repomap-final` | seed 0 | 20 | **16/20** | 189 | **189/189** | 2 | 0 |
| `mini-original` | seed 1, first 10 | 10 | 0/10 | n/a (J0) | n/a | 0 | 0 |
| `mini-repomap-final` | seed 1, first 10 | 10 | **5/10** | 98 | **98/98** | 3 | 1 |

The Repo Map Final seed-0 run produced 19 successful and 15 failed exact
replace attempts (34 total), 4 successful Edit V2 attempts out of 18 edit
actions, and tests after editing on 3/20 tasks. The seed-1 run produced 5/15
successful replace attempts and 2/17 Edit V2 attempts, with tests after editing
on 1/10 tasks. API timeouts are retained in the JSONL and are not silently
removed. One seed-1 Repo Map trajectory attempted a network command and is
therefore excluded from any capability ranking.

For the first ten paired tasks, using non-empty patch only as a stability
proxy:

| Harness | Patch proxy `pass@2` | Patch proxy `pass^2` |
|---|---:|---:|
| `mini-original` | 0/10 | 0/10 |
| `mini-repomap-final` | **10/10** | **4/10** |

These are not official `pass@2`/`pass²` scores. They become official only
after both frozen patches are evaluated against SWE-bench tests. The `pass^2`
column is useful here because it separates repeatable patches from one-run
successes; the gap also shows that the model/harness remains stochastic.

## Official evaluator: seed 0

The evaluator ran on the frozen 20-task manifest. The official runner's
aggregate report was written with the full SWE-bench test-set size, so the
fixed-task denominator below is taken from the frozen manifest (20), not from
the runner's `total_instances` field. Empty predictions were not sent to
Docker and remain unresolved for the fixed-task score.

| Harness | Fixed tasks | Non-empty evaluated | Patch applied | F2P complete* | P2P complete* | Full Resolve | Evaluator errors |
|---|---:|---:|---:|---:|---:|---:|---:|
| `mini-original` | 20 | 1 | 1/20 | 1/20 | 1/20 | **1/20** | 0 |
| `mini-repomap-final` | 20 | 16 | **16/20** | 1/20 | 7/20 | **1/20** | 0 |

\* F2P/P2P are counted as complete tasks over the fixed 20-task manifest;
empty patches count as failures. Among the 16 RepoMap Final patches actually
executed by Docker, 1/16 had complete F2P and 7/16 had complete P2P. The
single resolved task for both harnesses was `django__django-16527`; this is a
shared task and is not evidence that Repo Map improved official resolve rate on
this small confirmation. Per-task evaluator logs are under
`logs/run_evaluation/track2-official-*` and the compact reports are the
`mini-*.track2-official-*.json` files in the project root.

The seed-1 first-ten official evaluator run was not started after the Docker
approval quota was exhausted. Its Agent-side patch proxy remains explicitly
non-official; no stability claim is made from it.

## Efficiency and integrity

- `mini-repomap-final`, seed 0: 1,094,595 total tokens, 189 tool/action
  calls, mean wall time 1.92 minutes per task, P95 6.04 minutes.
- `mini-repomap-final`, seed 1 first ten: 625,775 total tokens, 98
  tool/action calls, mean wall time 3.55 minutes per task, P95 6.01 minutes.
- Agents never received gold fields; `evaluations` is empty and
  `ranking_valid` is false in both run summaries.
- The seed-0 `mini-original` network event and seed-1 Repo Map network event
  remain visible as integrity failures. They are evidence about harness
  behavior, not successes to be hidden.

Raw artifacts:

- `runs/amd-cloud-verified-confirmation-seed0-v2/`
- `runs/amd-cloud-verified-confirmation-seed1-first10/`

The remaining scoring step is to run the already-frozen first-ten seed-1
patches with the same evaluator and append the results without feeding them
back to the Agent or changing the manifest.
