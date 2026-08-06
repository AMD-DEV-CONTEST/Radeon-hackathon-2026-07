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

For auditable test evidence, add a final check that runs after the agent:

```bash
radeon-fix --repo /path/to/repo --issue "Describe the bug" \
  --final-test-cmd "python -m pytest -q"
```

Artifacts are written to `./radeon-fix-out/<repo>-<timestamp>/`:

- `patch.diff` — the unified diff to review and apply.
- `report.md` — issue, model, trajectory summary, verifier verdict, AMD GPU
  metrics, and apply instructions.
- `trajectory.json` — the full agent trajectory.
- `run.json` — the frozen run configuration.
- `gpu.json` — a `rocm-smi` snapshot when running on AMD hardware.
- `report.md` and `run.json` also include a `final_test` block when
  `--final-test-cmd` is used (command, exit code, passed, output tail).

## Product configuration

Every run uses the validated product cell:

- mini-SWE controller with A1 budget checkpoint and loop guard;
- Aider Repo Map as initial context (2048 tokens) plus one focused refresh
  after the first successful inspection (C1R1);
- J3 structured actions via vLLM/xgrammar;
- Edit V2 exact-replace protocol for existing single-file edits;
- V1R1 deterministic verifier with at most one evidence-guided repair.

The verifier (V1R1) runs deterministic gates only: patch apply
(`git apply --check`), `git diff --check`, presence of changes, and
`py_compile` for changed Python files. It does not execute tests. Test
evidence comes from the optional `--final-test-cmd`, which is recorded
separately from the verifier verdict.

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
--final-test-cmd CMD   optional command run after the agent in the temporary
                       workspace (e.g. "python -m pytest -q"); failure maps
                       to exit 3
--require-context      fail fast (exit 2) if the Aider Repo Map provider is
                       unavailable
--output-dir <dir>     artifact directory
--verbose              verbose runner logging
--version              print version
```

Exit codes: `0` verified patch produced (verifier accepted, and the final
check passed when configured); `1` the agent ran but produced no patch; `2`
invalid arguments, missing endpoint, non-git repository, missing required
context, or an infrastructure/API failure; `3` a non-empty patch was produced
but the verifier rejected it, or the configured final check failed.

## Execution boundary

`radeon-fix` clones the repository into a temporary workspace and runs tool
commands with a secret-stripped environment and command guards for
network/package-install and absolute-path commands. This is command-guarded
local execution, not an OS-level sandbox. The benchmark runtime also exposes
a Docker environment (`--agent-env docker`) for stronger isolation.

## AMD Radeon deployment

The endpoint must be a local OpenAI-compatible vLLM server. The reference
runtime is documented in [`amd-cloud-deployment.md`](amd-cloud-deployment.md):

```bash
./scripts/cloud_start_vllm.sh
```

The launcher refuses to start unless the expected `gfx1100` device and BF16
support are present. The report includes `rocm-smi` metrics when available.
`gpu.json` also records the model, KV-cache profile, ROCm/vLLM versions, and
measured TTFT/decode values (from the environment or `configs/gpu_probe.json`).

## Troubleshooting

- **`missing endpoint`**: export `TRACK2_BASE_URL` or pass `--base-url`. Only
  `http://127.0.0.1` / `http://localhost` endpoints are accepted in v1.
- **J3 schema errors or JSON failures**: the vLLM server must be started with
  `--structured-outputs-config.backend xgrammar`. Prompt-only JSON is not a
  substitute.
- **Repo Map unavailable**: Aider's `benchmarks/aider/.venv-track2` is used
  for context extraction. If it is missing, the run continues with a marked
  fallback, a visible warning is printed, and `context_available=false` is
  recorded; pass `--require-context` to fail instead. Run
  `scripts/setup_product.sh` to install the Repo Map path reproducibly.
- **`not a git repository`**: pass a path containing a `.git` directory; the
  CLI clones it into a temporary workspace.
