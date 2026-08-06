# ClaimCourt: A Private Local AI Evidence Court

**Team:** Zi Fei Yu

**Competition:** AMD AI DevMaster Hackathon 2026

**Track:** Track 2 - Development & Local Deployment of Private AI Agents

> A private evidence-grounded agent that compiles fuzzy human recollections into local search plans, finds the right records, and turns disputed commitments into cited verdicts, contradiction timelines, and approval-gated briefs.

ClaimCourt keeps documents, embeddings, prompts, retrieval history, model inference, and generated reports inside the selected private deployment boundary. Its verified competition stack runs on an AMD Radeon PRO W7900-class GPU with ROCm and does not depend on a closed remote model API.

The current release is a **private alpha**. The retrieval, evidence, privacy, and agent workflows are real implementations. Encryption at rest, authenticated multi-user isolation, and background synchronization remain post-hackathon production gates.

## Why ClaimCourt

Private knowledge work rarely starts with a perfect filename or a single authoritative document. A user may remember only that a presentation discussed a delayed launch, or that sales mentioned an uptime target while the signed contract did not. A conventional chatbot can produce a fluent answer, but it does not reliably distinguish drafts from final records, marketing language from contractual obligations, or evidence from missing evidence.

ClaimCourt addresses two connected problems:

1. **Fuzzy private memory retrieval:** compile incomplete human recollections into a structured local intent plan and locate the correct file family without guessing.
2. **Evidence-grounded decision support:** retrieve cited evidence, run constrained prosecution and defense stages, and let a judge stage issue only a schema-valid verdict supported by the retrieved packet.

## Verified Radeon Result

- **GPU:** AMD Radeon PRO W7900 class, `gfx1100`, 51.52 GB VRAM.
- **Judge:** `Qwen3-14B`, BF16, vLLM + ROCm, with the ClaimCourt query-intent LoRA loaded in the same service.
- **Retrieval models:** `BAAI/bge-small-zh-v1.5` through the vLLM pooling runner and a local `bge-reranker-base` cross-encoder.
- **Live fuzzy-intent gate:** 320/320 synthetic adversarial queries passed; live Router, embedding, and reranker checks all passed; unsafe wrong auto-selections: 0.
- **Live court gate:** first-token latency `0.27 s`, generation throughput `14.3 tokens/s`, 1,778 completion tokens, and `126.44 s` end-to-end for the complete three-role court run.
- **Expected championship verdict:** `insufficient_evidence` for a claimed 99.9% contractual uptime commitment.

The machine-readable receipts are available in [`docs/evidence/radeon-championship-live-20260805.json`](docs/evidence/radeon-championship-live-20260805.json) and [`docs/evidence/radeon-fuzzy-holdout-live-20260805.json`](docs/evidence/radeon-fuzzy-holdout-live-20260805.json).

## Submission Materials

