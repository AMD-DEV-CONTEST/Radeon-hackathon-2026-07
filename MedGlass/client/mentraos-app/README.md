# MedGlass MentraOS App (Mentra Live)

This is the real MentraOS integration for the **MedGlass** edge server. It runs
on your computer with [Bun](https://bun.sh), speaks to MentraOS Cloud over the
official `@mentra/sdk` (AppServer + AppSession), and proxies AI work to the
MedGlass Python edge server.

```
Mentra Live glasses
   └─ phone (Mentra app)
        └─ MentraOS Cloud  (speech-to-text, session relay)
             └─ /webhook ──▶ this app (Bun, port 3000) ◀── ngrok (public URL)
                  └─ HTTPS localhost ──▶ MedGlass edge server (Python, :8100)
                                            (vision detection/OCR + SOAP generation)
```

Mentra Live has **no display**, so feedback is audio (TTS), RGB LEDs and the
phone dashboard.

## What it does

| Trigger | Action |
|---|---|
| App open | Idle. "Press and hold to start." LED off. |
| Button **long** press (idle) | **Start session**: edge session reset, green LED stays on (the in-glasses "recording" light). |
| Speech (active) | Cloud STT (`onTranscription`) → transcript appended to the edge server session → "Heard" card on phone; white LED while talking |
| Button **short** press (active) | `camera.requestPhoto()` → MedGlass `POST /vision/process` → medication detection + OCR → spoken finding + blue LED if medication detected |
| Button **long** press (active) | **End session**: `POST /generate_note` → spoken S/A/P summary + SOAP cards + dashboard link card on phone, saved to `simpleStorage`, LED blinks then off |
| App stop | Edge-server session reset |

The app also serves the MedGlass results dashboard at `http://<host>:3000/dashboard`
(reverse-proxied to the edge server) so it can be opened from your phone browser
through the same ngrok URL.

Optional: set `MEDGLASS_USE_OWN_WHISPER=1` to stream raw glasses audio chunks
to MedGlass instead of relying on cloud STT (for the GPU whisper story).

## Setup (one-time)

1. **Install Bun**
   ```bash
   curl -fsSL https://bun.sh/install | bash
   source ~/.bashrc
   ```

2. **Install ngrok** (already done on this machine)
   ```bash
   # Linux x64
   curl -sL https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz -o ngrok.tgz
   tar xzf ngrok.tgz && sudo mv ngrok /usr/local/bin/
   ngrok config add-authtoken <YOUR_AUTHTOKEN>   # from https://dashboard.ngrok.com
   ```

3. **Register the app** at https://console.mentra.glass/apps
   - Create App → set `packageName` (e.g. `com.you.medglass`).
   - Add **MICROPHONE** permission (required for transcription) and
     **CAMERA** permission (for photo capture).
   - Set **Public URL** to your ngrok URL (after step 6).
   - Open the app in the Mentra phone app (Share → install link) — it is
     tied to your Mentra account.

4. **Install & configure this app**
   ```bash
   cd client/mentraos-app
   bun install
   cp .env.example .env
   # edit .env:
   #   PACKAGE_NAME = com.you.medglass     (must match console)
   #   API_KEY      = your app API key     (console → your app)
   #   MEDGLASS_URL = http://127.0.0.1:8100 (edge server, stays private)
   ```

5. **Run both servers**
   ```bash
   # Terminal 1 — MedGlass edge server (vision + note generation)
   bash scripts/start_server.sh 127.0.0.1 8100

   # Terminal 2 — MentraOS app
   cd client/mentraos-app && bun run dev        # port 3000
   ```

6. **Expose with ngrok** (Terminal 3)
   ```bash
   ngrok http 3000
   # copy the Forwarding URL, e.g. https://abc123.ngrok.io
   ```
   Update the app's **Public URL** in the Developer Console to that URL
   (no trailing slash). On free ngrok the URL changes each restart.

7. **Test on the glasses**
   - Open **MedGlass** in the Mentra phone app (it connects the glasses).
   - The app speaks "MedGlass ready…". Speak with your mock patient —
     transcripts build up, white LED while speaking.
   - **Short-press** the glasses button to capture a photo (medication bottle /
     rash) → it will be analyzed and spoken.
   - **Long-press** to generate the SOAP note → summary spoken + cards on the
     phone dashboard.

## Troubleshooting

| Symptom | Fix |
|---|---|
| No transcription events | MICROPHONE permission missing in console; reinstall app; check `bun run dev` logs |
| 401 on webhook | `API_KEY` / `PACKAGE_NAME` mismatch with console |
| "Connection refused" from ngrok | Start the app before ngrok; port must be 3000 |
| No events after restarting ngrok | Update Public URL in console (free URLs rotate) |
| Photo never arrives | CAMERA permission required; check the SDK `/photo-upload` flow |

## Local debug without glasses

MedGlass also ships a **web UI** (`http://127.0.0.1:8100`) and a Python
simulator (`client/simulator.py`) that drive the same edge endpoints, so you
can develop the AI pipeline before touching the glasses.
