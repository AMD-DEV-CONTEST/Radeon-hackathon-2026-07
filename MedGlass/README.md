# MedGlass — Fully-Local Ambient Clinical Scribe

**AMD AI DevMaster Hackathon 2026 · HIPAA-first ambient documentation on a single AMD Radeon GPU (ROCm).**

MedGlass runs a five-model AI pipeline — speech-to-text, visual detection +
medication-label OCR, and medical LLM note generation — **entirely on local
hardware**. Audio, images, and transcriptions never leave the edge server.

```
MENTRA GLASSES ──(WebSocket)──▶ MEDGLASS EDGE SERVER ──▶ AMD GPU (ROCm)
   camera/mic/HUD                  5 concurrent AI models        no cloud
```

## Features

| Priority | Feature | Stack |
|---|---|---|
| P0 | Ambient speech-to-text | whisper.cpp (hipBLAS), Q5_1 |
| P1 | Visual context (med labels, rash, forms) | EasyOCR (CRAFT) on ONNX ROCm EP |
| P1 | Visual detection (med bottles/books/documents) | YOLOv8n-seg ONNX ROCm EP |
| P0 | SOAP note generation | llama.cpp (ROCm), Qwen3.6:27B Q4_K_M |
| P2 | HUD feedback on glasses | FastAPI WebSocket + webhook |
| P0 | 100% local execution | all inference on one AMD GPU |

## Repository layout

```
src/
  server.py            FastAPI app: /ws/audio, /ws/video, /generate_note
  audio_handler.py     whisper.cpp subprocess wrapper + chunk buffer
  video_handler.py     YOLO-seg detect -> OCR pipeline
  llm_handler.py       llama.cpp subprocess for SOAP generation
  context_builder.py   SOAP prompt template + few-shot + PHI sanitizer
  hud_output.py        HUD formatting + webhook push + JSONL sink
  utils.py             GPU detection, benchmarks, WAV conversion
  config.py            all paths / knobs / VRAM budget
client/
  mentraos-app/          Mentra Live app (Bun + @mentra/sdk) -> connects to edge server
  simulator.py           laptop webcam/mic fallback for reliable demos
benchmarks/
  benchmark.py         CPU vs GPU wall-clock per stage -> cpu_vs_gpu.json
scripts/
  download_models.py   fetch ggml-small.en.bin, yolov8n-seg.onnx, Qwen GGUF
  run_demo.py            voice-driven no-hardware demo (espeak voice -> GPU whisper -> GPU LLM)
docs/                    architecture, AMD/ROCm optimization, HIPAA, pitch, submission docs
demo/                    demo video, recording guide, evidence screenshots, GPU summary tools
benchmarks/              CPU vs GPU harness + measured results (json/png)
```

## Quick start

```bash
# 1) One-command setup (installs Python deps + models; builds GPU backends if ROCm+compiler present)
bash setup.sh

# 2) Run the server (web UI + API + WebSockets)
bash scripts/start_server.sh 127.0.0.1 8100

# 3) Sign in and open the Demo App
#    http://127.0.0.1:8100  -> sign in. On first boot the server prints a
#    one-time password for the `clinician` account to the log; or set
#    MEDGLASS_LOGIN_USER / MEDGLASS_LOGIN_PASSWORD (see .env.example).
#    For local demos, create/refresh the seeded `amdje` account with:
#        python3 scripts/add_user.py amdje '<password>' --role admin
#    Dashboard: /          Demo App: /live
#
#    Demo App flow:
#      - Click "Start session" and allow the microphone. A random synthetic
#        patient name is announced via local TTS ("Session started. Patient
#        Casey Hughes.") and the live transcript box fills as you speak
#        (whisper.cpp on ROCm). The UI shows a live "chunks" counter so you
#        can verify audio is flowing.
#      - "Add photo" opens the (back/outward) camera with a short preview,
#        captures one frame and queues it — tap the × on a queued photo to
#        delete it. Photos are only saved when the session ends. Without a
#        camera, a bundled stock photo is queued instead; the recording is
#        never interrupted.
#      - Click "Stop session": queued photos are saved, any remaining audio
#        is transcribed (flush), the SOAP note is generated, and "Session
#        ended. Note saved." is spoken. The note (with transcript + photos)
#        appears on the Patient Notes dashboard.

# Create an extra account (scrypt-hashed, stored in output/users.json):
python3 scripts/add_user.py alice 's3cure-pass' --role clinician

# Or run the no-hardware demo
python3 scripts/run_demo.py
```

