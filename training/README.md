# ClaimCourt LoRA Training

This directory builds the `claimcourt-router:8b` adapter. It is not a legal model and it does not replace the Qwen3 32B Q8 judge. Its narrow responsibilities are local task routing, citation-shaped JSON, and secret-safe behavior.

## Data

`generate_claimcourt_sft.py` emits 172 synthetic examples. They cover:

- evidence verdict JSON with citation constraints;
- routing to `evidence_court`, `file_locator`, or `sensitive_record_scan`;
- credential findings that contain only a location, fingerprint, and redacted preview.
- fuzzy memory queries that map incomplete recollections to topics, file types, time hints, event relations, and clarification states.

The generator contains no real private documents or credentials. It also writes `training/data/claimcourt_intent_sft.jsonl`, a 64-example query-only dataset whose JSON contract exactly matches the runtime compiler. Use that focused file for the router adapter; private workspace text is never used as SFT data.

## Train On Radeon Cloud

```bash
python training/generate_claimcourt_sft.py
python training/train_lora.py \
  --model /workspace/models/Qwen3-14B \
  --data training/data/claimcourt_intent_sft.jsonl \
  --output /workspace/claimcourt-models/claimcourt-qwen3-8b-lora
```

## Serve The Adapter

```bash
ollama pull qwen3:8b
ollama create claimcourt-router:8b -f training/Modelfile.claimcourt-router
```

Keep `qwen3:32b-q8_0` as the final evidence judge. The smaller adapter is optimized to choose the right local tool before the court workflow runs.
