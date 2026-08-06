# PolicyCut — Policy-Driven Local Privacy Video Editor

**AMD Radeon Hackathon 2026 — Track 1: Multimodal Content Creation Tools**

---

## 1. Project Background

Video is the default medium for journalism, education, research, corporate communication and customer support — and almost every real-world recording contains personal data: faces of bystanders, license plates, ID documents left on a desk, a monitor showing internal dashboards, a spoken phone number or home address. Publishing or sharing such footage without redaction creates legal exposure (GDPR, PIPL, FERPA-adjacent policies) and real harm to the people captured.

Today's options are poor:

- **Manual editing** (masking objects frame by frame in an NLE) is accurate but takes hours per minute of footage.
- **Cloud redaction services** are fast but require uploading exactly the sensitive footage you are trying to protect — often a non-starter for newsrooms, schools, hospitals and research labs.
- **Single-model demos** (a face blurrer, a transcript scrubber) each cover one modality with no review step, no audit trail and no way to express *what* should be redacted.

**PolicyCut** closes this gap: a fully local, human-in-the-loop privacy editor. The user writes a privacy policy in plain English — *"Pixelate every face, license plate, identity document and screen. Beep phone numbers, email addresses and street addresses."* — and PolicyCut turns it into structured rules, finds the targets in both the video and the audio track, lets a human confirm, correct and complete the machine's proposal, then renders a redacted MP4 with redacted subtitles and a machine-readable audit report. Every model runs locally on an AMD Radeon GPU via ROCm; no frame, no audio sample and no transcript ever leaves the machine.

## 2. Target Users & Application Scenarios

| User | Scenario |
|---|---|
| Newsrooms & documentary teams | Blur bystander faces and plates in street footage before broadcast; beep spoken contact details of sources |
| Schools & universities | Redact students' faces and IDs in classroom or campus recordings before sharing with parents or on public channels |
| Research labs | De-identify study recordings (interviews, driving studies) before archiving or data sharing, with an audit file for the ethics board |
| Enterprises | Scrub screens, badges and spoken customer PII from meeting recordings, screen captures and support-call videos |
| Public sector | Prepare bodycam / CCTV excerpts for disclosure with a verifiable record of what was redacted and why |

Common requirements across all of these users: the footage must stay on-premises, a human must remain accountable for the final cut, and the organization needs evidence of the redaction process — exactly the three properties PolicyCut is built around (local-only, human-in-the-loop, audited).

## 3. System Architecture

```
Browser (vanilla HTML/CSS/JS)
 ├─ Projects / New Project (upload + policy)
 ├─ Processing (SSE progress, stage metrics)
 ├─ Review Workspace (video + canvas overlay, dual-track timeline, event editing)
 └─ Export (render, downloads, audit stats)
          │  REST + SSE (/api/v1)
FastAPI backend (single process, single-GPU job queue)
 ├─ policy/   Qwen3-4B → strict JSON PolicySpec → deterministic keyword fallback
 ├─ media/    ffprobe validation, CFR normalization ≤1080p, analysis proxy ≤1280,
 │            thumbnail, 16 kHz ASR WAV, scene-cut detection
 ├─ vision/   Grounding DINO (open-vocabulary keyframe detection)
 │            + YuNet (small-face CPU assist) → NMS → greedy track association
 │            → SAM 2.1 mask propagation (box-interpolation fallback)
 │            → mask post-processing (fill, dilate, feather, safety-box union)
 ├─ audio/    Whisper large-v3-turbo word-level transcription
 │            → spoken-form normalization ("five five five…" → digits)
 │            → PII localisation (regex + heuristics + optional Presidio)
 ├─ review/   overlay preview renderer (boxes + audio banners burned in)
 ├─ media/render  OpenCV frame effects (blur / pixelate / solid, priority solid>pixelate>blur)
 │            + sample-accurate audio mute/beep (1 kHz, −12 dBFS, 10 ms fades)
 │            → libx264/AAC mux, metadata stripped, ffprobe-validated atomic replace
 └─ audit/    audit.json (models, precision, timings, VRAM, events, review history counts —
              zero PII plaintext), redacted.srt, ZIP bundle
Storage: atomic JSON + compressed NPZ masks under data/projects/<id>/ (no database)
```

**Analysis pipeline order** (sequential model loading to bound VRAM):
`NORMALIZING → PARSING_POLICY → TRANSCRIBING → DETECTING_PII → DETECTING_VISUAL → TRACKING → BUILDING_PREVIEW → REVIEW_READY`

**The human loop is a first-class stage, not an afterthought**: every automatic event starts `pending`; export is blocked until each one is confirmed or ignored. Reviewers can retime events, change effects, re-categorize, add fixed manual regions for missed objects and add manual audio intervals. Every mutation is revision-checked (HTTP 409 on conflict), journaled to `review_history.jsonl`, and immediately marks previous exports as stale.

## 4. Models & Algorithms

