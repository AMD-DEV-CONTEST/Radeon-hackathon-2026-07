# radeon-fix product guide

`radeon-fix` is a simple command-line product built on the Track 2 experiment
stack. It repairs a local git repository from a plain-text issue description
using one local model (Qwen3-14B BF16) served by vLLM on AMD Radeon. It is
inference-only: no training, no external model APIs, and no changes to the
user's repository.

## Quickstart

```bash
export TRACK2_BASE_URL=http://127.0.0.1:8000/v1
export TRACK2_API_KEY=local-vllm
export TRACK2_MODEL=Qwen3-14B-BF16

radeon-fix --repo /path/to/repo --issue "Describe the bug you want fixed"
```

Artifacts are written to `./radeon-fix-out/<repo>-<timestamp>/`:

- `patch.diff` — the unified diff to review and apply.
- `report.md` — issue, model, trajectory summary, verifier verdict, AMD GPU
  metrics, and apply instructions.
- `trajectory.json` — the full agent trajectory.
- `run.json` — the frozen run configuration.
- `gpu.json` — a `rocm-smi` snapshot when running on AMD hardware.

## Product configuration

Every run uses the validated product cell:

- mini-SWE controller with A1 budget checkpoint and loop guard;
- Aider Repo Map as initial context (2048 tokens) plus one focused refresh
  after the first successful inspection (C1R1);
- J3 structured actions via vLLM/xgrammar;
- Edit V2 exact-replace protocol for existing single-file edits;
- V1R1 deterministic verifier with at most one evidence-guided repair.

The repository is cloned into a temporary workspace before the agent runs.
The original repository is never modified. The patch can be applied later
with `git apply patch.diff`.

The terminal shows what the agent is doing: one action line per step
(`🔍 inspect`, `✏️ replace`, `📝 edit`, `🧪 execute`, `🏁 finish`), the executed
command for shell work, and a compact unified diff (at most 24 lines) for each
successful edit — the same style used by mainstream CLI agents.

## CLI reference

```text
radeon-fix --repo <path> --issue "<text>" [options]
radeon-fix --repo <path> --issue-file <file> [options]

--base-url <url>       OpenAI-compatible endpoint (default: $TRACK2_BASE_URL)
--model <name>         model id (default: $TRACK2_MODEL or Qwen3-14B-BF16)
--max-turns N          model turns (default 12)
--max-tool-calls N     tool call budget (default 30)
--max-wall-time N      wall-clock budget in seconds (default 900)
--seed N               sampling seed (default 0)
--output-dir <dir>     artifact directory
--verbose              verbose runner logging
--version              print version
```

Exit codes: `0` non-empty patch produced; `1` the agent ran but produced no
patch; `2` invalid arguments, missing endpoint, non-git repository, or an
infrastructure/API failure.

## AMD Radeon deployment

The endpoint must be a local OpenAI-compatible vLLM server. The reference
runtime is documented in [`amd-cloud-deployment.md`](amd-cloud-deployment.md):

```bash
./scripts/cloud_start_vllm.sh
```

The launcher refuses to start unless the expected `gfx1100` device and BF16
support are present. The report includes `rocm-smi` metrics when available.

## Troubleshooting

- **`missing endpoint`**: export `TRACK2_BASE_URL` or pass `--base-url`. Only
  `http://127.0.0.1` / `http://localhost` endpoints are accepted in v1.
- **J3 schema errors or JSON failures**: the vLLM server must be started with
  `--structured-outputs-config.backend xgrammar`. Prompt-only JSON is not a
  substitute.
- **Repo Map unavailable**: Aider's `benchmarks/aider/.venv-track2` is used
  for context extraction. If it is missing, the run continues with a marked
  fallback and `context_available=false` is recorded.
- **`not a git repository`**: pass a path containing a `.git` directory; the
  CLI clones it into a temporary workspace.
