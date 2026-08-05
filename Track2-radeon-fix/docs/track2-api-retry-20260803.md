# Track 2 AMD API retry: 2026-08-03

## What changed

The first retry exposed an experiment-runner bug: the C5-only forced-edit
inspection gate was enabled after half of every mini-SWE run, including the
C0/C1/C2 baselines. It rejected legitimate read-only localization commands
with `INSPECTION_BUDGET_EXHAUSTED`, so earlier mini-SWE comparisons were
contaminated. The gate is now restricted to C5.

Two Qwen Code accounting bugs were also corrected: `todo_write` is no longer
counted as a source edit, and Qwen Code exit 53 after using all configured
model turns is classified as `max_model_turns`, not an API failure.

## Clean stability gate

The same difficult SWE-bench Lite instance, `sympy__sympy-13031`, was rerun
with Qwen3.6-35B-A3B, eight model turns, clean workspaces, and no official test
feedback.

| Harness | Successful model calls | API errors | Infra incomplete | Patch | Tokens | Wall time |
|---|---:|---:|---:|---:|---:|---:|
| mini-original | 8/8 | 0 | 0 | empty | 25,467 | 75.3 s |
| mini-repomap | 8/8 | 0 | 0 | empty | 30,938 | 89.7 s |
| mini-repograph-clean | 8/8 | 0 | 0 | empty | 22,297 | 66.7 s |

The clean run is in
[`../results/api-retry-clean/summary.json`](../results/api-retry-clean/summary.json).

The API was stable for all twenty-four mini-SWE calls. All three harnesses
localized relevant matrix code, but spent the full eight turns inspecting and
never edited a file. This is now a controller/budget failure rather than an API
failure. RepoGraph used the fewest tokens and lowest latency on this single
task, but no harness solved it and one task cannot establish a leader.

Qwen Code was also retried before the accounting correction. It completed all
eight model turns and twelve tools without a patch, consumed 148,963 tokens,
and took 557.8 seconds. Its final process exit was normal turn-budget
exhaustion, not an API connection error. Its much larger context and latency
make it a costly comparator under the current configuration.

## Next experiment

Increase the semantic budget to twelve turns while keeping tool and wall-clock
budgets fixed, and add a neutral controller reminder after turn six: summarize
the likely root cause and either implement the smallest candidate fix or state
the missing evidence. This must be tested as a separate controller variant;
it must not be silently added only to Repo Map or RepoGraph.
