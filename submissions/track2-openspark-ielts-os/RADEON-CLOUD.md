# Radeon Cloud Development Setup (Hackathon Track 2)

The AI service speaks the OpenAI-compatible protocol, so one codebase runs
against two backends:

- Development: Radeon Cloud free API (AMD GPU cloud, Qwen3.6-35B-A3B)
- Submission/demo: local Ollama, or vLLM inside a Radeon Cloud Workspace
  (the private-deployment story)

## Quick Start

```bash
npm run agent:radeon       # uses .env.radeon, Radeon Cloud backend
npm run agent:dev          # default local Ollama (http://127.0.0.1:11434/v1, qwen3:8b)
npm run check:local-agent  # offline self-check (stubbed upstream, no quota used)
```

The server also statically hosts the main app: http://127.0.0.1:8790/ opens
the full IELTS OS application and auto-verifies the current origin as the AI
endpoint (no manual settings). The bottom "AI" tab contains the AI Tutor
panel backed by `/api/agent`; `/demo` is the standalone agent demo page.

## Environment Variables

| Variable | Description |
| --- | --- |
| `OLLAMA_BASE_URL` | OpenAI-compatible endpoint; Radeon Cloud is `https://developer.amd.com.cn/radeon/api/v1` |
| `LOCAL_MODEL` | Model name; `Qwen3.6-35B-A3B` on Radeon Cloud |
| `LLM_API_KEY` | Key from Radeon Cloud Token Factory (`rc-` prefix); leave empty for local Ollama |
| `LLM_DISABLE_THINKING` | Set `1` to disable Qwen3 hidden reasoning and avoid free-tier timeouts |
| `LLM_MAX_TOKENS` | Answer token cap; keep ≤ 384 on the free tier (~120 s gateway timeout) |
| `LIBRARY_ROOT` | Personal material library root; defaults to the local iCloud IELTS folder. `/library/<relative path>` streams PDF/audio/video with HTTP Range support |

## Field Notes (2026-08-03, free tier)

- Throughput is ~3-6 tok/s and the gateway drops requests after ~120 s;
  longer generations fail with `Model gateway is unavailable`.
- Qwen3.6 enables thinking mode by default and reasoning tokens consume the
  `max_tokens` budget — always set `LLM_DISABLE_THINKING=1`.
- Tool calling works (`finish_reason=tool_calls`) and supports multiple
  parallel calls in one turn.
- `.env.radeon` is git-ignored; keys never enter the repository.
