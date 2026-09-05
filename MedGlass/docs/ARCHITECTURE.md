# Architecture

## System diagram

```
MENTRA GLASSES                     MEDGLASS EDGE SERVER (AMD GPU / ROCm)
┌──────────────┐  WebSocket/HTTPS  ┌─────────────────────────────────────────┐
│ camera / mic │──────────────────▶│ /ws/audio  /ws/video  /generate_note     │
│     HUD      │◀───── webhook ────│                                          │
└──────────────┘                   │  audio.py ─▶ whisper.cpp (hipBLAS)      │
                                   │       └─▶ ChunkBuffer (5s windows)      │
                                   │  video.py ─▶ YOLOv8-seg (ONNX ROCm)     │
                                   │       └─▶ EasyOCR (ROCm) ─▶ findings    │
                                   │  context_builder ─▶ llm (llama.cpp)     │
                                   │       └─▶ hud_output ─▶ glasses / file  │
                                   └─────────────────────────────────────────┘
```

## Data flow

1. **Audio** — glasses stream 16 kHz mono PCM to `/ws/audio`. `ChunkBuffer`
   keeps the last `window_seconds + overlap_seconds` of audio; when a fresh
   5 s window is available it is written to a temp WAV and passed to
   `whisper-cli --print-json` (hipBLAS). Incremental transcripts are appended
   to the session state and echoed back to the client.
2. **Video** — frames arrive as base64 JPEG on `/ws/video`. `VideoProcessor`
   letterboxes to 640×640, runs YOLOv8n-seg via ONNX Runtime, and routes each
   detected box (medication bottles/books/documents) to EasyOCR. OCR results
   become visual findings.
3. **Context** — `context_builder.build_prompt` concatenates the system
   prompt, few-shot SOAP example, transcript, and visual findings.
4. **Generation** — `llm_handler` writes the prompt to a temp file and invokes
   `llama-cli` (ROCm). Streaming tokens are forwarded over SSE
   (`/generate_note/stream`) and collected into a full note.
5. **Output** — the note is split into S/O/A/P, pushed to the HUD
   (`hud_output`), and stored as `output/soap_note.{txt,json}`. PHI is
   sanitized before storage when `strip_phi_on_store` is true.

## Concurrency model

- One `SessionState` per `session_id` holds the audio window, rolling
  transcript, and visual findings.
- Transcription is fire-and-forget (`create_task`) so new PCM keeps flowing
  while whisper.cpp works; windows overlap so no words are lost.
- Vision and LLM models are lazy singletons to keep VRAM within budget.

## Failure tolerance

| Component failure | Fallback |
|---|---|
| Mentra SDK / glasses | `client/simulator.py` (webcam + mic) or the browser UI at `/` |
| whisper.cpp hipBLAS build / no compiler | `pywhispercpp` prebuilt CPU wheel (auto-selected) |
| llama.cpp / Qwen missing | `template` LLM backend — deterministic SOAP from transcript |
| YOLO ONNX ROCm EP | CPU ONNX (auto-selected) |
| easyocr missing | medication OCR skipped; visual findings still logged |
| GPU OOM | lazy model loading, max 2 models resident |

## Privacy

No data leaves the server. WebSocket frames and HUD payloads carry only
transcript text, detection metadata, and OCR strings. PHI patterns are
redacted on local store (`sanitize_phi`). This is a privacy *helper* — final
HIPAA review is out of scope for a hackathon.
