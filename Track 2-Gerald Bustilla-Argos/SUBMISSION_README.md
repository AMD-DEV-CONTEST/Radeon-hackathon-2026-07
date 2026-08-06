# Track 2 — GERALD BUSTILLA — Argos

## Submission Materials

| Item | File | Status |
|------|------|--------|
| Project Specification Document | [Project_Specification.md](./Project_Specification.md) | ✅ |
| Project Source Code | [https://github.com/Zrald1/amdagentic](https://github.com/Zrald1/amdagentic) | ✅ |
| README (env config, startup, deps) | [README.md](./README.md) | ✅ |
| Demo Video | _To be recorded (3-5 min)_ | ⏳ |
| Supplementary: PPT | [Argos_Presentation.pptx](./Argos_Presentation.pptx) | ✅ |

## Quick Summary

**Argos** is an AI companion robot that lives on your Windows desktop as a floating overlay. It features:

- **38+ tools** with agentic loop (up to 8 iterations) — browser automation, file ops, screen reading, keyboard control
- **RAG** — TF-IDF + BM25 + Reciprocal Rank Fusion, persistent disk index, manual folder sync
- **Multi-turn memory** — JSONL persistence, cross-session recall
- **Multi-step task planning** — AI decomposes complex tasks via tool loop
- **Privacy & permission control** — No hardcoded keys, config file + env vars, no telemetry
- **Voice input** — Local Whisper speech-to-text (push-to-talk via Caps Lock)
- **Visual robot** — Direct2D Spartan warrior with shield & sword, electric lightning during tool execution

### Capabilities (5 of 5 implemented, minimum was 2)

1. ✅ Local knowledge retrieval (RAG)
2. ✅ Tool invocation
3. ✅ Multi-step task planning
4. ✅ Local multi-turn memory
5. ✅ Permission control & privacy protection

### Tech Stack

- C++17, Win32 API, Direct2D
- AMD Radeon Cloud API (OpenAI-compatible): DeepSeek-V4-Flash, MiniCPM5-1B, Qwen3.6-35B-A3B
- whisper.cpp (local speech-to-text, GGML)
- Custom RAG engine (TF-IDF + BM25 + RRF)

### Build

```bash
git clone https://github.com/Zrald1/amdagentic.git
cd amdagentic\cpp
build.bat
```

### Configuration

No hardcoded API keys. Users configure via:
1. Environment variables: `ARGOS_API_KEY`, `ARGOS_SERVER_URL`, `ARGOS_MODEL`
2. Config file: `argos_config.txt` (next to exe or `%APPDATA%\Argos\`)
3. In-app Settings UI (auto-saves to config file)
