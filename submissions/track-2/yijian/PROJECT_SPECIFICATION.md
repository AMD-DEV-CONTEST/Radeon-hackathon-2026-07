# YIJIAN Project Specification

## 1. Project overview

**YIJIAN** is a private, evidence-grounded AI Go coach. It converts KataGo analysis into explanations that a human player can verify, question and replay on the board.

The project addresses a specific failure mode in current AI review products: numerical strength does not automatically produce teaching quality. A Go engine can rank candidate moves, while a language model can speak fluently, yet the combined system may still confuse coordinates, answer about the wrong move, or use generic Go vocabulary that is unrelated to the position. YIJIAN treats this as an agent-engineering problem rather than a prompting problem.

## 2. Target users and scenarios

### Target users

- Club and online Go players who want to understand mistakes rather than only see win-rate loss.
- Teachers who need a traceable starting point for review.
- Advanced learners who ask about thickness, territory, initiative, shape, ko and direction of play.
- Privacy-conscious users who do not want raw game records uploaded to an uncontrolled service.

### Primary scenario

1. The user imports an SGF or GIB record.
2. YIJIAN scans the game and identifies high-value review nodes.
3. The user opens a node and sees the played move, the AI move and the numerical change.
4. The coach explains the local and global trade-off.
5. The user asks a follow-up question about either move.
6. YIJIAN reconstructs the subject, gathers new evidence, and answers with validated terminology and coordinates.
7. The user plays the recommended variation on the board.

## 3. Agent architecture

### 3.1 Control plane

The FastAPI service owns the workflow. The browser never decides which engine fact is true and never fabricates teaching evidence. A position context is identified by the game, turn, variation and board hash.

### 3.2 Evidence plane

The server builds a structured teaching context from four sources:

1. **KataGo facts** — recommended candidates, visits, win rate, score lead and principal variations.
2. **Go-rule facts** — board reconstruction, legality, captures, liberties, adjacency and coordinate conversion.
3. **Deterministic teaching features** — subject move, board region, nearby groups, local fighting signals, urgency and candidate relationships.
4. **Validated heuristics** — teaching interpretations that are clearly marked as explanatory judgments rather than engine output.

Each answer carries a context identifier and evidence hash so the service can rebuild and audit its source.

### 3.3 Expression plane

Qwen receives the structured evidence and the conversation context. It selects a response shape appropriate to the question instead of forcing every question into one fixed template. It may compare moves, explain a tactical sequence, discuss timing, or give a concise conclusion.

The model is not allowed to override the subject move, candidate coordinates, board regions or engine numbers.

### 3.4 Validation and repair

The answer validator checks:

- whether the response answers the move the user selected;
- whether played and recommended moves remain distinct;
- whether every mentioned coordinate exists in the evidence;
- whether region descriptions agree with board coordinates;
- whether numerical claims match KataGo output;
- whether unsupported certainty or contradictory language appears.

If validation fails, the agent retries with structured repair feedback. If a safe repair is not possible, it returns a deterministic evidence summary.

### 3.5 Persistence

SQLite stores imported game metadata, analysis jobs, evidence contexts, reports, feedback and reusable narrative results. Reopening a completed game reads cached results instead of repeating GPU work.

## 4. Core capabilities

- SGF/GIB import and exact board replay.
- Whole-game analysis and ranked critical nodes.
- 32-visit scan plus 128-visit critical verification.
- Evidence-grounded move explanation.
- Follow-up dialogue anchored to the selected move.
- Variation playback and board highlighting.
- Terminology support for classical and modern Go concepts.
- Deterministic fallback when the language model is unavailable or unsafe.
- Local-first storage with explicit remote-compute opt-in.

## 5. Models and local deployment

### KataGo

- Version: KataGo v1.16.5.
- Network: official `kata1-zhizi-b40c768nbt-s11272M-d5935M` model.
- Backend on the demo system: OpenCL.
- Role: sole authority for candidate ranking and numerical evaluation.

### Language model

- Model: Qwen3.6-27B, dense, Q4_K_M GGUF.
- Runtime: self-hosted `llama.cpp` server.
- Accelerator: AMD ROCm 7.2.1 on Radeon PRO W7900 48 GB.
- Role: evidence-constrained teaching expression and follow-up dialogue.

The current main path uses the 27B base model with agent-side evidence construction and validation. Historical small-model LoRA experiments are not presented as the main runtime and no private creator-derived training data is included in this submission.

## 6. Radeon GPU optimization

### Scheduling

The full-game pipeline is staged:

1. GPU KataGo scan at 32 visits.
2. CPU SGF parsing, phase classification and feature extraction run concurrently where possible.
3. GPU KataGo rechecks critical nodes at 128 visits.
4. After engine pressure drops, the local Qwen server generates batch narratives.
5. Results are committed to SQLite.

This avoids running the engine and the LLM at maximum load at the same time on one GPU.

### Quantization and fit

The 27B dense model uses Q4_K_M quantization so it fits comfortably within the W7900's 48 GB VRAM together with runtime buffers. The model server binds to loopback and is accessed through a narrow OpenAI-compatible interface.

### Repeatability

The public snapshot includes installation, start, smoke-test and benchmark scripts under `source/deploy/cloud/`. Model weights are downloaded separately and are never committed.

## 7. Measured results

On the Radeon PRO W7900 demo instance:

- 33 KataGo positions at 32 visits: 13.55 seconds total.
- One 128-visit verification: 2.63 seconds.
- Six constructed evidence-grounding cases: 6/6 passed.
- Coach evaluation P95 latency: 9.536 seconds.
- Regression suite: 125 backend tests plus 248 training/data tests, 373 total.

These measurements demonstrate the implemented system under the stated configuration. They do not claim universal latency or playing strength across other hardware, models or positions.

## 8. Privacy, safety and data boundaries

- Game records stay local unless the user explicitly enables remote KataGo.
- Remote model and engine ports are not exposed publicly.
- Provider keys remain in server environment variables.
- The browser receives derived evidence, not provider secrets.
- Public submission assets exclude private SGFs, SQLite databases, creator transcripts, review drafts, authorization conversations, model weights and SSH credentials.
- KataGo facts, Go-rule facts, heuristics and LLM prose remain separately identifiable.

## 9. Current limitations

- The six-case coach benchmark is deliberately small and constructed; broader expert review is still required.
- Long-term personalized student memory is not yet a production capability.
- Retrieval-augmented generation over a licensed Go corpus is not yet the main answer path.
- The product currently prioritizes Chinese coaching; the submission material is English for the competition.
- Engine output can prove numerical preference but cannot by itself prove every high-level teaching interpretation.

## 10. Why this project matters

YIJIAN uses a powerful Radeon GPU for more than raw inference throughput. It coordinates a superhuman engine, a dense local language model, deterministic Go rules, validation and privacy controls into one teaching agent. The product contribution is not simply a better answer. It is a trustworthy path from a move recommendation to a human-understandable reason.