- [Project description PDF](submission/ClaimCourt_Project_Description.pdf)
- [Presentation deck](submission/ClaimCourt_Presentation.pptx)
- [Presentation PDF preview](submission/ClaimCourt_Presentation.pdf)
- [Demo recording script](submission/DEMO_SCRIPT.md)
- [Demo video on YouTube](https://youtu.be/Do_LJsUSFnQ)

## What it demonstrates

- **Local workspace retrieval:** recursive local indexing of PDF, DOCX, PPTX, TXT, Markdown, and EML files; PDF pages and PPTX slides retain local locators.
- **Controlled tool workflow:** prosecutor, defense, and judge steps are separate constrained calls.
- **Multi-step planning:** retrieve -> prosecution -> defense -> judge -> approval-gated export.
- **Local memory:** the indexed evidence and court record remain in the current session on the host.
- **Privacy and permissions:** no document leaves the machine; a local decision brief is written only after the user checks the approval control.
- **Citation guardrail:** the judge may cite only IDs supplied in the retrieved evidence packet. Unknown citations are removed before rendering or export.
- **Evidence ledger:** every rendered source and excerpt carries a local SHA-256 hash and chunk locator; approved briefs include this ledger for later verification.
- **Secret-location tool:** deterministic local scanning finds likely private keys and credentials, but returns only a file location, category, fingerprint, and redacted preview.
- **Runtime proof:** the UI displays GPU model and architecture, ROCm/HIP/vLLM versions, VRAM, dtype, quantization, context, first-token latency, end-to-end latency, completion tokens, and throughput.
- **Specialized local router:** a Qwen3-14B LoRA adapter is trained locally on synthetic query-to-intent plans. It compiles fuzzy requests; the verified local Qwen3-14B vLLM service remains the final judge.
- **Unified private request:** one request routes to evidence court, file location, or a redacted sensitive-record scan without sending workspace contents outside the instance.
- **Semantic memory finder:** vague requests such as “find the PPT I wrote about customer delay and Q4 risk” are converted into a transparent local intent plan, expanded concepts, file-type constraints, hybrid relevance scores, and human-readable match reasons.
- **Grounded artifact summary:** after a confident file match, every indexed chunk from that file is read by the local model. Long files use cited section digests before a final cited overview; real files never receive a fabricated fallback summary.
- **Fuzzy intent compiler:** a local Qwen/ClaimCourt LoRA adapter may compile topics, entities, time hints, causal relations, query expansions, and clarification needs. A deterministic privacy-safe compiler remains the transparent fallback and never receives document contents.
- **Optional local embeddings:** when a loopback Ollama /api/embed or vLLM /v1/embeddings endpoint is configured, embedding similarity is blended with lexical retrieval; an unavailable endpoint falls back without sending data elsewhere.
- **Query memory:** local query plans, result identities, confidence, embedding/reranker status, and failure diagnostics are persisted with the workspace index for replay and audit.
- **File-family grouping:** similar copies and version-like names are grouped so a PDF export, draft, and final presentation do not appear as unrelated discoveries.
- **Accumulating workspace memory:** the local index persists source hashes, current evidence, and prior-version excerpts across refreshes; changed files are marked and re-indexed instead of silently reusing stale evidence.
- **Measurable retrieval gain:** the synthetic championship benchmark compares the intent compiler with raw BM25 on eight hard queries, including Chinese paraphrases, signed-vs-draft version selection, and event relations.

## Architecture

```text
Local PDF / DOCX / TXT / MD / EML
          |
  parse + chunk + local retrieval
          |
  retrieved evidence packet with citation IDs
          |
  prosecution -> defense -> judge (same local instruction model)
          |
cited verdict + contradictions + timeline + missing evidence
          |
local evidence ledger + redacted sensitive-record locator
          |
explicit user approval -> local Markdown decision brief
```

## Quick demo

```bash
cd claimcourt
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Click **Load stable demo case**, then ask:

> Did the vendor contractually commit to 99.9% uptime?

The included corpus intentionally produces `Insufficient Evidence`: sales language is marketing, meeting notes describe a conditional future target, and the agreement requires a signed SLA addendum.

For the championship acceptance run, build the larger multi-file workspace and run its gate:

    python scripts/build_championship_corpus.py
    python scripts/championship_check.py --output championship_results.json

To inspect the fuzzy-semantic gain independently:

    python scripts/fuzzy_retrieval_check.py --output fuzzy_results.json

The current synthetic gate reports 100% Top-1 and Recall@3 for the intent-aware path versus a 62.5% Top-1 and 75% Recall@3 raw BM25 baseline. This is a benchmark on synthetic data, not a claim of universal accuracy.

The 2026-08-05 private-alpha gate uses 60 rows against 180 real local sources without committing queries, paths, labels, or document text. It reports 100% single-target Top-1 (37 cases), 100% Recall@5 (40 positive cases), 100% multi-target full coverage (3 cases), 100% no-answer abstention (12 cases), and 100% auto-selection precision at 85% coverage. The sanitized receipt is `docs/evidence/private-retrieval-20260805.sanitized.json`; owner label review remains a release requirement.

The live release gate additionally requires the local embedding and judge endpoints:

    python scripts/championship_check.py \
      --embedding-endpoint http://localhost:8001/v1 \
      --embedding-model /workspace/models/bge-small-zh-v1.5 \
      --judge-endpoint http://localhost:8000/v1 \
      --judge-model Qwen3-14B \
      --require-live-judge

The synthetic demo corpus includes an explicitly labeled deterministic fallback so the UI can be reviewed before the GPU server is ready. Real workspaces and artifact summaries fail closed when the local model is unavailable. For the competition demo, start the local ROCm service below; the court record then reports the active local runtime and Radeon performance evidence.

## Radeon Cloud / ROCm deployment

Select **ROCm vLLM-dev (Navi)** in Radeon Cloud. First validate the instance:

```bash
rocminfo
python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
vllm --version
```

For the Radeon PRO W7900 instance, the verified competition configuration is Qwen3-14B BF16 in vLLM with the ClaimCourt intent LoRA. The base weights are about 29.54 GB; the complete judge, router, embedding, and API stack peaked at approximately 45.3 / 51.52 GB reported VRAM. Ollama remains an optional compatibility runtime, but it is not the verified submission path.

```bash
export PATH=/workspace/ollama-runtime/bin:$PATH
export LD_LIBRARY_PATH=/workspace/ollama-runtime/lib:$LD_LIBRARY_PATH
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_MODELS=/workspace/ollama-models
ollama serve
```

In a second terminal, pull and verify the model:

```bash
ollama pull qwen3:32b-q8_0
ollama run qwen3:32b-q8_0 "Return JSON only: {\"status\": \"ready\"}"
ollama ps
rocm-smi
```

For semantic retrieval in the optional Ollama compatibility path, run a local embedding model and enable **Use local semantic embeddings** in the sidebar:

    ollama pull nomic-embed-text

The embedding endpoint is http://localhost:11434 with model nomic-embed-text. This is optional; the app keeps a deterministic hybrid fallback when the embedding model is not loaded.

On the Radeon Cloud deployment, the verified configuration uses vLLM's pooling runner:

    vllm serve /workspace/models/bge-small-zh-v1.5 --runner pooling --host 0.0.0.0 --port 8001 --dtype bfloat16 --gpu-memory-utilization 0.10 --max-model-len 512

Use http://localhost:8001/v1 and model /workspace/models/bge-small-zh-v1.5 in ClaimCourt. The endpoint exposes /v1/embeddings and returns 512-dimensional vectors.

ClaimCourt also maintains a durable SQLite FTS5 index beside the JSON ledger. The
index is rebuilt from the hashed evidence after every ingestion, so it can be
deleted and regenerated without losing the audit history. Retrieval first uses
hybrid lexical/embedding scores, then optionally reranks a shortlist with a local
`sentence-transformers` cross-encoder. To enable that path, install the optional
package and point the UI at a model already present in the private model cache:

```bash
python -m pip install sentence-transformers
# optional, for scanned PDFs:
python -m pip install pymupdf pytesseract pillow
# the tesseract executable and the selected language packs must also be local
```

Every retrieved child chunk carries its structural parent and neighboring context
in the evidence packet. This keeps citations anchored to a small chunk while
giving the judge enough surrounding text to distinguish an exception clause from
the sentence immediately before it.

The verified vLLM judge is served with:

```bash
export VLLM_ATTENTION_BACKEND=TRITON_ATTN
vllm serve /workspace/models/Qwen3-14B \
  --host 0.0.0.0 \
  --port 8000 \
  --dtype bfloat16 \
  --gpu-memory-utilization 0.82 \
  --max-model-len 8192 \
  --served-model-name Qwen3-14B \
  --enforce-eager
```

Start the interface, select **vLLM ROCm**, and use `http://localhost:8000/v1` with model `Qwen3-14B`. The app sends `enable_thinking=false` for the court calls so the structured JSON contract is not polluted by a reasoning stream.

For constrained VRAM, prefer a supported AWQ/GPTQ quantized Qwen3 checkpoint and pass its documented `--quantization` option. Measure and record first-token latency and output tokens/second on the app's court request. This is evidence for the AMD/ROCm performance scoring section.

Run the UI in a second terminal:

```bash
streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Set the sidebar endpoint to `http://localhost:8000/v1` (or the private instance address), select **vLLM ROCm**, and enable local GPU inference. ClaimCourt intentionally does not accept a cloud-model API key.

## Optional ClaimCourt LoRA

The `training/` directory contains the reproduced local LoRA specialization path for `Qwen3-14B`. It is deliberately narrow: route local requests to the court, file locator, or redacted secret scanner. It does not replace the evidence judge.

```bash
python training/generate_claimcourt_sft.py
python training/train_lora.py \
  --model /workspace/models/Qwen3-14B \
  --data training/data/claimcourt_intent_sft.jsonl \
  --output /workspace/claimcourt-models/claimcourt-qwen3-14b-intent-lora
```

See `training/README.md` for adapter serving instructions and dataset scope. Workspace evidence history and prior-version archive are stored locally under `data/workspace_index.json`.

## Tests

```bash
cd claimcourt
python -m unittest discover -s tests -v
python scripts/adversarial_holdout_check.py
```

The frozen synthetic fuzzy-intent holdout contains 320 queries across ten failure categories. On Radeon Cloud, require the live LoRA router, BGE embedding, and local cross-encoder instead of accepting deterministic fallback:

```bash
export CLAIMCOURT_RERANKER_MODEL=/workspace/models/bge-reranker-base
bash scripts/run_radeon_holdout.sh
```

The command exits non-zero if any live component is missing or silently falls back. The public sanitized receipt is `docs/evidence/fuzzy-holdout-20260805.json`.

## Privacy model

Documents are parsed and indexed in process. Retrieval data, prompts, structured arguments, and reports remain on the current host. Model endpoints are loopback-only by default; a non-loopback host must be explicitly listed in `CLAIMCOURT_TRUSTED_ENDPOINTS`. The interface only permits a report file write after explicit approval. Keep the UI bound to localhost and use an SSH tunnel; do not expose a real-document workspace to the public internet.

## Submission checklist

- Fork `AMD-DEV-CONTEST/Radeon-hackathon-2026-07` and add this project.
- Use PR title: `Track 2, Zi Fei Yu, ClaimCourt`.
- Submit all materials in English: source, this README, a project specification PDF, demo video, and a poster or PPT.
- In the video, show `rocminfo`, the local ROCm runtime, Qwen3-14B BF16 resident on the Radeon GPU, the live GPU-backed verdict, and generated telemetry.
