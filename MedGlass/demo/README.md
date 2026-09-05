# Demo

**Video:** `demo/medglass_demo.mp4` (91 s, automated capture: glasses-POV feed →
photo + medication OCR → Patient Note → dashboard, plus ROCm GPU proof).

> The recorded video predates the current Demo App UI (live on-screen
> transcript, voice feedback, Add-photo with preview/× delete, photos saved
> at session end).

To re-record with the physical glasses, see `demo/RECORD_GUIDE.md`.

*Note: The Radeon AI PRO R9700 (Navi 48) driver does not expose a GPU-busy counter
(`rocm-smi --showuse` stays flat and `gpu_busy_percent` returns "Operation not
supported"), so the GPU-activity proof on the video and below is VRAM used
(`rocm-smi -u --showmeminfo vram`, 1.1 GiB → 17.2 GiB as the 27 B model loads)
plus real per-stage CPU vs GPU wall-clock speedups. See `demo/RECORD_GUIDE.md`.*

## Evidence (screenshots)

Static, legible copies of what the video shows, in this folder:

- `evidence_benchmark.png` — CPU vs GPU timing table (whisper 6.3×, LLM 3.6×) and
  the `rocm-smi --showpids` line proving the llama-cli process held 16.8 GiB.
- `evidence_vram.png` — GPU VRAM-used trace over time during a real
  whisper + LLM run, peaking at ~17.2 GiB (the live GPU-activity proof).
  (Same chart as `benchmarks/gpu_utilization.png`.)
- `evidence_ocr.png` — glasses-POV frame next to the medication OCR finding
  ("Ibuprofen 200 mg tablets (NSAID)").
- `evidence_note.png` — the generated Patient Note (Emerson Bishop, full SOAP)
  decrypted off the local store, with the source transcript and photo link.
- `hackathon_evidence.png` — one-page combined evidence sheet (all four above).

## Walkthrough

### Scene 1 — Setup (30 s)
- `bash setup.sh` (one-command environment) then `bash scripts/start_server.sh 127.0.0.1 8100`.
- Terminal shows server starting and `GET /health` reporting GPU + models loaded.
- Open `http://127.0.0.1:8100` and sign in:
  - **Username:** `amdje` · **Password:** set it once with
    `python3 scripts/add_user.py amdje '<password>' --role admin`
    (the seeded admin account; the password is never stored in source).
    For a first-boot quick demo you can also use the one-time password the server
    logs at startup for the `clinician` account, or set
    `MEDGLASS_LOGIN_USER`/`MEDGLASS_LOGIN_PASSWORD` in `output/server.env`.
  - Dashboard: `/`, Glasses Demo: `/live`.

### Scene 2 — Consultation (90 s)
- **MIC IS PRIMARY.** Click **Start session** and allow the microphone
  (required). The microphone is the consultation voice track and stays running
  even if no camera is available.
- The camera is for photos only (no live detection feed is sent to the HUD):
  click **Capture** to snap a medication bottle / object. If the camera or vision
  pipeline is unavailable, capturing inserts a stock patient photo instead and
  the session is **never** interrupted.
- There is no flip button: the camera defaults to the rear (outward) camera on
  phones.
- Right after "Start session" the glasses announce the patient name via TTS
  (e.g. "Session started. Patient Casey Hughes.") — the same name is recorded on
  the saved SOAP note.
- Transcript builds live; HUD events show medication detections.

### Scene 3 — Note generation (30 s)
- Press **Generate Note** (or call `POST /generate_note`).
- GPU utilization spike on the overlay; SOAP note streams in via `/generate_note/stream`.
- HUD shows S/O/A/P sections.

### Scene 4 — GPU metrics (60 s)
- `rocm-smi -u --showmeminfo vram` overlay (GPU use% is unavailable on Navi 48, so
  VRAM is the live activity signal: ~1.1 GiB idle → ~17 GiB when the LLM loads).
- Side-by-side CPU vs GPU from `benchmarks/cpu_vs_gpu.json`.
- Latency breakdown per stage; 3.6× LLM / 6.3× whisper speedup.

## Reproduction commands

```bash
bash setup.sh                                  # one-command environment
cd src && uvicorn server:app --port 8100       # server (hardware path)
python client/simulator.py --audio --video     # glasses simulator
python benchmarks/benchmark.py --samples 20    # CPU vs GPU + utilization plot
python scripts/run_demo.py --speak      # voice-driven demo (espeak voice -> GPU whisper -> GPU LLM note)
```
