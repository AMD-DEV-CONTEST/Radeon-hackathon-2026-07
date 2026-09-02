# IELTS OS · Private AI Study Agent — Project Specification

**Track 2: Development & Local Deployment of Private AI Agents**

## 1. Application Scenarios

IELTS OS is a local-first study companion for IELTS candidates. Learners keep
their vocabulary book, synonym library, mistake notes and personal material
library on their own machine. A built-in **private AI study agent** answers
questions, reviews Listening and Reading evidence, corrects Writing drafts and
runs Speaking Live sessions. A persistent learning memory connects all four
skills to the next plan, so the coach acts on the learner's real answers,
recurring mistakes and recent progress instead of using a generic chatbot persona.

Typical conversations:

- "Based on my study status, plan today's review." → the agent reads the live
  study queue and mistake notes, then looks up each word it cites.
- "Have I learned the word *approach*? Explain it." → the agent looks up the
  learner's own 8,000-word book, including memory state.
- "What listening materials do I have?" → the agent searches the local index
  of the learner's personal material library.
- Listening evidence review, Reading answer-and-hint review, Writing correction
  and Speaking dialogue/debrief share the same OpenAI-compatible contract
  (`/api/ai`).
- A full-screen live speaking session transcribes each answer, speaks the next
  question, then produces a dialogue summary, transcript-based ability review,
  model answer and next drill. The result is stored in local learning memory
  for the next session. Pronunciation is explicitly left unscored until an
  audio-capable local model is connected.

## 2. Agent Architecture

```text
┌───────────────────────────────────────┐
│ IELTS OS Web App (PWA / Capacitor)    │
│  · AI Tutor panel      → /api/agent   │
│  · Four skill reviews  → /api/ai      │
│  · Material viewer     → /library/*   │
│  · Long-term memory    → localStorage │
└──────────────────┬────────────────────┘
                   │ local REST, OpenAI-compatible
┌──────────────────▼────────────────────┐
│ local-agent-server.mjs (Node, no deps)│
│  · static hosting of the app          │
│  · agent loop (≤12 steps, parallel    │
│    tool calls, visible trace)         │
│  · tools over local JSON data:        │
│    lookup_word · find_synonyms ·      │
│    search_library · get_study_status ·│
│    get_learning_memory                │
│  · /library/* streams personal files  │
│    with HTTP Range support            │
└──────────────────┬────────────────────┘
                   │ chat/completions (+tools)
┌──────────────────▼────────────────────┐
│ Model backend — interchangeable:      │
│  · Radeon Cloud (AMD GPU cloud):      │
│    Qwen3.6-35B-A3B                    │
│  · Fully offline: Ollama / vLLM with  │
│    qwen3:8b on an AMD Radeon GPU      │
└───────────────────────────────────────┘
```

Key properties:

- **Personal files never leave the machine.** Radeon Cloud receives model
  prompts and tool results during development. With a local Ollama/vLLM
  backend, those requests also stay on the machine.
- **API keys live only on the server side** (`.env`, git-ignored). The web app
  stores just the endpoint URL.
- **Zero runtime dependencies.** The server uses only the Node.js standard
  library; the app is plain HTML/CSS/JS.

## 3. Core Capabilities

| Capability | Implementation |
| --- | --- |
| Private personal assistant | In-app AI Tutor chat panel; answers cite the learner's own records |
| Local knowledge-base QA | Agent tools query the 8,000-word book, 99 synonym groups and the personal library index |
| Tool calling | 5 local tools with a visible call trace in the UI |
| Multi-step planning | Agent loop up to 12 steps; independent lookups batched in one turn |
| Privacy | Personal files stay local; Ollama/vLLM mode also keeps prompts and tool results local |
| Persistent personalization | Local learning memory stores four-skill reviews, dialogue transcripts, weak areas and recent evidence |
| Live speaking coach | Full-screen browser/iPhone voice mode, spoken AI follow-ups, summary and transcript-based ability review |
| Four-skill coaching | Listening/Reading evidence review, Writing correction, Speaking Live debrief and prioritized next-task recommendations |

## 4. Why This Is Not Another Vocabulary App

IELTS OS does not compete on the size of a generic course catalog. Its core
unit is a **personal evidence loop**:

1. The learner completes a real task or live conversation.
2. The app stores the answer, transcript, mistakes and timing locally.
3. The agent reads that evidence through tools and long-term memory.
4. It gives one high-impact correction, a stronger model answer and a concrete
   next drill.
5. The result becomes context for the next session.

Listening answers, Reading evidence and hints, Writing drafts, Speaking
transcripts, vocabulary, mistakes and personal materials feed one coach rather
than remaining separate features. A fully local AMD Radeon deployment keeps
that evidence loop on the learner's machine.

## 5. Model & Local Deployment Plan

Development/demo backend: **Qwen3.6-35B-A3B served on AMD Radeon GPUs**
(Radeon Cloud, OpenAI-compatible endpoint). The same endpoints run unchanged
against a fully local backend:

```bash
ollama pull qwen3:8b        # or vLLM with a Qwen checkpoint
npm run agent:dev           # OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
```

For a Radeon workstation, vLLM with ROCm serves the same
`chat/completions` contract; switching backends is one environment variable
(`OLLAMA_BASE_URL`), no code change. Tool calling is exercised end-to-end by
the offline self-check with a stubbed upstream:
`npm run check:local-agent`.

## 6. Inference-Speed Optimization on AMD Radeon GPU

Measured against the shared Radeon Cloud free tier (August 2026):

| Observation | Effect | Mitigation in this project |
| --- | --- | --- |
| Qwen3.6 hidden "thinking" burns the token budget | 64-token cap produced *only* reasoning, empty answer | `LLM_DISABLE_THINKING=1` injects `chat_template_kwargs: {enable_thinking: false}` |
| Gateway hard-cuts requests at ~120 s | long generations return "Model gateway is unavailable" | `LLM_MAX_TOKENS=384` keeps answers inside the time budget; concise system prompts |
| Transient gateway failures under load | sporadic 5xx | server retries transient failures once; client retries once more; honest error messages |
| Multi-step agents amplify latency | 8 sequential lookups hit the step cap before answering | system prompt caps cited lookups and requests parallel tool calls in one turn |

One final live Listening validation completed in 4.0 s. Shared free-tier queue
latency varied substantially during recording. Other observed end-to-end
latencies were ~20 s for a full study-plan agent run (status + 8 word lookups +
plan) and ~50 s for writing feedback.

## 7. Repository Notes

- Bundled training content is **original sample material** (3 reading
  passages, 3 listening scripts, 6 writing tasks). Commercial materials stay
  in the learner's personal library and are never redistributed; see
  `CONTENT-LICENSING.md`.
- 21 automated checks cover the learning loops, data contracts and the agent
  server: `npm run check`.
