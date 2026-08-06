# Mentra Glasses Integration

MedGlass connects to **Mentra Live** camera glasses through the official
MentraOS SDK (`@mentra/sdk`, `client/mentraos-app/`). This page explains the
architecture and the exact wiring.

## Architecture (real SDK, not a placeholder)

```
Mentra Live (camera, mic, speaker, RGB LED, button, no display)
   └─ phone: Mentra app
        └─ MentraOS Cloud  (cloud speech-to-text, session relay, TTS)
             │  webhook  (session start/stop)
             │  WebSocket (AppSession: transcription, buttons, VAD,
             │             audio chunks, photo request/responses)
             ▼
        client/mentraos-app  (Bun + @mentra/sdk, port 3000)
             │  HTTPS  (ingest transcript/audio, vision/process, generate_note)
             ▼
        MedGlass edge server  (Python/FastAPI, port 8100)
             │  pywhispercpp (CPU) or whisper.cpp hipBLAS (ROCm GPU)
             │  YOLOv8-seg detection, EasyOCR medication labels
             │  Qwen3.6:27B llama.cpp (ROCm) or template LLM fallback
             ▼
        output/soap_note.txt|json   (local only; PHI sanitized on store)
```

Everything is tunnelled with **ngrok**: only the Bun app is public; the Python
edge server stays on `localhost`.

## Session data flow

1. `AppServer.onSession` opens an `AppSession` (WebSocket to MentraOS Cloud).
   The app is **idle** until the glasses button starts a session.
2. **Long-press** the glasses button:
   - *Idle* → **start session**: the RGB LED turns **solid green** (the
     "recording" light you can see in-glasses) and stays on.
   - *Active* → **end session**: generates the SOAP note, LED blinks green and
     turns off; the live edge session is reset for the next visit.
3. `events.onTranscription` — cloud STT yields `{text, isFinal, confidence,
   speakerId}`. Final utterances are POSTed to `/ingest/transcript` **only
   while the session is active**. (Optionally `MEDGLASS_USE_OWN_WHISPER=1`
   streams raw `AUDIO_CHUNK` PCM to `/ingest/audio` and MedGlass's own whisper
   transcribes instead.)
4. Button **short-press** (active) → `session.camera.requestPhoto()` returns a
   JPEG `Buffer` → POST `/vision/process` → detection + OCR. Findings (e.g.
   medication label) are spoken and stored in the session context.
5. Button **long-press** (active) → POST `/generate_note` → SOAP note.
   Summaries are read via `session.audio.speak()`, full note shown as cards
   through `layouts.showDashboardCard` / `showReferenceCard` and saved with
   `simpleStorage`.

## Glasses feedback (Mentra Live has no display)

| Signal | Method |
|---|---|
| Ready / prompts / summaries | `session.audio.speak()` |
| **Session active (recording)** | `session.led.solid("green", …)` — the kickoff light |
| Speaking (VAD) | `session.led.solid("white", …)` |
| Utterance captured | `session.led.blink("green", …)` |
| Medication detected | `session.led.blink("blue", …)` + spoken label |
| Note complete | `session.led.blink("green", …)` then off |
| Note / status / dashboard link | `layouts.showDashboardCard/showReferenceCard` (phone app) |

## Viewing results from your phone

The app reverse-proxies the MedGlass edge server through the same public
ngrok URL, so the dashboard AND the live consultation page work in your phone
browser:

```
https://<your-ngrok-domain>/dashboard   # saved results + EHR export
https://<your-ngrok-domain>/           # live consultation page (mic/webcam)
```

Proxied through the Bun app (with `X-Dashboard-Token` injected automatically
when configured):

| Client path | Proxied to edge server |
|---|---|
| `/dashboard`, `/notes`, `/notes/{id}/download`, `/static/*` | results dashboard + EHR export |
| `/` | live consultation page |
| `/generate_note`, `/generate_note/stream`, `/session/*`, `/hud/update`, `/ingest/*`, `/vision/process` | live page actions |
| `/ws/audio`, `/ws/video` (WebSocket upgrade) | live mic/camera streaming |

Configure `DASHBOARD_TOKEN` in `client/mentraos-app/.env` (it must match
`MEDGLASS_DASHBOARD_TOKEN` on the edge server, which `scripts/start_server.sh`
reads from `output/server.env`) and `PUBLIC_BASE_URL` (your ngrok domain) to
show a tappable "Results Dashboard" card on the phone after each note.

## Endpoints added for Mentra ingestion

| Endpoint | Purpose |
|---|---|
| `POST /ingest/transcript` | append cloud-STT line to a session (`session_id, text, confidence?, speaker?`) |
| `POST /ingest/audio` | raw 16 kHz PCM (base64) → MedGlass whisper (`pcm_b64, sample_rate`) |
| `POST /vision/process` | base64 JPEG → detection/OCR result + findings (`image_b64, session_id`) |
| `POST /generate_note` | SOAP note from session context |
| `POST /session/{id}/reset` | clear a session |
| `GET /dashboard` | results dashboard (proxied for phone access) |
| `GET /notes` · `GET /notes/{id}/download` | archived notes + EHR export (proxied) |

## Walkthrough

1. `bash scripts/start_server.sh` — edge server on :8100.
2. `cd client/mentraos-app && bun run dev` — MentraOS app on :3000
   (needs `.env` with `PACKAGE_NAME` + `API_KEY` from
   https://console.mentra.glass/apps).
3. `ngrok http 3000` — public URL; paste into the Developer Console as the
   app's Public URL.
4. Open the app from the Mentra phone app; put on the glasses; speak; use the
   button for photo capture / note generation.

See `client/mentraos-app/README.md` for the full setup checklist and
troubleshooting.
