# Demo Video

**Private RAG Agent — Track 2 (2026 AMD AI DevMaster Hackathon)**

## 🎬 Primary video (submitted)

**`private_rag_agent_demo_narrated.mp4`** (in this folder) — **3 min 08 s, 1440×860, H.264 + English narration**.
A narrated walkthrough of the actual application running end to end (8 shots):

1. **Opening** — the empty-state UI: "100% local, offline, data never leaves this machine".
2. **Document ingestion** — three import modes (single file, whole folder, read-all local scan); knowledge base shows 6 documents · 15 chunks.
3. **Bilingual UI** — open the settings panel and switch the whole interface between English and Chinese with one click (English is the default).
4. **Single-agent Q&A** — live streaming answer with hybrid retrieval, citation cards, and the source drawer.
5. **Out-of-knowledge honesty** — ask a question outside the knowledge base; the agent answers the part it knows (labelling its source) and openly states the rest is "not in the knowledge base" instead of fabricating an answer.
6. **Multi-agent parallel** (the core) — plan panel with sub-task progress, parallel researcher agents, fact-check cards with grounding scores, and the final synthesized answer with a per-sentence verification panel.
7. **GPU acceleration** — the in-app AMD GPU monitor.
8. **Closing** — "retrieval you can trace, answers you can verify, data that stays on this machine."

> A silent full-length recording of the same run is also included (`private_rag_agent_demo.mp4`).
> For hosted sharing, upload to Bilibili / YouTube and add the URL below.

**Video link:** _(optional — add Bilibili / YouTube URL after upload)_

---

## What the video demonstrates

1. **Opening** — the empty-state UI: "100% local, offline, data never leaves this machine".
2. **Document ingestion** — importing PDF/Word/Markdown into the local knowledge base; badge updates to *6 documents · 15 chunks*.
3. **Bilingual UI** — the settings panel switches every label, button, and status message between English and Chinese with one click.
4. **Single-agent Q&A** — hybrid retrieval, streaming answer, clickable citation cards, and the source drawer with query terms highlighted in the original text.
5. **Out-of-knowledge honesty** — a question partly outside the knowledge base: the agent answers the known fact with a source label, and for the unknown part states plainly that it is "not in the knowledge base" rather than inventing one.
6. **Multi-agent parallel** (the climax) — the plan panel with sub-tasks and a progress bar, parallel researcher agents streaming retrieval events, fact-check cards with grounding scores, and the final answer composed only from verified content.
7. **GPU acceleration** — the in-app GPU monitor (utilization / VRAM / temperature). ROCm speed-up figures shown are *projected* (5–10× over CPU); the local CPU baseline is in `benchmarks/`.
8. **Closing** — "retrieval you can trace, answers you can verify, data that stays on this machine."

---

## Narration script

The full shot-by-shot English narration and production notes are in
[`src/docs/demo_video_EN.md`](src/docs/demo_video_EN.md) (also available as
[`demo_video_script.pdf`](demo_video_script.pdf)).

## Recording notes

- Record with OBS Studio / Bandicam: 1920×1080, 60 fps, high bitrate, MP4/H.264.
- All functional shots run fully live on a CPU-only machine — no GPU required.
- The GPU shot shows the in-app monitor; the 5–10× ROCm figure is clearly narrated as *projected*, and the local CPU baseline in `benchmarks/` is real. No numbers are faked.