| Stage | Model / method | Why this choice |
|---|---|---|
| Policy → rules | **Qwen/Qwen3-4B-Instruct-2507**, greedy decoding, strict JSON schema, one repair round, then deterministic keyword parser with negation handling | Small enough to co-reside with vision models on one GPU; the deterministic fallback guarantees a valid PolicySpec 100% of the time |
| Open-vocabulary detection | **IDEA-Research/grounding-dino-tiny** (Hugging Face Transformers port) | Text-prompted detection covers faces, plates, ID documents and screens with one model; the Transformers port avoids the original CUDA-only custom ops, so it runs unmodified on ROCm |
| Small-face assist | **YuNet** (OpenCV Zoo, CPU) | Catches small/profile faces below DINO's reliable size; explicitly a CPU assist detector |
| Mask tracking | **facebook/sam2.1-hiera-small** video propagation, `SAM2_BUILD_CUDA=0` (no CUDA extension; connected-component post-processing in OpenCV) | Pixel-accurate masks between keyframes; small variant keeps VRAM headroom; automatic box-interpolation fallback guarantees no unprotected frames |
| Speech-to-text | **openai/whisper-large-v3-turbo**, word timestamps | Word-level timing is what makes surgical audio redaction possible; turbo variant keeps real-time factor low |
| PII localisation | Regex + spoken-form normalization + address heuristics, optional **Microsoft Presidio** | Spoken PII ("five five five … at example dot com") defeats naive regex; normalization with char→word mapping recovers exact timestamps |

Key algorithmic details:

- **Keyframe + propagation strategy**: Grounding DINO runs every 0.5 s (YuNet every 0.25 s), SAM 2.1 propagates masks between keyframes — an order of magnitude cheaper than per-frame open-vocabulary detection at equal coverage (measured in `docs/benchmark.md`).
- **Recall-first thresholds** (box 0.25 / text 0.20 / NMS IoU 0.5) tuned on three held-out test clips; misses cost privacy, false positives only cost one reviewer click.
- **Mask safety post-processing**: fill holes → drop specks → dilate 5–12 px → feather 2–4 px → union with the padded detection box, so a drifting mask can never expose the target.
- **Audio safety padding**: −150 ms / +250 ms around every PII span, <200 ms gaps merged; if word timestamps are unavailable the whole segment is redacted and flagged for mandatory review — never silently skipped.

## 5. AMD Radeon GPU / ROCm Adaptation

PolicyCut was developed and benchmarked on an **AMD Radeon PRO W7900 (48 GB) with ROCm** using the platform-provided PyTorch ROCm build.

1. **All four core models run on the Radeon GPU** — Qwen3-4B (policy), Grounding DINO (detection), SAM 2.1 (tracking) and Whisper large-v3-turbo (ASR) — verified by `scripts/preflight.py` (prints `torch.version.hip`, device name, and a GPU matmul smoke test) and recorded per stage in `audit.json`.
2. **`--require-rocm` contest mode**: core model stages raise instead of silently falling back to CPU, so a "Radeon run" is provably a Radeon run. The only intentional CPU component is the YuNet assist detector (documented as such).
3. **ROCm-clean model choices**: the Transformers port of Grounding DINO (no custom CUDA kernels) and SAM 2.1 with `SAM2_BUILD_CUDA=0` (optional CUDA extension skipped; OpenCV replaces the post-processing op). No Flash-Attention, bitsandbytes, or quantization kernels are required.
4. **Precision policy**: FP16 by default on the W7900; any numerically suspect stage is re-run in FP32 for that stage only, and the fallback is recorded in the audit file.
5. **VRAM discipline**: models load sequentially per stage and are explicitly unloaded (`torch.cuda.empty_cache()`) before the next stage; peak VRAM per stage is measured with `torch.cuda.max_memory_allocated()` around synchronized boundaries and shipped in both the UI and `audit.json`.
6. **Honest metrics**: every stage reports wall time, effective FPS, precision and peak VRAM; GPU timing is bracketed by `torch.cuda.synchronize()`. Reproducible via `scripts/benchmark.py` (results in `artifacts/benchmarks/`).

> Measured performance tables (FP16 vs FP32, per-frame vs keyframe+SAM strategy, detection-interval sweep, Whisper RTF, end-to-end real-time factor, peak VRAM) are in `docs/benchmark.md` and `artifacts/benchmarks/` — all numbers are real measurements from the W7900 machine.

## 6. Outputs & Guarantees

Every export produces four artifacts:

- `redacted.mp4` — H.264/AAC, yuv420p, faststart, input metadata stripped, A/V drift < 100 ms, ffprobe-validated before an atomic replace;
- `redacted.srt` — transcript with sensitive spans replaced by `[REDACTED: PHONE|EMAIL|ADDRESS|MANUAL]` (the raw transcript is never exported);
- `audit.json` — input/output SHA-256, policy, model IDs and precision, per-stage timings and peak VRAM, every redaction event with source (auto/manual) and status, counts of human edits — and **zero PII plaintext, no raw transcript, no absolute paths**;
- `policycut_export.zip` — the three above, bundled.

## 7. Limitations (stated, not hidden)

PolicyCut is a human-in-the-loop redaction tool, **not** a guarantee of legal compliance. It does not do face recognition/whitelisting, age estimation, speaker diarization, generative inpainting or live capture. Detection is recall-tuned but not perfect — which is precisely why the review workspace, the mandatory confirm/ignore step and manual regions exist. Contest build accepts a single ≤60 s, ≤1080p video per project.

---

*PolicyCut Team — AMD Radeon Hackathon 2026, Track 1. Fully local. Human in the loop. Auditable. Built on AMD Radeon + ROCm.*
