# Media Production Plan

This checklist turns `demo-script.md` into the required 3–5 minute video and
keeps every visible performance claim tied to reproducible Radeon evidence.

## Capture Layout

- Record at 2560×1440, 30 fps, and export at 1920×1080 or higher.
- Use a browser zoom that keeps the Session field, active tab label, JSON keys,
  pending preview, and confirmation receipt readable.
- Prepare two terminal layouts before recording:
  1. ROCm/HIP identity plus llama.cpp initialization and offload log;
  2. timestamped GPU utilization/VRAM samples and final evidence summaries.
- Use the same synthetic guest, clean app lifecycle, and model-service lifecycle
  throughout the live UI journey.
- Shorten only idle inference waits. Add the same visible notice to every cut:
  `Inference wait shortened — same live run`.

## English Subtitle Track

- Use the narration column in `demo-script.md` as the subtitle source.
- Deliver both a sidecar `.srt` or `.vtt` and a review copy with captions burned
  in. Keep each cue to at most two lines and roughly 42 characters per line.
- Do not place captions over the Request box, active JSON tab, pending preview,
  confirmation button, booking ID, Session field, or GPU telemetry.
- Translate the meaning of the Chinese guest interaction; do not cover or replace
  the original multilingual UI text.
- Read identifiers such as ROCm, HIP, llama.cpp, RAG, and GPU consistently. Avoid
  narrating long hashes; let the evidence remain visible on screen.

## Evidence Asset Checklist

| Asset | Final source | Status before final recording |
| --- | --- | --- |
| ROCm/HIP and detected GPU identity | Bound target-system evidence | `[PENDING_FINAL_ASSET]` |
| llama.cpp native backend and positive offload | Complete server lifecycle log | `[PENDING_FINAL_ASSET]` |
| Inference-window GPU utilization and VRAM | Same-run monitor log | `[PENDING_FINAL_ASSET]` |
| Primary UI journey | One real captured session | `[PENDING_FINAL_ASSET]` |
| 30-case quality result | Final quality JSON and binding manifest | `[PENDING_FINAL_ASSET]` |
| Qualified Reference metrics | Complete A or B Reference bundle | `[PENDING_FINAL_ASSET]` |
| Best accepted metrics | Complete accepted evidence bundle | `[PENDING_FINAL_ASSET]` |
| Reference-versus-Winner comparison | Comparator JSON generated from both bundles | `[PENDING_FINAL_ASSET]` |
| Repository or submission QR | Final public submission URL | `[PENDING_FINAL_ASSET]` |
| English captions | Timed from the locked video edit | `[PENDING_FINAL_ASSET]` |

## Qualified Reference Versus Winner Card

Build the final result card from parsed JSON, not manually transcribed numbers.
Use the following labels until the evidence is complete; placeholders must not
appear in the submitted video:

| Field | Quality-qualified Reference | Accepted Winner |
| --- | --- | --- |
| Experiment label | `[REFERENCE_LABEL]` | `[WINNER_LABEL]` |
| Quality score | `[REFERENCE_QUALITY]` | `[WINNER_QUALITY]` |
| Core latency metric(s) | `[REFERENCE_LATENCY]` | `[WINNER_LATENCY]` |
| Successful throughput | `[REFERENCE_THROUGHPUT]` | `[WINNER_THROUGHPUT]` |
| Effective output tokens/s | `[REFERENCE_TOKEN_RATE]` | `[WINNER_TOKEN_RATE]` |
| Comparison decision | Reference | `[ACCEPTANCE_STATUS]` |

The card must state that both sides use the same model artifact, llama-server
binary, source/workload, policy corpus, and physical GPU evidence. A is the
Reference only when it passes 300/300; otherwise the bound A quality negative is
shown separately and B is the Reference. Do not label a configuration “Winner”
unless the selector accepted it under the final rules.

## Privacy and Continuity Review

Before export, inspect the video frame by frame for:

- `.env` contents, identity secrets, confirmation capabilities, private SSH details,
  real names, complete unique booking/ticket/session/request/audit IDs, or local
  paths that should not be public;
- a Session value that accidentally changes before the cross-identity denial;
- an output inserted without its corresponding live request;
- a confirmation shown without its preceding preview;
- GPU utilization that falls outside the demonstrated inference window;
- a performance claim without its raw bound artifact;
- captions obscuring the exact evidence being discussed.

## Final Deliverables

- 3–5 minute 1080p-or-higher demonstration video;
- English `.srt` or `.vtt` subtitle file;
- captioned review export;
- bilingual nine-slide presentation and PDF export;
- final project-specification PDF;
- evidence bundle or stable link referenced by the video and presentation.
