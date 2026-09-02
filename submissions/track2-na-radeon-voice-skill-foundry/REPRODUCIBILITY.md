# Reproducibility

This file lists the commands and artifacts a reviewer can use to reproduce the
current submission package.

## Environment

- Node.js 20 or newer
- npm 10 or newer
- Python 3
- `pdftotext` for PDF text validation
- Optional: Radeon/ROCm environment for reproducing GPU measurements

Install source dependencies:

```bash
npm ci
```

## Full Local Verification

```bash
npm run verify:submission
```

This command performs:

1. reads the committed `SHA256SUMS.txt`
2. downloads only missing large media from the fixed `submission` Release
3. rejects any downloaded asset whose SHA-256 differs from the manifest
4. runs `npm run evidence:agent-harness`
5. runs `npm test` (68 tests) and the Supervisor-watchdog fault simulation
6. runs the typecheck and production build
7. regenerates and checks `submission/SHA256SUMS.txt`
8. validates the three-hour public-health evidence and unedited W7900 run
9. validates independently scheduled GitHub health-run history
10. runs `pdftotext` checks for current P0 proof text

This makes the command work from a clean source clone even though large videos
are distributed as GitHub Release assets instead of Git objects.

## Evidence Generation

Generate the governed harness repair proof:

```bash
npm run evidence:agent-harness
```

Outputs:

- `submission/AGENT_HARNESS_REPAIR_EVIDENCE.json`
- `submission/AGENT_HARNESS_REPAIR_PROOF.zip`

Expected behavior:

1. Revision 1 is deliberately modified to allow `mail:send`.
2. Verification quarantines revision 1.
3. The verifier emits one repairable permission finding.
4. The server creates revision 2 with `source: verifier`.
5. Revision 2 restores `mail:send = deny` and verifies.

Generate checksum manifest:

```bash
python3 scripts/generate_submission_checksums.py
```

Validate finalized artifacts:

```bash
cd submission
shasum -a 256 -c SHA256SUMS.txt
```

## PDF Assets

The project specification PDF is built from `submission/PROJECT_SPECIFICATION.md`:

```bash
python3 scripts/build_submission_assets.py
```

If local Python lacks `reportlab`, use the bundled Codex Python runtime or
install `reportlab` and `Pillow` before running the builder.

## Radeon Measurements

The Radeon measurements are already included as frozen evidence in:

- `submission/evidence/HARDWARE_BENCHMARK.json`
- `submission/evidence/RADEON_SERVING_AND_ASR_SUMMARY.json`
- `submission/evidence/QUARK_QUANTIZATION_SUMMARY.json`
- `submission/evidence/ADAPTIVE_PRECISION_SUMMARY.json`
- `submission/evidence/ADAPTIVE_PRECISION_E2E.json`
- `submission/LIVE_RADEON_RECOVERY_EVIDENCE.json`

The main reported values are:

- Agent median TTFT: 108.87 ms
- Agent median generation throughput: 22.02 tokens/s
- ASR warm median RTF: 0.0556, or 17.98x real-time
- vLLM graph concurrency-eight: 257.65 output tokens/s
- Serialized Transformers concurrency-eight: 20.66 output tokens/s
- Native ASR batch-eight: 85.35x aggregate real-time

These are pinned evidence results. Re-running them requires a matching Radeon
Cloud ROCm environment and the scripts under `scripts/radeon_*`.
