# MedGlass — Usage Guide

How to use the ambient clinical scribe end-to-end — either on the
**Mentra glasses** (primary, real mic + camera), or the **voice-driven demo
mode** (no glasses), and then how to **export results** from the dashboard
into an EHR.

```
MENTRA GLASSES ──(phone Mentra app → MentraOS Cloud)──▶ Bun app (:3000)
   mic/camera/button/LED                                   │  HTTPS + WSS proxy
                                                            ▼
                                                    MEDGLASS EDGE (:8100)
                                                     whisper · YOLO detection + OCR
                                                    llama.cpp HIP · notes
                                                            │
                                                    output/notes/  (history)
                                                            │
                                                    phone browser ──▶ /dashboard
```

---

## 1. One-time setup (already done on the rig)

| Service | Command | Status |
|---|---|---|
| Edge server (AI pipeline) | `bash scripts/start_server.sh 127.0.0.1 8100` | running |
| MentraOS app (Bun) | `cd client/mentraos-app && bun run start` | running, port 3000 |
| Public tunnel | `ngrok http --url=copilot-unstaffed-smuggling.ngrok-free.dev 3000` | running |

Check health:
- Edge: `http://127.0.0.1:8100/health` → `{"status":"ok","models":{whisper:true,yolo:true,llm:true}}`
- Mentra app: `http://127.0.0.1:3000/health` → `{"status":"healthy","activeSessions":N}`

The public URL (phone + MentraOS console) is
**https://copilot-unstaffed-smuggling.ngrok-free.dev**.

---

## 2. Real glasses mode (Mentra glasses, primary)

> Mentra Live has **no display** — feedback is TTS voice, the RGB LED, and
> cards on the phone's Mentra app.

### Step-by-step

1. **Open the app on your phone** → Mentra phone app → tap **MedGlass**.
   The glasses speak: *"MedGlass ready. Press and hold the button to start a
   session."* The LED is **off** (idle).
2. **Long-press the glasses button** → session starts.
   - LED turns **solid green** — this is your "recording" light, visible
     in-glasses. It stays on for the whole session.
   - TTS: *"Session started. Recording."*
3. **Run the consultation** with your patient. Nothing to press while talking:
   - The white LED glows while either of you is speaking (VAD).
   - Transcripts accumulate automatically (cloud STT → edge server).
4. **Short-press** to capture a photo any time (med label, rash, document):
   - The photo is analyzed locally (detection + OCR).
   - Medication found → TTS *"Medication detected: <label>"*, blue LED blink,
     "Medication" card on the phone.
   - No medication found → nothing spoken; the photo is stored as an original.
5. **Long-press again when done** → session ends and the SOAP note is built:
   - LED white (busy) → TTS reads the S/A/P summary → LED blinks green → **off**.
   - Full SOAP note cards + a tappable **"Results Dashboard"** link card appear
     on the phone.
   - The note is saved to the edge server's history for the dashboard.

### Button cheat-sheet

| Press | Idle (LED off) | Active (LED green) |
|---|---|---|
| **Long** | Start session (green LED on) | End session → SOAP note (blink → off) |
| **Short** | "Press and hold to start" | Capture photo → detection + OCR |

### What each LED means

| LED | Meaning |
|---|---|
| **off** | Idle — waiting for a long-press to start |
| **solid green** | Session active / recording (the kickoff light) |
| **solid white** | Someone is speaking (VAD) |
| **blue blink** | Medication detected from a photo |
| **green blink** | Utterance captured / note complete |

---

## 3. Demo mode (voice-driven, no glasses)

A self-contained demo that runs the **real GPU pipeline** (no hardware) and
emits the same voice feedback the glasses speak. It synthesizes a realistic
patient voice line, transcribes it with the on-device GPU whisper.cpp, runs the
real vision+OCR and the GPU LLM, and writes a SOAP note — so the notes are real
and vary per scenario (not a template).

Requirements (already on the rig): the edge server on `:8100` (see Section 1)
and `espeak-ng`.

```bash
python scripts/run_demo.py              # scenario 0 — headache + ibuprofen
python scripts/run_demo.py --scenario 1 # rash + lisinopril refill
python scripts/run_demo.py --scenario 2 # sore throat + amoxicillin
python scripts/run_demo.py --speak      # enable espeak voice feedback ("Session started" / "Medication detected" / "Note complete")
python scripts/run_demo.py --no-server  # transcribe + generate note client-side only
```

What each step does (mirrors the glasses lifecycle):

1. Reset session → **TTS:** *"Session started."*
2. Synthesize + GPU-transcribe a patient voice line → POST transcript like the
   Mentra cloud STT does.
3. Capture a photo (synthesized medication label) → real YOLO+OCR.
   → **TTS:** *"Medication detected: …"*
4. Generate note via the GPU LLM → variable SOAP note (S/O/A/P).
   → **TTS:** *"Note complete."*
5. Output written to `output/demo_<note_id>.{json,txt}` (+ dashboard history).

---

## 4. Using the browser live page (desktop or phone)

Useful for demoing the AI pipeline without the glasses, or from your phone:

- **Desktop:** `http://127.0.0.1:8100` (live page) and `http://127.0.0.1:8100/dashboard`
- **Phone (same rig):** `https://copilot-unstaffed-smuggling.ngrok-free.dev`
  (live page) and `.../dashboard` (results). Mic, camera, WebSockets, notes
  and the dashboard are all tunneled through the Bun app.

