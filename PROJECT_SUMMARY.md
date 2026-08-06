# GraphVoice Project Summary

**For:** Expert review and advice  
**Project:** Voice-driven conversational agent with graph-structured long-term memory  
**Hardware:** MacBook M5 16G (dev) → AMD 48G GPU (deploy)

---

## 1. What It Does

GraphVoice is a conversational agent that:
1. **Listens** to the user via microphone (AudioWorklet + Silero VAD)
2. **Interviews** the user to build their life story (graph-structured memory)
3. **Answers questions** about stored knowledge using LLM-generated Cypher queries
4. **Speaks back** with natural TTS (Qwen Omni voice)

The core idea: conversations become persistent, queryable graph structures — so the agent remembers, connects, and retrieves.

---

## 2. Architecture

```
Browser (AudioWorklet mic + playback)
  ↕ WebSocket (raw PCM16, 16kHz, 40ms chunks)
Flask Server (session management)
  ↕ HTTP + WS
Agent Pipeline:
  VAD (Silero/RMS) → STT (Qwen Omni) → Director LLM → 
  Cypher Generator (Qwen) → DB Executor (Neo4j) → Result Interpreter (Qwen) → 
  TTS (Qwen Omni) → Playback
  ↕ 
Neo4j (graph DB, movie test data + story graphs + memory)
```

**Key components:**

| Layer | File(s) | Purpose |
|-------|---------|---------|
| Audio | `audio/recorder.py`, `stt_client.py`, `vad.py`, `stream_handler.py`, `player.py` | Mic→PCM, Silero VAD state machine, STT via Qwen Omni, TTS via Qwen Omni SSE |
| Frontend | `frontend/index.html`, `worklets/*.js` | Always-listening browser UI, AudioWorklet mic capture (48k→16k resample + noise gate), AudioWorklet playback (ring buffer + fade-in/out), bilingual CN/EN |
| Agent | `agents/graph_agent.py`, `interviewee.py`, `interviewer.py` | Director LLM decides chat vs query, interview agent builds life graphs via conversation |
| Tools | `agents/tools/cypher_generator.py`, `db_executor.py`, `result_interpreter.py` | NL→Cypher generation, read-only DB execution, result→natural language |
| Memory | `memory/memory_graph.py` (conversation memory), `story_graph.py` (story graph v2) | Schema: 7 entity types (person/object/place/concept/skill/trait/body_part/feeling), 6 relationship types (RELATES_TO/IN_EVENT/NEXT/CAUSES/IN_PHASE/SYMBOLIZES) |
| Structurization | `memory/structurizer.py`, `evaluator.py` | LLM-based text→graph extraction, graph→text regeneration, quality scoring (LLM 1-10 + bigram overlap) |
| Server | `server.py` | Flask + flask-sock, /api/ask, /api/voice, /api/tts, /ws/listen |
| Database | `database/neo4j_client.py`, `schema_loader.py` | Neo4j wrapper, read-only enforcement, schema introspection |

---

## 3. Story Graph Schema (v2)

Compact, generalized schema for narrative structures:

```
Entity {name, type, description}
  types: person | object | place | concept | skill | body_part | feeling | trait
Event {label, description, order, time_period}
Phase {label, description, order}

Relationships (6):
  (:Entity)-[:RELATES_TO {type, context}]->(:Entity)  — any entity relation
  (:Entity)-[:IN_EVENT {role}]->(:Event)              — entity participates in event
  (:Event)-[:NEXT]->(:Event)                           — temporal sequence
  (:Event)-[:CAUSES {context}]->(:Event)               — causality
  (:Event)-[:IN_PHASE]->(:Phase)                       — life phase grouping
  (:Entity)-[:SYMBOLIZES {context}]->(:Entity)         — symbolic meaning
```

**Why this works:** Only 2 node types and 6 relationship types cover everything from Japanese inventor biographies to Journey to the West mythology. Tested across 4 domains (short stories, Chinese fiction, biographies, real Wikipedia bios).

**Key design decision:** Uses `RELATES_TO` as a universal edge with a `type` property instead of separate edge types (e.g., `[:FATHER_OF]`). This keeps the schema compact while allowing arbitrary relationship semantics.

---

## 4. Text → Graph → Text Pipeline (Structurization)

Validated across **13 diverse tests** with **9.4/10 average LLM quality score**:

| Source | Examples | Entities | LLM Score |
|--------|----------|----------|------------|
| Hand-crafted Chinese stories (3) | 小林 (inventor), 王铁匠 (sculptor), 萨蒂亚 (dancer) | 13–16 | 9.4–9.5 |
| Wikipedia biographies (6) | Marie Curie, Frida Kahlo, Alan Turing, Nelson Mandela, Maya Angelou, Bruce Lee | 13–21 | 9.2–9.4 |
| LLM-generated (3) | Curie, Kahlo, Turing | 24 | 9.4–9.7 |
| xyyuedu.com (1) | Marie Curie Chapter 1 (real narrative prose) | 16 | 9.4 |

