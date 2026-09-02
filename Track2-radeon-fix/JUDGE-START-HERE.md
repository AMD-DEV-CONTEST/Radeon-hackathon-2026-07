# radeon-fix - Judge Start Here

**One line:** radeon-fix is a private, CLI-driven AI code-repair agent that
fixes a local git repository from a plain-text issue, using one local
Qwen3-14B BF16 model on an AMD Radeon GPU (ROCm + vLLM). Your code never
leaves the machine.

## 90-second quickstart

```bash
# 1) Reproducible setup (main venv + Aider Repo Map venv + smoke test)
./scripts/setup_product.sh

# 2) Start the local vLLM endpoint (or use your running instance)
export TRACK2_BASE_URL=http://127.0.0.1:8000/v1
export TRACK2_API_KEY=local-vllm
export TRACK2_MODEL=Qwen3-14B-BF16

# 3) Repair a repository; an optional final test command makes the result auditable
radeon-fix --repo /path/to/repo --issue "Describe the bug" \
  --final-test-cmd "python -m pytest -q"
```

Output: `patch.diff`, `report.md`, `trajectory.json`, `run.json`, `gpu.json`.
Exit codes: `0` verified patch, `1` no patch, `2` fatal error, `3` patch
produced but verification/final check failed.

## Watch first

`demo/radeon-fix-demo.mp4` (3-4 minutes): a real repair session on the AMD
Radeon instance - terminal shows every action, generated code appears on the
right panel, and the final pytest check shows all repository tests passing.

## AMD Radeon evidence

- Hardware: AMD Radeon Graphics (gfx1100), 51.52 GB VRAM, RadeonX Cloud.
- Runtime: ROCm 7.2.2, PyTorch 2.11.0+rocm7.2.2, vLLM 0.25.1, loopback-only
  endpoint, INT8 per-token-head KV cache, prefix caching, xgrammar J3.
- Measured: TTFT p50 103.97 ms, decode p50 25.66 tok/s; prefix caching cut
  TTFT from 3,976 ms to 219 ms at 4K input and 43,568 ms to 562 ms at 16K
  input on the fixed repeated-prefix probe (not an end-to-end speedup claim).
- Details: `docs/amd-cloud-results-20260804.md`,
  `docs/product.md`, `Project-Specification.pdf`, `Poster.pdf`.

## Key capabilities

- Temporary git clone; the original repository is never modified.
- C1R1: Aider Repo Map (2048 tokens) plus one focused refresh.
- J3: xgrammar-constrained structured actions; Edit V2 exact replacement.
- A1 budget controller; V1R1 deterministic verifier (patch apply,
  `git diff --check`, `py_compile` - it does not run tests).
- Optional `--final-test-cmd` provides an auditable post-agent test run.

## Real benchmark (honest numbers)

- Five-task development gate: 5/5 non-empty patches, 5/5 applied exact
  replacements, 38/38 valid J3 actions, zero integrity failures.
- SWE-bench Verified fixed 20-task seed-0 confirmation: RepoMap Final
  produced 16/20 non-empty patches (vs 1/20 baseline) and 189/189 valid
  structured actions; official Docker evaluation resolved 1/20 for both
  harnesses on this small fixed set. Patch completion improved; Full Resolve
  did not change - do not read this as a correctness improvement claim.
- Demo fixture (examples/demo_project, 3 bugs / 7 tests): repaired on the AMD
  instance; patch applies and all 7 tests pass.

## Known limitations

- V1R1 verifier does not execute tests; use `--final-test-cmd` for test
  evidence. The demo shows this final check.
- Local tool execution is command-guarded (network/package/absolute-path
  rules, secret-stripped environment), not an OS-level sandbox. A Docker
  environment is available for stronger isolation.
- `--final-test-cmd` runs in the temporary clone with committed Git state;
  uncommitted/ignored files are not included.
- Repo Map requires the full setup in `scripts/setup_product.sh`; without it
  the run continues with `context_available=false` and a warning.