**Sign in:** On first boot the server prints a one-time password for `clinician`
to the log. For a persistent demo account, create `amdje` with:
```bash
python3 scripts/add_user.py amdje '<password>' --role admin
```
Then sign in with `amdje` / `<password>`.

Steps on the live page:
1. **Start mic** → allow the browser to use the microphone (transcribes live).
2. **Start camera** → allow the webcam (live detection preview).
3. Talk through a mock consultation, hold objects/cards up to the camera.
4. **Generate note** → SOAP note appears; it is archived automatically.
5. **Results →** opens the dashboard with the full history.

---

## 4. Results dashboard & EHR export

`https://<host>/dashboard` lists every saved note (from glasses, web UI, or
simulator), newest first.

For each note you can:

| Action | How |
|---|---|
| View full note + transcript + findings | tap the note |
| **Download** as plain text | button → `?fmt=txt` |
| **Download** as Markdown | button → `?fmt=md` |
| **Download** raw JSON record | button → `?fmt=json` |
| **Port into EHR (HL7 FHIR R4)** | button → `?fmt=fhir` (Bundle + LOINC 28633-4 Composition with S/O/A/P) |
| **Port into EHR (CDA/CCD XML)** | button → `?fmt=ccda` |
| Delete a note | ✕ on the note row |

Any download button also works as a direct URL:
`GET /notes/<id>/download?fmt=fhir`. The FHIR/CCDA output can be imported into
Epic/Cerner-style systems or an XDS repository.

> All results are stored **locally only** in `output/notes/`. PHI is sanitized
> on store (`strip_phi_on_store`). The dashboard is protected by a token when
> `MEDGLASS_DASHBOARD_TOKEN` / `DASHBOARD_TOKEN` are set.

---

## 5. Use cases (example scripts)

### A. Urgent-care visit (sore throat)
1. Long-press → green LED (recording).
2. Patient: *"I've had a sore throat for four days, hurts to swallow, and I've
   been running a temperature."*
3. Doc: *"Let's check your vitals and throat."*
4. Short-press a photo of the exam / throat image.
5. Long-press → note generated.
6. Phone shows the SOAP note + dashboard link → export FHIR into the EHR.

### B. Medication refill + rash
1. Long-press → green LED.
2. Patient: *"I have a rash on my arm for a week and I'm almost out of my
   lisinopril."*
3. Doc: *"BP 128/84. Show me the rash and your pill bottle."*
4. Short-press photo of the **pill bottle** → TTS *"Medication detected:
   lisinopril 10 mg"*, blue blink; short-press photo of the **rash**.
5. Long-press → SOAP note includes the rash assessment + refill plan.

### C. No-hardware demo (laptop, no glasses)
- `python scripts/run_demo.py` — voice-driven demo through the real pipeline
  (see Section 3).
- Web UI at `http://127.0.0.1:8100/live` (mic + webcam), or
  `python client/simulator.py --audio --video` driving the WebSocket endpoints.

### D. Review day
Open the dashboard on the phone, scroll past notes, open one, hit
**HL7 FHIR R4 (EHR)** → send the downloaded `.json` to your EHR sandbox or
print the CDA XML.

---

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `setup.sh` falls back to CPU whisper/template LLM | `setup.sh` only builds GPU backends when a compiler **and** `rocm-smi` are found; on a GPU box re-run after `sudo apt-get install build-essential rocm-smi rocminfo python3-venv` |
| `setup.sh: line N: python: command not found` | Was a stale bug (literal `python`); pull the latest `setup.sh`, which uses the project venv (`.venv`) or `python3` consistently |
| `python3 -m venv` fails ("ensurepip not available") | Install the venv module: `sudo apt-get install python3-venv`, then re-run `setup.sh` |
| Server won't use the venv | `start_server.sh` prefers `.venv/bin/python` when present; re-run `setup.sh` or start via `bash scripts/start_server.sh` |
| No green LED on long-press | Phone app must be open & connected; check `curl http://127.0.0.1:3000/health` shows `activeSessions` ≥ 1 |
| No transcription in the note | Session wasn't started (long-press first); check `/session/<id>/note` shows transcript |
| "Cannot GET" on the phone | The Bun app must be running the latest code (`bun run start` after any edit) |
| Dashboard shows 401 | Token mismatch: `DASHBOARD_TOKEN` (.env) must equal `MEDGLASS_DASHBOARD_TOKEN` (output/server.env) |
| ngrok URL changed | Update `PUBLIC_BASE_URL` in `.env` and the Public URL in the Mentra console |
| Edge server unreachable from app | `MEDGLASS_URL=http://127.0.0.1:8100` must match where the edge server runs |
| Vision warns "provider not available" | The app auto-detects the ONNX ROCm EP (needs ROCm Tracer, not in Ubuntu apt); on this rig YOLO deliberately runs on the CPU EP — set `MEDGLASS_YOLO_ROCM=false` to silence, or override in `config.json` if you install a working EP |

---

## 7. Session lifecycle reference

| Event | What happens |
|---|---|
| App opened (phone) | Idle. LED off. "Press and hold to start." |
| Long-press (idle) | Edge session reset; LED solid green; transcripts begin accumulating |
| Speech (active) | Cloud STT → `/ingest/transcript`; white LED while talking |
| Short-press (active) | `/vision/process` → detection + OCR → spoken finding + card |
| Long-press (active) | `/generate_note` → SOAP note archived, spoken summary, LED blink→off, edge session reset |
| App closed / stop | Edge session reset |
