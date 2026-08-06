# PolicyCut

**A fully local, policy-driven, human-in-the-loop privacy video editor — built for AMD Radeon + ROCm.**

Write your privacy policy in plain English. PolicyCut finds the targets in both the picture and the sound, you confirm or fix its proposal on a dual-track timeline, and it renders a redacted MP4 with redacted subtitles and a machine-readable audit report. Nothing ever leaves your machine.

> AMD Radeon Hackathon 2026 · Track 1 — Multimodal Content Creation Tools

```
"Pixelate every face, license plate, identity document and screen.
 Beep phone numbers, email addresses and street addresses."
        │
        ▼
 upload → interpret policy → automatic analysis → HUMAN REVIEW → render → MP4 + SRT + audit.json
```

## Why PolicyCut

- **Local only.** Faces, IDs, spoken phone numbers — the footage you most need to redact is the footage you least want to upload. All models run on your AMD Radeon GPU via ROCm; the processing path makes zero external API calls.
- **Policy, not buttons.** One English sentence is parsed (Qwen3-4B, strict JSON schema, deterministic fallback) into structured visual + audio rules you confirm before anything runs. Negations work ("do not blur screens"); unsupported targets are surfaced, never silently dropped.
- **Both modalities.** Visual redaction (blur / pixelate / solid) of faces, license plates, ID documents and screens, *and* audio redaction (mute / beep) of spoken phone numbers, email addresses and street addresses — including spoken forms like "five five five … at example dot com".
- **Human in the loop.** Every automatic detection is a pending event on a dual-track timeline. Confirm, ignore, retime, re-effect, add manual regions for anything missed. Export is blocked until every automatic event was reviewed.
- **Auditable.** `audit.json` records models, precision, per-stage timings, peak VRAM, every event and every human correction — with zero PII plaintext inside.

## Models (all local, all on Radeon)

| Stage | Model |
|---|---|
| Policy parsing | `Qwen/Qwen3-4B-Instruct-2507` |
| Open-vocabulary detection | `IDEA-Research/grounding-dino-tiny` (Transformers port — no CUDA custom ops) |
| Small-face assist | YuNet (OpenCV Zoo) — CPU assist detector |
| Mask tracking | `facebook/sam2.1-hiera-small` (`SAM2_BUILD_CUDA=0`) |
| Speech-to-text | `openai/whisper-large-v3-turbo` (word timestamps) |
| PII localisation | regex + spoken-form normalization (+ optional Microsoft Presidio) |

## Requirements

- Linux with an AMD Radeon GPU and a working **ROCm PyTorch** build (developed/benchmarked on a Radeon PRO W7900, 48 GB). CPU-only machines can run the app and unit tests; core model stages then run in fallback mode — fine for development, not for the contest path.
- Python ≥ 3.10, FFmpeg + ffprobe on PATH.
- ~15 GB disk for model weights.

## Setup

```bash
git clone <this repo> && cd policycut

# venv that can SEE the system ROCm torch (do NOT pip install torch over it):
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r requirements-rocm.txt

# verify the GPU path before anything else:
python scripts/preflight.py
# → prints torch.version.hip, GPU name, matmul smoke test, ffmpeg, model cache status

# download models (honors HF_ENDPOINT, e.g. https://hf-mirror.com):
python scripts/download_models.py
```

> **ROCm note:** on ROCm builds of PyTorch, `torch.cuda.*` is the correct, official API — it is the unified GPU namespace, not an NVIDIA dependency.

## Run

```bash
python run.py --host 0.0.0.0 --port 8000 --require-rocm
```

Open `http://localhost:8000`. `--require-rocm` is contest mode: core model stages raise instead of silently falling back to CPU. Omit it for CPU development machines.

Workflow: **Projects → New Project** (upload ≤60 s / ≤1080p video) → type or pick a policy → **Interpret Policy** → confirm the parsed rules → **Start Analysis** → watch stages + GPU metrics live → **Review** (confirm/ignore/retime events, add manual regions, dual-track timeline) → **Complete Review** → **Render** → download `redacted.mp4`, `redacted.srt`, `audit.json` or the ZIP bundle.

## Tests & benchmarks

```bash
pytest tests/unit tests/api          # no GPU / ffmpeg needed
python scripts/make_fixtures.py      # generates 3 synthetic test clips (all PII fake)
python scripts/benchmark.py tests/fixtures/interview.mp4 \
  --policy "Pixelate every face. Beep phone numbers." \
  # → artifacts/benchmarks/benchmark_<ts>.json + markdown table
```

Measured W7900 results live in `docs/benchmark.md` and `artifacts/benchmarks/`.

## Repository layout

```
policycut/            Python package (api, core, policy, vision, audio, media, review, audit, web)
schemas/              JSON Schemas for policy / events / audit
scripts/              download_models, preflight, benchmark, make_fixtures
tests/                unit + api tests, synthetic fixtures
docs/                 architecture, limitations, benchmark, project profile, poster
artifacts/benchmarks/ measured results (JSON)
data/                 (runtime) projects, never committed
```

## Privacy & audit guarantees

- Processing makes **no external network calls**; models are loaded from the local HF cache.
- `redacted.srt` replaces sensitive spans with `[REDACTED: PHONE|EMAIL|ADDRESS|MANUAL]`; the raw transcript is never exported.
- `audit.json` contains hashes, models, timings, VRAM, event/review records — and **no PII plaintext, no raw transcript, no absolute paths**.
- Output MP4 is stripped of input container metadata and ffprobe-validated before an atomic replace.

## Limitations

PolicyCut is a human-in-the-loop redaction tool, **not** a legal compliance guarantee. No face recognition/whitelists, no age estimation, no speaker diarization, no generative inpainting, no live capture. One video per project, ≤60 s, ≤1080p in the contest build. See `docs/limitations.md`.

## License

MIT — see `LICENSE`. Third-party model and library licenses in `THIRD_PARTY_NOTICES.md`.