The app works two ways on a plain laptop:

| Path | How | Notes |
|---|---|---|
| **Web UI** | `start_server.sh`, open the browser, sign in | mic + webcam via `getUserMedia`; live transcript, detection, photo capture, SOAP note |
| **Laptop simulator** | `python client/simulator.py --audio --video` | Python client driving the same WebSockets |

## Web UI

Served at `http://<host>:8100` (`src/static/`). Sign in with a clinician
account; `/` is the **Patient Notes** dashboard and `/live` is the
**Demo App**.

**Demo App** — each "Start session" creates an isolated session with a fresh
random synthetic patient name (announced via local TTS). Microphone audio is
captured with AudioWorklet (ScriptProcessor fallback), resampled to 16 kHz
PCM and streamed over the same WebSocket the glasses use; transcripts appear
live in the UI. "Add photo" captures from the back/outward camera (short
preview, flicker feedback, × to delete a queued photo; bundled stock photo
fallback when no camera exists) — queued photos are uploaded only when the
session ends, together with a final transcription flush, so the saved note
always contains the real conversation and the kept photos.

**Patient Notes dashboard** — every saved consultation (web demo, simulator,
or glasses) with S/O/A/P drawer, transcript, case photos, downloads
(Markdown/Text/JSON/**FHIR R4**/**CDA-CCD**), spoken note readback, and
care-team next steps: plan items can be assigned (Nurse/Provider) and checked
off — completed items leave the list and the Follow-ups / Tests & orders /
Med changes / Open items counters update, with a "Show completed" toggle.

## Connecting Mentra glasses

MedGlass integrates with **Mentra Live** (camera glasses) via the official
`@mentra/sdk` — see `client/mentraos-app/` (a real Bun/TypeScript app, not a
placeholder) and [docs/MENTRA_INTEGRATION.md](docs/MENTRA_INTEGRATION.md).

```bash
# edge server (vision + note generation)
bash scripts/start_server.sh 127.0.0.1 8100

# MentraOS app (needs .env: PACKAGE_NAME + API_KEY from console.mentra.glass)
cd client/mentraos-app && bun install && cp .env.example .env   # edit .env
bun run dev                                                      # port 3000

# expose for the MentraOS relay
ngrok http 3000    # paste the URL into console.mentra.glass as Public URL
```

Then open **MedGlass** from the Mentra phone app with the glasses connected:
**long-press to start** a session (green LED comes on — your "recording" light),
speak (cloud STT → transcript), **short-press** to capture a photo
(detection + medication OCR), then **long-press again to end** the session and
generate the SOAP note (summary spoken + cards on the phone dashboard).

> Mentra Live has **no display** — feedback is TTS, RGB LED and the phone
> app. The browser UI at `/` and `client/simulator.py` exercise the same
> edge endpoints for local development without the glasses.

## API

| Endpoint | Purpose |
|---|---|
| `GET /health` | GPU + model availability |
| `WS /ws/audio` | send 16 kHz PCM, stream back transcripts |
| `WS /ws/video` | send JPEG frames, get detection/OCR JSON |
| `POST /generate_note` | build SOAP note from session context |
| `GET /generate_note/stream` | SSE stream of the note from the GPU |
| `POST /hud/update` | push a HUD payload to clients |
| `GET /session/{id}/note` | current note / transcript |
| `GET /notes` | list all archived notes (newest first) |
| `GET /notes/{id}` | one archived note (note, sections, transcript, findings) |
| `GET /notes/{id}/download?fmt=` | download/export: `txt`, `md`, `json`, `fhir`, `ccda` |
| `DELETE /notes/{id}` | delete an archived note |

Every generated note is archived to `output/notes/<id>.json` (with transcript
and visual findings) so results survive restarts and show up on the dashboard.

## Results dashboard & EHR export

Open **http://127.0.0.1:8100/dashboard** (linked from the live page) to see
every saved consultation — from the web UI, the laptop simulator, or the Mentra
glasses. Each note can be:

- **Downloaded** as plain text, Markdown, or the raw JSON record.
- **Exported to an EHR** as **HL7 FHIR R4** (`?fmt=fhir`, a Bundle with a
  LOINC 28633-4 Composition carrying the S/O/A/P sections) or **CDA/CCD XML**
  (`?fmt=ccda`) — importable into Epic/Cerner-style systems or an XDS
  repository.

Backend: `src/notes_store.py` (history) + `src/ehr_export.py` (formatters).

### Viewing results from your phone

The MentraOS app reverse-proxies the edge server through its public ngrok URL,
so the dashboard **and** the live consultation page work in your phone browser:

```
https://<your-ngrok-domain>/dashboard   # saved results + EHR export
https://<your-ngrok-domain>/           # live consultation page (mic/webcam)
```

Patient data is protected by an optional token: set `DASHBOARD_TOKEN` in
`client/mentraos-app/.env` and `MEDGLASS_DASHBOARD_TOKEN` in
`output/server.env` (the edge server reads it via `start_server.sh`); the app
injects it automatically so the phone never needs to type it. Set
`PUBLIC_BASE_URL` to your ngrok domain to get a tappable "Results Dashboard"
card on the phone after every note. The live page's WebSockets (`/ws/audio`,
`/ws/video`) are tunneled too. See `docs/MENTRA_INTEGRATION.md` and
`docs/USAGE_GUIDE.md`.

## Performance (measured on R9700 / ROCm 7.1)

| Stage | Acceleration | Result |
|---|---|---|
| whisper-small.en | whisper.cpp hipBLAS | **6.2× vs CPU** (RTF 0.055 → 0.009) |
| YOLOv8n-seg | ONNX CPU EP¹ | 88.98 ms/frame |
| Qwen3.6:27B Q4_K_M | llama.cpp ROCm | **5.8× vs CPU** (28–47 tok/s) |

Full table + CPU/GPU wall-clock in `docs/TECHNICAL_BREAKDOWN.md` and
`benchmarks/cpu_vs_gpu.json`.

¹ The ONNX ROCm EP is auto-detected; Ubuntu-native ROCm lacks ROCm Tracer so
YOLO runs on the CPU EP. Whisper + LLM — the two compute-heavy stages — are
fully GPU-accelerated.

VRAM budget: whisper 1.5 GB + YOLO 0.5 GB + LLM 16.8 GB ≈ fits a 32 GiB card
(models load lazily; concurrency governed by `memory_budget_gb`).

## Hackathon submission materials (Track 1)

| Requirement | Location |
|---|---|
| Project Profile (background, users, architecture, models, AMD/ROCm adaptation) | [`docs/PROJECT_PROFILE.md`](docs/PROJECT_PROFILE.md) (+ generated PDF) |
| Complete source code | this repository (`src/`, `client/`, `scripts/`, `benchmarks/`, `tests/`) |
| Environment config, startup guide, dependency list | this README, [`requirements.txt`](requirements.txt), [`setup.sh`](setup.sh), [`.env.example`](.env.example), [`config.example.json`](config.example.json) |
| Demo video (3–5 min) | [`demo/medglass_demo.mp4`](demo/medglass_demo.mp4) |
| AMD GPU execution evidence | [`benchmarks/cpu_vs_gpu.json`](benchmarks/cpu_vs_gpu.json), [`benchmarks/gpu_utilization.png`](benchmarks/gpu_utilization.png), [`demo/evidence_*.png`](demo/) |

Demo screenshots: `demo/evidence_note.png` (generated SOAP note with
transcript + photo), `demo/evidence_ocr.png` (medication-label OCR from a
glasses-POV frame), `demo/evidence_benchmark.png` (CPU vs GPU + `rocm-smi`
process residency), `demo/evidence_vram.png` (VRAM trace during a live run).

## Docs

- [Usage guide](docs/USAGE_GUIDE.md) — step-by-step for glasses, web UI, dashboard, EHR export + use cases
- [AMD/ROCm optimization](docs/AMD_OPTIMIZATION.md) — quantization, EP notes, rocm-smi
- [Architecture](docs/ARCHITECTURE.md) — data flow and module walkthrough
- [Mentra integration](docs/MENTRA_INTEGRATION.md) — glasses wiring, button/LED lifecycle, phone proxy
- [Product pitch](docs/PITCH.md) — AMD AI DevMaster pitch aligned to judging criteria
- [Demo](demo/README.md) — demo video walkthrough + evidence screenshots
