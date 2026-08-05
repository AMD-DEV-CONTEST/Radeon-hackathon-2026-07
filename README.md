# ExamLens

A private, fully-local VLM agent that turns scanned exam papers into
ready-to-teach PowerPoint lecture decks. Runs 100% offline on an AMD
Radeon GPU (ROCm + vLLM).

## Requirements
- AMD Radeon GPU with ROCm, vLLM ROCm build
- Python 3.10+
- pip install vllm transformers Pillow python-pptx

## Run
1. Put scanned exam pages (1.png .. 8.png) into the questions folder.
2. python gen_explain.py - VLM agent solves the paper and transcribes
   all 23 questions into explanations.json (whitelist filter + JSON
   salvage parser + retries).
3. python make_ppt.py - renders a 40+ slide lecture deck (original
   text / answers / explanations / common mistakes / scanned appendix).

## Files
- gen_explain.py : VLM transcription agent
- make_ppt.py : slide renderer
- explanations.json : incremental agent state

## Design Notes
- Deterministic decoding (temperature 0.1), per-question prompts,
  two-attempt retries.
- Page-to-question whitelist blocks hallucinated question numbers.
- State saved after every step: crash-safe and idempotent.