**Pipeline flow:**
```
Raw text (400–1500 chars)
  → structurize_text() [LLM extracts JSON: entities, events, phases, relationships, causes, symbols, 40–70s]
  → StoryGraphBuilder.build() [writes to Neo4j, 0.3s]
  → regenerate_narrative() [LLM produces Chinese literary biography, 10–15s]
  → compute_loss() [bigram overlap + LLM quality score]
```

**Limitation:** Input ceiling is ~1500 chars (Qwen API times out on 2700+ char texts). For long-form content, chunking or summarization pre-processing is needed.

---

## 5. Interview Mode (Interviewer + Interviewee Agents)

Two-agent system for guided life-story collection:

**Interviewer agent** (`agents/interviewer.py`):
- Tracks coverage across 7 life phases (childhood, education, career, relationships, challenges, values, legacy)
- 5 strategies: OPEN, FOLLOW_UP, FILL_GAP, STEER, CLARIFY
- Coverage watchdog: detects missing phases and forces pivot questions

**Interviewee agent** (`agents/interviewee.py`):
- Simulated user with pre-defined life story (persona text)
- Configurable: verbosity (0.5–1.5), tangent_rate (0–1.0), emotional guard topics
- Simulated thinking delays (0.5–3s)
- Natural responses with sensory details and emotional nuance

**Simulation results** (5-round interview):
- 96% entity recall (23/24 entities from ground truth)
- Coverage: childhood 100%, education 52%, career 100%, relationships 100%, challenges 67%, values 100%, legacy 52%
- Found limitation: interviewer got absorbed in rich childhood narrative, didn't pivot to adult life — needs a coverage watchdog with forced pivot

---

## 6. Conversation Memory Layer

```
Conversation:
  (Session {id, created_at})
  (Message {id, role, content, timestamp})
  (Entity {name, type}) — auto-extracted via LLM
  (Fact {key, value})   — user preferences

  (Session)-[:HAS_MESSAGE]->(Message)
  (Message)-[:MENTIONS]->(Entity)
```

Integrated with the agent — every Q&A turn is stored, entities are extracted and linked. The Director LLM receives recent memory as context for follow-up questions and multi-turn coherence.

---

## 7. Technical Stack

| Component | Technology |
|-----------|-----------|
| LLM (text) | Qwen `qwen-plus` via OpenAI-compatible API |
| LLM (audio) | Qwen `qwen3.5-omni-flash` for STT + TTS |
| VAD | Silero VAD (neural) with RMS fallback |
| Graph DB | Neo4j 5 Community (Docker) |
| Frontend | Vanilla HTML/JS + AudioWorklet |
| Server | Flask + flask-sock (WebSocket) |
| Audio | PyAudio (CLI), Web Audio API (browser) |

---

## 8. Key Design Decisions

1. **In-browser AudioWorklet** over MediaRecorder — zero-copy, lossless PCM16, 40ms chunks, 48k→16k resampling, noise gate in audio thread
2. **Qwen Omni** for both STT and TTS — single model, multimodal chat API
3. **Compact graph schema** — 2 node types, 6 relationship types, universal applicability across all content domains tested
4. **RMS VAD fallback** — Silero model download blocked by network; RMS works correctly (speech=True, silence=False)
5. **Flask over FastAPI** — simpler for single-user dev; flask-sock for WebSocket
6. **Neo4j for both data and memory** — reuse same Docker container; 1.5GB fixed overhead acceptable for dev

---

## 9. Known Issues & Open Questions

| Issue | Severity | Context |
|-------|----------|---------|
| Qwen API times out on >2500 char extraction | Medium | Need chunking or summarization for long-form texts |
| Silero model can't download over current network | Low | RMS fallback works, accuracy tradeoff acceptable for dev |
| Neo4j 123,000x storage overhead at tiny scale | Low (expected) | Fixed overhead dominates; ratio improves dramatically with data volume |
| Interviewer needs coverage watchdog | Medium | Currently absorbs into rich narrative thread, misses mid-life phases |
| Bigram metric overly sensitive at <500 chars | Low | LLM score (1-10) is the more useful metric |
| No multi-user isolation | Low (future) | Single-user dev mode; session_ids ready for multi-user |

---

## 10. What We'd Like Expert Advice On

1. **Graph schema expressiveness vs complexity**: Is our 2-node, 6-relation schema hitting the right balance? Should we add more specialized relationship types or keep the universal `RELATES_TO {type}` pattern?

2. **Structurization quality at scale**: At 9.4/10 LLM score across 13 tests, is this "good enough" or should we invest in better extraction prompts, few-shot examples, or fine-tuning?

3. **Interview coverage strategy**: How should the interviewer balance depth (following rich narrative threads) vs breadth (ensuring all life phases are covered)? Should coverage be time-based (X rounds per phase) or quality-based?

4. **Audio → Text → Graph pipeline**: What are the known failure modes when STT errors (mis-transcriptions, missing context) cascade into structurization? Should we add a correction/confirmation step?

5. **Memory retrieval for multi-session context**: What's the best approach for the Director LLM to retrieve relevant memories from potentially thousands of stored messages? Vector embedding vs keyword vs graph traversal?

6. **Silero VAD quality on real hardware**: If we pre-download the Silero model, will it significantly outperform RMS VAD for distinguishing user speech from background conversation in a meeting-like scenario?
