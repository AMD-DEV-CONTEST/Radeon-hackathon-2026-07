# Case Log: Fix championship critical paths

## Intent

Make the real-workspace story credible: locate Chinese credentials without disclosure, recover and summarize a vaguely remembered report, fail closed on malformed model output, preserve retrieved evidence after model failure, and expose verifiable Radeon runtime facts.

Risk: medium. These changes affect privacy routing, model contracts, UI state, and performance evidence.

## Contract

- Real documents never use deterministic verdict or summary fallback.
- Only loopback model endpoints are trusted by default.
- Unknown model citations are removed and surfaced as quality failures.
- Retrieved evidence remains inspectable if a downstream model call fails.
- No Git commit or push is performed without owner approval.

## Changes

- Added Chinese assigned-credential detection, query-aware ranking, full paths, fingerprints, and redacted output.
- Added strict role, verdict enum, timeline, and citation validation.
- Added an all-chunk local artifact summary with hierarchical passes for long files.
- Added operating-system coursework intent expansion and a realistic retrieval regression test.
- Added persistent public-exposure warning and loopback-first endpoint policy.
- Added GPU architecture, ROCm/HIP/vLLM, dtype, quantization, VRAM, context, end-to-end latency, and completion-token evidence.

## Verification

- `python -m py_compile core.py app.py scripts/championship_check.py tests/test_core.py`
- `python -m unittest discover -s tests -v`
- `python scripts/championship_check.py`
- Championship corpus: 23 files, 30 chunks, FTS5 active, final Q4 PPT ranked first, sensitive result redacted.

## Residual Risk

- The local Windows environment does not have Streamlit installed, so browser-level UI verification must run on the Radeon Cloud instance.
- Live Qwen/vLLM structured output, OCR binaries, embedding endpoint, and optional reranker still require the final Radeon deployment gate.
