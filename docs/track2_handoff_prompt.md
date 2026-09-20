# Track 2 Handoff Notes

The repository root is the project root. Track 2 is no longer nested under a subdirectory.

## Mission

Maintain a domestic-market quantitative assistant running locally on AMD ROCm. Preserve the general-assistant fallback, RAG grounding, multi-agent risk veto, DSL validation, deterministic backtest, and Dify workflow.

## Important constraints

- Do not introduce cloud-only inference into the demo path.
- Do not claim real trading or live execution.
- Keep large model weights outside GitHub; commit checksums and reproducibility metadata instead.
- Keep domestic-market examples and constraints in user-facing documents.
- Do not reintroduce merge-conflict markers into README or technical documents.

## Main paths

```text
src/agent/       ReAct loop, memory, routing, and multi-agent orchestration
src/knowledge_base/  RAG and confidence gating
src/dsl/         Schema, canonicalizer, validator, transpilers
src/backtest/    Backtest and risk metrics
training/        LoRA/DPO data and serving scripts
dify/            OpenAPI tools and workflow guide
tests/           Unit and integration tests
```

## Verification

```bash
bash scripts/verify_e2e.sh
python -m pytest tests/ -v
```
