# Radeon Code Agent

Radeon Code Agent is an inference-only private repository repair system for
AMD Radeon Hackathon 2026 Track 2. It uses one local Qwen3-14B model with a
mini-SWE controller, optional repository context, structured actions, and a
deterministic verifier with one bounded repair attempt.

The final deployment target is a private AMD Radeon GPU instance running the
model and OpenAI-compatible vLLM endpoint locally. No model training is used.

## Product: `radeon-fix`

`radeon-fix` is the simple command-line product built on the validated Track 2
product cell (C1R1 + J3/EditV2 + A1 + V1R1). It repairs a local git repository
from an issue description using the local model, without modifying the user's
repository:

```bash
pip install -e .
export TRACK2_BASE_URL=http://127.0.0.1:8000/v1
export TRACK2_API_KEY=local-vllm
export TRACK2_MODEL=Qwen3-14B-BF16

radeon-fix --repo /path/to/repo --issue "Describe the bug"
```

Output is written to `./radeon-fix-out/<repo>-<timestamp>/`:
`patch.diff`, `report.md` (with AMD GPU metrics when running on Radeon),
`trajectory.json`, `run.json`, and `gpu.json`. See
[`docs/product.md`](docs/product.md) for the CLI reference and
troubleshooting. A short English demo video, its replay page, and the
recorded session assets live in [`demo/`](demo/README.md).

Exit codes: `0` verified patch produced; `1` no patch produced; `2`
configuration, repository, API, or structured-output error; `3` patch
produced but the deterministic verifier rejected it, or the optional
`--final-test-cmd` failed. The verifier (V1R1) is a deterministic
syntax/structure gate (`git apply --check`, `git diff --check`,
`py_compile`) and does not run tests; pass
`--final-test-cmd "python -m pytest -q"` to record auditable test evidence
in `report.md` and `run.json`. Tool commands run in a command-guarded local
environment (not an OS-level sandbox); a Docker environment is available in
the benchmark runtime.

## Architecture

```text
SWE-bench issue
    -> mini-SWE controller
    -> C0 baseline | C1 Aider Repo Map + one focused refresh
    -> Qwen3-14B BF16 on AMD Radeon gfx1100 / ROCm
    -> A0 original controller | A1 budget-aware controller
    -> J0 native tools | J3 xgrammar Action + Edit V2 replace
    -> V1 deterministic checks | V1R1 one evidence-guided repair
    -> patch, test evidence, trajectory, and performance metrics
```

Qwen Code 0.21.0 is included as the independent harness comparator. It uses
the same model endpoint, sampling profile, task budget, and fresh workspace so
the experiment measures the model-harness pair rather than comparing different
models.

## Repository layout

- `mini_swe_runner.py`: mini-SWE controller, budgets, action protocol, and repair loop.
- `swe_experiments/`: action schemas, context providers, structured output,
  experiment config, API accounting, and verifier.
- `track2_swebench_harness.py`: leakage-controlled SWE-bench runner.
- `track2_qwen_code.py`: isolated Qwen Code adapter and trajectory parser.
- `track2_context_extract.py`: Aider Repo Map and RepoGraph extraction.
- `track2_dataset.py` / `track2_prepare.py`: deterministic task acquisition and
  checkout preparation.
- `track2_demo.py`: lightweight Markdown demo report.
- `configs/track2_ablation.json`: experiment matrix and fixed budgets.
- `results/`: selected, path-redacted pilot results. Generated workspaces and
  secrets are intentionally excluded.

## Setup

```bash
./scripts/setup_product.sh
```

`setup_product.sh` creates the main venv, installs the project, clones the
pinned Aider commit, creates `benchmarks/aider/.venv-track2` with Aider's
Repo Map dependencies, runs a Repo Map smoke test, and checks the local vLLM
endpoint. Optional benchmark and comparator dependencies are pinned by:

```bash
./scripts/bootstrap_benchmarks.sh
```

`pip install -e '.[dev]'` remains available for a minimal install, but the
Repo Map product path requires `setup_product.sh`; without it the run
continues with `context_available=false` and a warning (or fails fast with
`--require-context`).

API credentials are read only from environment variables:

```bash
export TRACK2_BASE_URL=http://127.0.0.1:8000/v1
export TRACK2_API_KEY=local-vllm
export TRACK2_MODEL=Qwen3-14B-BF16
```

## Run the final mini-SWE pilot

