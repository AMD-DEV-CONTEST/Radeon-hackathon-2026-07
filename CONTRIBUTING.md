# Contributing to Bunker

Thanks for contributing to Bunker! This project is an AMD AI DevMaster
Hackathon entry, so changes must stay aligned with the competition framing:
fully local inference on AMD Radeon GPUs via ROCm, with zero data exfiltration.

## Before You Start

Read `docs/AGENT_REVIEW_CHECKLIST.md`. Every change is expected to satisfy its
conventions (source-grounded RAG, strictly local inference backend, statistical
integration testing) before it is considered review-ready.

## Development Setup

```bash
python -m venv .venv310
.venv310\Scripts\activate        # Windows
pip install -r requirements.txt
```

## Adding a New MCP Tool

1. Add the tool function in `src/tools/`.
2. Wrap it as a permission-gated DSPy tool in `src/tools/dspy_tools.py`
   (mirror the existing wrappers: audit + data-flow event, then
   `PermissionController.gate()` for dangerous operations).
3. Register the tool metadata in `src/tools/registry.py`.
4. Add tests under `tests/` covering both the success path and the permission
   "Deny" path.

## Running Tests

```bash
make test-unit        # offline gate (no GPU, no model required)
make test-security    # prompt injection + PermissionController "Deny" path
make test-negative    # graceful-degradation paths
make test-compile     # DSPy compile pipeline smoke test
make test-bdd         # behave/Gherkin acceptance suite
make test-all         # every layer, end to end
```

Integration/perf/eval tests require a live local vLLM server on `:8000` (or an
AMD GPU) and skip cleanly when it is unavailable.

## Pull Requests

- Fork the repo, create a feature branch, and open a PR against `master`.
- Keep changes focused; include a short description of the change and the
  tests you ran.
- Do not commit secrets, `.env` files, model weights, or `demo/video_assets/`
  (all gitignored).
- Never upgrade PyTorch or vLLM without verifying ROCm compatibility first.

## Code of Conduct

Keep contributions professional and constructive. Harassment or inappropriate
behavior is not welcome and may result in removal.
