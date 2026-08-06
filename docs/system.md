# System SSOT

## Architecture
```text
Trusted local documents
  -> policy-controlled workspace scanner (scope, symlinks, size, exclusions, diagnostics)
  -> parser and chunker
  -> durable JSON evidence ledger + SQLite FTS5, hybrid child retrieval and parent context
  -> local fuzzy intent compiler (query only)
     -> multi-hypothesis hybrid ranking -> calibrated select / clarify / abstain / compare
     -> owner feedback ledger -> hard-negative reranker review queue
     -> file family ranking -> all-chunk cited artifact summary
     -> redacted sensitive-record scan
     -> controlled evidence packet -> prosecution -> defense -> judge
  -> strict schema/citation validation and quality warnings
  -> explicit approval -> local Markdown brief
```

## Tech Stack
- Frontend: Streamlit.
- Backend: Python 3.10+, requests, structured JSON workflow.
- Data: JSON evidence ledger with source hashes, adjacent SQLite FTS5 acceleration, in-memory TF-IDF/BM25/embedding matrices; source files remain local to the deployment boundary.
- Inference: OpenAI-compatible local vLLM endpoint on AMD Radeon GPU + ROCm; the verified target is Qwen3-14B BF16 with a query-only ClaimCourt LoRA served by the same vLLM process.
- Infrastructure: Radeon Cloud `ROCm vLLM-dev (Navi)` image; SSH tunnel is the reliable private browser access path when cloud web routing fails.

## Important Commands
```bash
# install
cd claimcourt
python -m pip install -r requirements.txt

# test
python -m unittest discover -s tests -t . -q
python scripts/adversarial_holdout_check.py

# local vLLM target on Radeon Cloud
vllm serve /workspace/models/Qwen3-14B --host 0.0.0.0 --port 8000 --dtype bfloat16 --gpu-memory-utilization 0.90 --max-model-len 8192 --enable-lora --lora-modules claimcourt-intent=/workspace/claimcourt-models/claimcourt-qwen3-14b-intent-lora

# UI
streamlit run app.py --server.address 127.0.0.1 --server.port 8502

# strict Radeon holdout; requires LoRA + BGE + local reranker
CLAIMCOURT_RERANKER_MODEL=/workspace/models/bge-reranker-base bash scripts/run_radeon_holdout.sh
```

## Data Model
- `Evidence`: citation, source, text, relevance score, optional date, structural parent ID, child position, and optional merged parent context.
- `Case`: user claim, retrieved packet, role outputs, verdict, model-quality failures, telemetry, and export approval state.
- `Artifact summary`: selected source/path, cited overview, cited key points, all-chunk pass count, and local inference telemetry.
- `IntentPlan`: route, request mode (single/inventory/existence), artifact types, required/excluded file roles, topics with all/any semantics, excluded topics, entities, time hints, causal/temporal relations, memory signals, expanded terms, confidence, and clarification state. Hybrid similarity performs broad recall; deterministic per-file constraints are the non-bypassable boundary before auto-selection.
- `RetrievalDecision`: confident, ambiguous, multiple_matches, or no_match; calibrated confidence, top score, score margin, reason, and clarification prompt.
- `Verdict`: supported, contradicted, or insufficient_evidence; confidence; reasoning; citations; contradictions; timeline; missing evidence; recommended action.

## Integrations
- Local OpenAI-compatible vLLM API only. No closed remote model API is permitted.
- Radeon Cloud is an execution environment, not a data source.

## Deployment
- Primary: Radeon Cloud GPU inference with a local browser connection through SSH port forwarding.
- Browser route: `ssh -L 8502:127.0.0.1:8502 ...`, then open `http://localhost:8502`.
- Fallback: deterministic, visibly labeled demo mode when the local LLM endpoint is unavailable. It is for reliability, not a substitute for GPU inference scoring.

## Guardrails
- Auth/security: Bind the UI and model services to loopback. Non-loopback model endpoints are blocked unless their host appears in `CLAIMCOURT_TRUSTED_ENDPOINTS`; do not expose the UI publicly with real evidence.
- Data safety: Parse/index in process; only export after explicit approval; reject citations absent from the packet; block public model endpoints and redact credential-like text before model/UI/export output.
- Cost/latency: Capture first-token latency, end-to-end latency, completion tokens, output tokens/s, model dtype/quantization, GPU architecture, and ROCm/HIP/vLLM versions; preserve model cache and avoid instance restarts.
- Optional quality layers: local cross-encoder reranking and PyMuPDF/Tesseract OCR are lazy and fail closed to the deterministic hybrid index.
- Fallback policy: deterministic fallback is restricted to the synthetic corpus and is never silently used for a real workspace.
- Training boundary: the optional intent LoRA is trained from synthetic query-to-plan examples only; private workspace contents never enter SFT data or model prompts during compilation.
- Feedback boundary: owner relevance feedback stays in the local index ledger and is queued for reranker review; it is never automatically copied into public training data.
- Filesystem scope: only an explicitly selected root is scanned; dependency/cache directories are excluded, symlinks and junctions are not followed, large-file and file-count limits are explicit, and skip reasons are rendered in the UI.
- Rollback: Source and demo corpus live in Git; archive before cloud changes; stop only app processes, never destroy a working instance without preserving evidence.
