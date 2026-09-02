# AMD Track 2 experiment runner

`mini_swe_runner.py` exposes four explicit Track 2 axes: repository context,
controller policy, action protocol, and verifier. Historical C/J/V flags remain
readable for old artifacts; new runs use the final matrix below.

## Product configuration

The product claim is intentionally limited to one composition:

```text
mini-SWE-agent
  + Aider Repo Map (2048-token initial map)
  + one focused Repo Map refresh after the first successful inspect
  + Edit V2 exact replace for existing single-file edits
  + A1 budget checkpoint and loop guard
  + V1R1 deterministic verifier with at most one repair request
  + Qwen3-14B BF16 on RadeonX Cloud localhost vLLM
```

RepoGraph is retained only as `mini-repograph-clean` for the historical
research ablation. It is not combined with the product configuration and is
not used to support the Repo Map product claim. The final action metrics count
structured `inspect`, `search`, `replace`, `edit`, `execute`, and `finish`
actions separately; a non-empty patch is never treated as evidence that an
edit tool call succeeded.

The five-task development gate is a go/no-go check, not a benchmark ranking.
The focused recovery passed for the product cell: 5/5 non-empty patches,
5/5 applied replacements, 38/38 valid J3 actions, and zero integrity or
patch-capture failures. The initial failed rerun and the same-15-cell recovery
are both retained under `runs/` and `results/`. Seed-0 of the fixed 20-task
SWE-bench Verified confirmation has now been scored by the official Docker
evaluator (1/20 Full Resolve for both harnesses; RepoMap Final had 16/20
applied patches). The first-ten seed-1 stability score remains pending.

## API-only capability probe

Put endpoint settings in environment variables so the key is not written to
source files or task manifests:

```bash
export TRACK2_BASE_URL='https://provider.example/v1'
export TRACK2_API_KEY='...'
export TRACK2_MODEL='small-code-model'

python track2_api_probe.py \
  --context_sizes 4096,8192 \
  --output runs/api-capabilities.json
```

The probe independently checks `/models`, ordinary chat, tool calling, prompt
JSON, native `response_format` JSON, and the current vLLM `structured_outputs`
request. A successful prompt JSON response is reported as `json_prompt`; it is
not counted as constrained decoding. If `structured_outputs` fails, skip
J3/J4 for the hosted API and reserve them for the vLLM instance in AMD Cloud.
Context-size checks are optional because each accepted size consumes a request.

On macOS, the API token can be stored once in Keychain instead of an
environment variable or a file:

```bash
./scripts/store_track2_keychain.sh
./scripts/run_track2_api_smoke.sh
```

The launcher reads only the Keychain item named `hermes-track2-amd` and never
prints the token. Use a new token; do not store the previously exposed one.

## Baseline

The task JSONL can be downloaded from the official Hugging Face dataset
without manually collecting issues:

```bash
python3 track2_dataset.py --dataset lite --limit 30 --seed 0 --output tasks/smoke.jsonl
python3 track2_dataset.py --dataset verified --limit 100 --seed 0 --output tasks/verified-100.jsonl

python3 track2_prepare.py \
  --tasks_file tasks/smoke.jsonl \
  --workspace_root workspaces/smoke \
  --manifest tasks/smoke-manifest.jsonl
```

The generated file keeps the public issue/repository metadata and excludes
`patch`, `test_patch`, `FAIL_TO_PASS`, and `PASS_TO_PASS` from the prompt.

The downloader uses the Hugging Face `datasets` package when available and
falls back to the read-only Dataset Viewer API, so a clean API-only worker can
fetch public rows without installing another dataset package.

