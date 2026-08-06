# MedGlass — Product Pitch

**AMD AI DevMaster Hackathon 2026 · Multimodal AI track**
**One AMD Radeon GPU (ROCm) · five AI models · zero cloud · fully local clinical scribe**

---

## One-liner

MedGlass turns any doctor-patient conversation into a HIPAA-safe SOAP note in
seconds — recorded, detected, transcribed, and summarized **entirely on one AMD
Radeon GPU in the exam room**, so no patient data ever leaves the building.

## The problem

Clinicians spend 1–2 hours per shift on documentation. Today's "AI scribes"
are thin wrappers over **cloud LLMs** — meaning a patient's most private words
are shipped to a third party. That is a non-starter for HIPAA, for rural and
offline clinics, and for any provider who wants to *actually* own their data.
Existing local solutions are research demos: single-model, CPU-bound, and
unusable in real time.

## The solution

MedGlass is an **edge AI server** driven by wearable camera glasses
(Mentra Live) or a plain laptop webcam + mic. It runs a complete five-model
multimodal pipeline on the AMD stack — no CUDA anywhere:

| Stage | Model | AMD acceleration |
|---|---|---|
| Speech-to-text | whisper-small.en (Q5_1) | whisper.cpp **HIP build** via hipBLAS |
| Visual detection | YOLOv8n-seg | ONNX Runtime (ROCm EP-ready) |
| Medication-label OCR | EasyOCR (CRAFT) | ROCm-aware, optional |
| SOAP note generation | Qwen3.6:27B (Q4_K_M) | llama.cpp **HIP build**, 100% layers on ROCm0 |
| HUD feedback | FastAPI WebSocket | instant, on-device |

Doctor talks → transcripts stream live → a photo of a rash or a pill bottle is
detected and read locally → the note (S/O/A/P) is generated and exported
(**HL7 FHIR R4** / **CDA-CCD**) straight into the EHR.

## Why it wins on AMD (40/100 points: ROCm optimization)

Measured on a **Radeon AI PRO R9700 (gfx1201, 32 GiB)**, Ubuntu-native ROCm 7.1:

| Component | CPU | GPU (ROCm) | Speedup |
|---|---|---|---|
| whisper-small.en (5 s clip) | 6.65 s | **1.08 s** | **6.2×** (111× realtime) |
| Qwen3.6-27B Q4_K_M | 52.3 s | **9.03 s** | **5.8×** (28–47 tok/s) |
| YOLOv8n-seg (vision) | 88.98 ms/frame | CPU EP¹ | — |

- **Native HIP builds** — `cmake -DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1201` for
  whisper.cpp and llama.cpp (b9180+ for Qwen3.6/MTP). The LLM runs 100% of its
  layers on ROCm0 — no Ollama, no cloud inference.
- **Real quantization choices** — Q5_1 whisper + Q4_K_M 27B (16.8 GB) sized to
  live alongside two other models inside 32 GiB VRAM with a concurrency budget.
- **Lazy loading + VRAM budgeting** — whisper + YOLO + LLM stay resident in the
  framebuffer heap; `/health` reports live GPU state.
- **Reproducible** — `bash setup.sh` provisions ROCm and rebuilds both HIP
  binaries; `python3 benchmarks/benchmark.py` regenerates every number above.
- ¹ ONNX ROCm EP is auto-detected; on Ubuntu-native ROCm it currently falls
  back to CPU (ROCm Tracer is not in the Ubuntu archive). Whisper + LLM — the
  two compute-heavy stages — are fully GPU-accelerated. See `AMD_OPTIMIZATION.md`.

## Why it wins on completeness (60/100 points: function + UX)

- **Works end-to-end** — the live demo: put on the glasses, talk, snap a photo,
  get a note. One `e2e_smoke.py` drives the real HTTP + WebSocket surface.
- **Real multimodal fusion** — audio transcript + visual findings merged by the
  context builder into one clinically coherent note; PHI is sanitized on store.
- **Scenario innovation + UX** — a privacy-preserving "recording light"
  (glasses LED = session active), TTS feedback, a live browser page, and a
  phone dashboard with EHR export. Clinicians see *why* the system is recording.
- **Real-world value** — works fully offline; no patient data leaves the room;
  notes land in the EHR as standards-compliant FHIR/CCDA, not a text dump.
- **Original, never-mocked pipeline** — the only mock is the no-hardware demo
  script; every production path runs real model binaries on real AMD hardware.

## Ask the judge to imagine

A doctor's office with no internet, no cloud contract, no risk review — just an
AMD Radeon box in the corner and a camera on the desk. Five AI models wake up,
listen, watch, and write. The note is already in the EHR when the patient
reaches the door. That is MedGlass.

## Submission kit

- Live demo: `bash setup.sh && bash scripts/start_server.sh && python3 scripts/run_demo.py`
- Demo script: `demo/README.md`
- Benchmarks + VRAM trace: `benchmarks/cpu_vs_gpu.json`, `gpu_utilization.png`
- Docs: `USAGE_GUIDE.md` · `AMD_OPTIMIZATION.md` · `ARCHITECTURE.md` · `PROJECT_PROFILE.md`