```bash
python track2_swebench_harness.py \
  --dataset tasks/swebench-lite.json \
  --limit 5 \
  --harness mini-original \
  --harness mini-repomap \
  --harness mini-repograph-clean \
  --harness mini-budget \
  --harness mini-verifier-repair \
  --harness mini-json-structured \
  --agent-env local \
  --max-calls 12 --max-tool-calls 30 --max-wall-time 900 \
  --output-dir runs/amd-cloud-pilot
```

Qwen Code is calibrated separately on two tasks and enters the final
comparison only if its event stream, tools, and patch capture are complete.
The official SWE-bench evaluator runs after patches are frozen; its gold
fields never enter the agent prompt or verifier feedback. For details, see
[`docs/track2.md`](docs/track2.md). For the AMD instance deployment sequence,
see [`docs/amd-cloud-deployment.md`](docs/amd-cloud-deployment.md). Frozen
RadeonX Cloud measurements are summarized in
[`docs/amd-cloud-results-20260804.md`](docs/amd-cloud-results-20260804.md).

The final product is deliberately narrow: **mini-SWE-agent + Aider Repo Map +
one focused Repo Map refresh + Edit V2 deterministic replacement + A1 budget
control + V1R1 verifier repair**, running Qwen3-14B BF16 locally on RadeonX
Cloud. Static RepoGraph remains available as a research-only historical
ablation (`mini-repograph-clean`); it is not part of the product claim.

The final hardware label is **AMD Radeon Graphics (gfx1100), 51.52 GB VRAM,
RadeonX Cloud**. Earlier Qwen3.6 FP8 API results and the `gfx1100` FP8 MoE
loading failure are retained as preliminary evidence only and are not mixed
into the formal harness ranking.

The permitted five-task development-gate recovery is recorded in
[`results/amd-cloud-dev-gate-20260804.md`](results/amd-cloud-dev-gate-20260804.md).
The final product cell passed the engineering gate: 5/5 non-empty patches,
5/5 applied replacements, 38/38 valid J3 actions, and zero integrity or
patch-capture failures. The initial failed rerun remains preserved for an
auditable before/after comparison. The fixed SWE-bench Verified confirmation
has frozen patches and a completed seed-0 official Docker evaluation: both
harnesses resolved 1/20 on this fixed set, while RepoMap Final produced 16/20
patches versus 1/20 for the original runner. This is a small confirmation, not
a claim of statistical significance, and it is not a correctness-improvement
claim: Repo Map increased patch completion and applicability, while Full
Resolve remained unchanged on this small set. The first-ten seed-1 official
stability evaluation remains pending. See
[`results/amd-cloud-verified-confirmation-20260805.md`](results/amd-cloud-verified-confirmation-20260805.md)
for the exact denominator and evaluator caveats.

## Current evidence

The previous five-task API pilot is retained as preliminary engineering
evidence only. The final ranking uses local AMD GPU inference, fixed sampling,
fixed budgets, official evaluator outcomes, and process/efficiency metrics.

## Integrity

- Gold patches, hidden test patches, `FAIL_TO_PASS`, and `PASS_TO_PASS` are
  unavailable to agents and context providers.
- Official evaluation runs only after candidate patches are frozen.
- API keys are never persisted in Qwen Code settings, manifests, or results.
- Every harness receives a fresh workspace and session.
- Infrastructure-incomplete runs do not enter capability rankings.

## License

MIT. The mini-SWE runner began as an adaptation of the MIT-licensed
NousResearch Hermes Agent runner; see [`NOTICE.md`](NOTICE.md).

## Hackathon submission package (Track 2)

This repository is the Track 2 submission for the AMD AI DevMaster
Hackathon 2026. Required materials:

- `Project-Specification.pdf` - application scenarios, agent architecture
  diagram, core capabilities, model and local deployment plan, and AMD
  Radeon / ROCm inference-speed optimization.
- `Poster.pdf` / `Poster.png` - supplementary poster (16:9).
- `demo/radeon-fix-demo.mp4` - 3:38 English demo video of a real run on an
  AMD Radeon gfx1100 instance (terminal + generated-code panel + results).
- This README plus `docs/` - environment configuration, startup guide, and
  dependency list. `JUDGE-START-HERE.md` is the one-page entry point.

Quick start (after the local vLLM server is running):

```bash
./scripts/setup_product.sh
export TRACK2_BASE_URL=http://127.0.0.1:8000/v1
export TRACK2_API_KEY=local-vllm
export TRACK2_MODEL=Qwen3-14B-BF16
radeon-fix --repo /path/to/repo --issue "Describe the bug"
```