Official sources: [SWE-bench datasets](https://www.swebench.com/SWE-bench/guides/datasets/),
[SWE-bench GitHub](https://github.com/SWE-bench/SWE-bench), and
[SWT-Bench](https://github.com/logic-star-ai/swt-bench).

```bash
python mini_swe_runner.py \
  --task "Fix the failing issue in this repository" \
  --env local \
  --context_variant C0 \
  --json_mode J0 \
  --verifier_mode V0
```

## JSON action mode

J3 is the final constrained JSON Action protocol: vLLM `structured_outputs`
with xgrammar. J1/J2/J4/J5 remain compatibility modes for historical API
results and are not part of the final AMD ranking. The server must be started
with the desired structured-output backend.

For a current vLLM server, pin the backend explicitly for reproducibility:

```bash
export TRACK2_BASE_URL=http://127.0.0.1:8000/v1
export TRACK2_API_KEY=local
export TRACK2_MODEL=<served-model-name>

vllm serve <model> \
  --structured-outputs-config.backend xgrammar
```

```bash
python mini_swe_runner.py \
  --task "Fix the failing issue in this repository" \
  --json_mode J3 \
  --context_variant C0 \
  --controller_policy A0 \
  --verifier_mode V0 \
  --max_model_turns 12 \
  --max_tool_calls 30 \
  --max_wall_time_seconds 900
```

The action envelope is intentionally small. A unified diff remains a string
and is applied with `git apply`; the verifier, not the JSON schema, decides
whether the code is correct.

## Final context/controller/verifier ablations

Run one context and one verifier variant at a time:

```bash
python mini_swe_runner.py --task "$TASK" --context_variant C1 --json_mode J0 --controller_policy A0 --verifier_mode V0
python mini_swe_runner.py --task "$TASK" --context_variant C2 --json_mode J0 --controller_policy A0 --verifier_mode V0
python mini_swe_runner.py --task "$TASK" --context_variant C0 --json_mode J0 --controller_policy A1 --verifier_mode V0
python mini_swe_runner.py --task "$TASK" --context_variant C0 --json_mode J0 --controller_policy A0 --verifier_mode V1R1
```

Optional native providers are explicitly marked unavailable when their
commands are not installed. Configure them rather than silently treating a
fallback as the real experiment:

```bash
export TRACK2_AIDER_REPOMAP_COMMAND='aider --show-repo-map'
export TRACK2_REPOGRAPH_COMMAND='python -m repograph ...'
```

The full matrix and fixed budgets live in
[`configs/track2_ablation.json`](../configs/track2_ablation.json).

## Batch ablations

Use the same prompt JSONL and fixed task order for every variant:

```bash
python track2_eval.py \
  --prompts_file tasks/smoke-manifest.jsonl \
  --output_dir runs/smoke \
  --limit 30 \
  --variant C0-J0-A0-V0 \
  --variant C1-J0-A0-V0 \
  --variant C2-J0-A0-V0 \
  --variant C0-J0-A1-V0 \
  --variant C0-J0-A0-V1R1 \
  --variant C0-J3-A0-V0 \
  --max-model-turns 12 --max-tool-calls 30 --max-wall-time-seconds 900
```

After the fixed workspaces are prepared, the complete API smoke matrix can be
launched from the shell that owns `TRACK2_API_KEY` with:

```bash
./scripts/run_track2_api_smoke.sh
```

The script includes only the final C0/C1/C2, A0/A1, J0/J3 and V0/V1R1
variants. J3 is included only after the cloud acceptance probe has confirmed
20/20 schema-valid JSON responses.

The prepared manifest records one repository checkout per task at its
`base_commit`. The evaluator resets every checkout to that commit before each
variant; otherwise a patch from C0 would become the starting state for C1.
The official SWE-bench Docker harness remains the final score authority.

Each variant gets its own JSONL trajectory file. `summary.json` reports
completion rate, mean API calls, JSON retries, verifier acceptance, and
context availability, so unavailable optional providers cannot be confused
with successful ablations.

If the provider is intermittently unavailable, rerun the same command with
`--resume` and a shorter `--api_timeout` (for example `20`). Existing
`instance_id` records are kept and skipped; only unfinished tasks are retried.

After running the official evaluator, pass its JSONL (with boolean
`instance_id`/`resolved` records) as `--official_results` to add false-accept
and false-reject counts to the summary.

## External comparator

The primary independent comparator is pinned to Qwen Code 0.21.0. It uses the
same model and task statement as mini-SWE-agent, but receives a fresh
`QWEN_HOME`, runtime directory, and session for every task. Its stream-JSON
events, usage, tool calls, termination reason, stderr, and final `git diff` are
captured by `track2_qwen_code.py`. OpenHands is deliberately out of the
deadline-scoped experiment. If Qwen Code fails its two-task calibration, it is
reported as an adapter failure and does not enter the capability ranking.

The leakage-free SWE-bench pilot runner compares the four prespecified groups
and invokes the official evaluator only after every patch is frozen:

```bash
.venv/bin/python track2_swebench_harness.py \
  --dataset benchmarks/RepoGraph/SWE-agent/tests/test_data/data_sources/swe-bench-lite-test.json \
  --output-dir runs/swebench-harness-pilot \
  --instance-id django__django-16255 \
  --instance-id sympy__sympy-13031 \
  --instance-id pytest-dev__pytest-11143 \
  --instance-id scikit-learn__scikit-learn-13584 \
  --instance-id django__django-15781 \
  --harness mini-original \
  --harness mini-repomap \
  --harness mini-repograph-clean \
  --harness mini-budget \
  --harness mini-verifier-repair \
  --harness mini-json-structured \
  --harness qwen-code \
  --max-calls 12 \
  --max-tool-calls 30 \
  --max-wall-time 900 \
  --evaluate
```

The output schema records completion, patch/apply/resolve rates, F2P/P2P,
localization, first edit, tests after editing, model/tool calls, tokens,
mean/P95 latency, repeated commands, API/tool failures, and integrity events.
No ranking is emitted unless every harness finishes the infrastructure path
on all selected tasks.

The first formal run and its interpretation are documented in
[`track2-pilot-v6-20260803.md`](track2-pilot-v6-20260803.md).

Render a judge-facing CLI dashboard for any frozen candidate without exposing
hidden test identifiers:

```bash
.venv/bin/python track2_demo.py \
  --run-dir runs/swebench-harness-pilot-v1 \
  --harness mini-repomap \
  --task-id django__django-16255 \
  --gpu-metrics runs/amd-cloud-gpu-metrics.json
```

The optional metrics file accepts `gpu_model`, `rocm_version`, `vllm_version`,
`ttft_ms`, `tokens_per_second`, `p50_latency_ms`, `p95_latency_ms`, `vram_gb`,
and `gpu_utilization_percent`. This keeps measured AMD Cloud telemetry separate
from hosted-API pilot data.

## Historical API harness benchmark

`track2_harness_benchmark.py` runs the independent Aider whole-file harness and
older mini-SWE configurations against the same fixed Python subset of Aider's
Polyglot benchmark. This section records the preliminary API-era snapshot only;
it is not part of the deadline-scoped AMD ranking. The final comparator is
Qwen Code 0.21.0 after its two-task calibration, and the final benchmark uses
the fixed SWE-bench pilot/confirmation matrix above.

```bash
.venv/bin/python track2_harness_benchmark.py \
  --output-dir runs/harness-final \
  --task-count 10 \
  --seed 42 \
  --max-calls 4 \
  --api-timeout 60 \
  --transport-retries 3
```

The retained summary is in `results/harness-polyglot/`. The strict end-to-end scores
were mini-original 4/10, Aider whole-file 3/10, JSON+V1 1/10, RepoGraph 1/10,
and Aider Repo Map 0/10. Aider had seven infrastructure-incomplete tasks, so
its number is an API-path score rather than a clean capability estimate. The
Chinese report records both those gaps and the uncorrected 50-cell snapshot:
`results/harness-polyglot/report.zh-CN.md`.

## Verifier gates

- V1: non-empty changes, `git diff --check`, and Python compilation;
- V1R1: V1 plus one bounded model repair sequence using the failure report;
- V2/V3/V4/V5 remain readable for historical artifacts but are not part of the
  deadline-scoped ranking.

Every batch result includes the context availability, JSON mode, parser retry
count, verifier report, timestamp, API token usage, per-call latency, wall
time, API errors, and optional estimated cost in its metadata for later
ablation analysis. Set `TRACK2_INPUT_USD_PER_1M` and
`TRACK2_OUTPUT_USD_PER_1M` when provider pricing is known.
