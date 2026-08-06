# Evaluation and Evidence

ProofLaunch separates deterministic mechanism checks, model-quality checks,
human preference, production effect, and competition hardware evidence.

## Evidence levels

| Level | What it can prove | What it cannot prove |
|---|---|---|
| Unit/contract tests | Code behavior and fail-closed boundaries | Creative quality or business impact |
| Deterministic replay | Workflow, approvals, hashes, export | New model inference |
| Model receipts | A named model produced a bound output | Human preference or causal effect |
| Blind human review | Preference under a frozen protocol | General production effect |
| Production observation | Operational outcome in a defined context | Universal causality |
| Live Radeon receipt/video | Hardware and execution path | Product-market or revenue success |

## Release-critical checks

- Product-critical Python tests: `827/827` in the current sealed readiness receipt.
- Route-head Node tests: `10/10`.
- Static web surface: `46` routes and `60` same-origin API contracts in the
  current build. The earlier sealed Aug 3 readiness receipt records `58`.
- Run-bound campaign pack: `10` deliverables.
- Automatic external publish/send/spend actions: `0`.

Canonical current-state evidence is listed in
[`submission/track1-prooflaunch/SUBMISSION_MANIFEST.json`](../submission/track1-prooflaunch/SUBMISSION_MANIFEST.json).
Historical receipts remain supporting material and must not override newer
canonical records.

## Radeon / ROCm evidence boundary

The archived executed Notebook
`notebooks/gemma4_emotion_lora_modelscope_single_gpu_original.ipynb` is bound
to SHA-256
`e2ac1e8b28b587c0d57f9dda2d2e6284733dd4f22b66ab3b6722129243f6cddc`.
Its saved outputs observe one `AMD Radeon Graphics` device, HIP `7.2.53211`,
Gemma-4 inference, a 400-example evaluation and 250 LoRA training steps. Run:

```bash
python3 scripts/validate_radeon_historical_evidence.py
```

This is valid historical component-level execution evidence. It does not
observe a fresh end-to-end ProofLaunch GTM run, Radeon image/video generation,
per-inference latency, peak VRAM or post-training evaluation. See
`evidence/RADEON_EVIDENCE_INDEX.md` for the complete tiered evidence map.

## Reproduce the governed replay

```bash
python demos/run_track1_demo.py
```

Inspect `artifacts/judge-track1-replay-v1/demo-receipt.json` and verify its
content hash. This replay must continue to state
`radeon_execution_observed=false`.

## Competition gate

```bash
python scripts/validate_amd_track1_package.py
```

`structural_status=passed` means the package is internally consistent.
`competition_status=ready` additionally requires the fresh end-to-end Radeon
campaign receipt. The Demo Video and pull-request bytes are present, but neither
substitutes for that missing capture; until it exists, the correct state is
`blocked`.

## Claim policy

The package does not claim 4A preference, Top-1 standing, production effect,
causal revenue, or autonomous business action without the corresponding named
human or production evidence. Generated visuals can target 4A craft while the
formal claim remains unmade.
