# Track 2 pilot v6 — 2026-08-03

This is the clean mini-harness pilot after the v1/v5 audit. It uses the same
`Qwen3.6-35B-A3B` AMD API, five fixed SWE-bench Lite tasks, fresh Docker
workspaces, eight model turns, forty tool calls, and a 240-second per-task
wall-clock limit:

| Harness | Context | Tasks | Non-empty patches | Official resolve |
|---|---|---:|---:|---:|
| `mini-original` | C0 | 5/5 | 2/5 | **2/5 (40%)** |
| `mini-repomap` | C1 + Aider Repo Map | 5/5 | 2/5 | **2/5 (40%)** |
| `mini-repograph-clean` | C2 + RepoGraph | 5/5 | 1/5 | **1/5 (20%)** |

The official reports used `FAIL_TO_PASS` and `PASS_TO_PASS`. Both resolved
patches passed all visible official checks: Django 16255 passed 1/1 F2P and
36/36 P2P; pytest 11143 passed 1/1 F2P and 114/114 P2P. Identical task+patch
reports are reused by hash, so no evaluator result is inferred from a patch
rate or from a local self-test.

Artifacts:

- [`summary.json`](../results/swebench-pilot-v6/summary.json)
- [`results.jsonl`](../results/swebench-pilot-v6/results.jsonl)
- [`run-config.json`](../results/swebench-pilot-v6/run-config.json)

## Why the other tasks failed

The failures are mostly model-controller failures, not API transport failures:

- SymPy 13031: all three mini variants localized `common.py` but did not edit
  the `sparse.py` override within eight turns.
- scikit-learn 13584: the model inspected `_pprint.py`, then spent budget on
  unavailable NumPy/package checks and did not edit.
- Django 15781: the model inspected help/formatter code but did not reach the
  relevant edit before the turn budget ended.

The runner now normalizes `/testbed` and `/home/user` aliases, blocks network
installs and outside-root scans without executing them, truncates large tool
outputs, forces an edit phase by the midpoint, and captures the final diff from
the host bind mount if Docker's wrapper loses its in-container `git diff`.
Blocked policy events are recorded but are not integrity failures; an actual
network or outside-workspace execution remains disqualifying.

## Qwen Code compatibility gate

Qwen Code 0.21.0 was tested separately on Django 16255 and pytest 11143 with a
four-turn/180-second low-budget calibration. Both tasks timed out in the model
request before producing a tool call or patch (`2/2` API errors, `0/2` patches).
It is therefore excluded from the v6 ranking under the prespecified adapter
gate. OpenHands is not installed in this workspace and is not included in the
deadline-scoped experiment; it must not be silently substituted for a
successful Qwen run.

The v6 result is a valid pilot leader only for this five-task manifest and
budget: `mini-original` and `mini-repomap` tie on official resolve rate, while
`mini-original` is the latency/token Pareto winner. It is not a statistically
significant claim about SWE-bench Lite as a whole. The next experiment should
use a stable localhost vLLM endpoint on AMD Cloud, retain the same task
manifest, and increase the budget before selecting a final Track 2 system.
