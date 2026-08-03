# YIJIAN: From Superhuman Go to Human Understanding

> A private, evidence-grounded AI Go coach powered by KataGo, Qwen and AMD Radeon.

**Track 2 — AI Agent Application Development**  
**Participant:** Ali Moqi  
**Tagline:** Every superhuman move, made understandable.

![YIJIAN agent workspace](assets/yijian-agent-workspace.png)

## Why YIJIAN

Go engines can identify a stronger move, but most players still need a coach to explain *why* it is stronger. Generic language models often sound fluent while confusing the played move with the engine recommendation, inventing board relationships, or describing the wrong region.

YIJIAN closes that gap. It turns a game record and a KataGo result into a traceable teaching object, then asks Qwen to express only what the evidence supports. The result is an interactive review experience that can discuss thickness, territory, initiative, trade-offs, ko threats, shape, joseki and local fighting without allowing the language model to rewrite engine facts.

## What makes it an agent

YIJIAN is not a chat wrapper. For every question it:

1. reconstructs the exact board state from the SGF;
2. resolves which move the user is asking about;
3. calls KataGo for candidates, values and principal variations;
4. derives deterministic board relations and teaching evidence on the server;
5. asks Qwen to form a human explanation from that evidence;
6. validates coordinates, regions, subjects and numerical claims;
7. repairs or falls back to a deterministic answer when validation fails;
8. stores reusable analysis in SQLite for fast reopening.

This separation keeps four different layers explicit:

- **KataGo facts:** candidates, win rate, score lead, visits and variations.
- **Rule facts:** legality, liberties, captures, adjacency and board coordinates.
- **Heuristic teaching judgments:** thickness, urgency, direction, trade-offs and timing.
- **LLM expression:** wording, structure and level-appropriate explanation.

## Core capabilities

- Full-game scan with critical-node re-analysis.
- Move-by-move teaching cards backed by server-rebuildable evidence.
- Context-aware follow-up questions about either the played move or the AI move.
- Board demonstrations of the recommended continuation.
- Classical Go terminology and principle-oriented explanations.
- Local-first game storage and an explicit opt-in path for remote GPU inference.
- Persistent SQLite caching to avoid recomputing finished analysis.

## AMD Radeon implementation

The current demo runs on an **AMD Radeon PRO W7900 48 GB**:

- **KataGo v1.16.5**, official b40 network, OpenCL backend.
- **Qwen3.6-27B Q4_K_M**, served by `llama.cpp` on ROCm 7.2.1.
- **32 visits** for the whole-game scan.
- **128 visits** for critical-position verification.
- GPU work is scheduled so that KataGo analysis completes before the local LLM generates batch narratives.
- Model and KataGo endpoints bind to loopback interfaces; remote access uses an authenticated SSH tunnel.

Measured on the W7900 demo instance:

| Workload | Result |
|---|---:|
| KataGo scan, 33 positions × 32 visits | 13.55 s total |
| KataGo critical-position check, 128 visits | 2.63 s |
| Evidence-grounded coach evaluation | 6/6 constructed cases passed |
| Coach evaluation P95 latency | 9.536 s |
| Automated regression tests | 373 total |

The six-case coach benchmark is a constructed acceptance set, not a claim of general Go strength. KataGo remains the numerical authority.

## Submission package

- [Project Specification](PROJECT_SPECIFICATION.md)
- [Performance and Validation](PERFORMANCE_AND_VALIDATION.md)
- [Demo Runbook](DEMO_RUNBOOK.md)
- [Presentation](YIJIAN-Track-2-Presentation.pptx)
- [Project Specification PDF](YIJIAN-Project-Specification.pdf)
- [Public source snapshot](source/)
- [Third-party and data-boundary notes](THIRD_PARTY_AND_DATA_BOUNDARY.md)

## Quick start

See [source/README.md](source/README.md) for local and Radeon cloud setup instructions.

The repository intentionally excludes model weights, private game records, creator-derived transcripts, review annotations, authorization screenshots, local databases, credentials and SSH configuration.

## Demo video

The final 3–5 minute English demo link will be added to this README before the pull request is marked ready for judging. The accompanying runbook already defines the required scenes and Radeon performance proof.

## License and attribution

Source code in this submission snapshot is provided for hackathon evaluation. Third-party components retain their original licenses; see [source/THIRD_PARTY_NOTICES.md](source/THIRD_PARTY_NOTICES.md). No third-party creator transcript or private training record is included in this public submission.
