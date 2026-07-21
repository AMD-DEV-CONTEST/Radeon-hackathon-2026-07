# Radeon Voice Skill Foundry

**Track 2: Development and Local Deployment of Private AI Agents**

**Participant:** Chengyuann
**Team:** N/A (solo)
**License:** MIT

Radeon Voice Skill Foundry converts a spoken operating procedure and six
server-recorded workflow actions into a reusable Agent Skill package. Before
reuse, the system retrieves local policy evidence, compiles typed constraints
and permissions, runs deterministic positive and adversarial tests, and
requires explicit human promotion.

## Judge Quick Path

1. Live product:
   `https://radeon-voice-skill-foundry.pages.dev/`
2. Final 4:49 Demo:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/RADEON_VOICE_SKILL_FOUNDRY_DEMO_V3.mp4`
3. Project Specification: `PROJECT_SPECIFICATION.pdf`
4. Scoring evidence: `SCORING_EVIDENCE_MATRIX.md`
5. Architecture: `ARCHITECTURE.png`
6. Poster: `POSTER.pdf`
7. Source:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry`

Demo captions:
`https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/RADEON_VOICE_SKILL_FOUNDRY_DEMO_V3.srt`

Demo proof package:
`https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/demo-v3-proof.zip`

Demo governance ledger:
`https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/final-submission-v1/demo-v3-governance-ledger.jsonl`

## Implemented Track 2 Capabilities

- **Local knowledge retrieval:** deterministic token-overlap retrieval over
  policy and SOP documents stored with the application.
- **Tool invocation:** typed file, report, email-draft, email-send, calendar,
  and network capabilities.
- **Multi-step planning:** spoken intent and action evidence compile into an
  ordered procedure, constraints, permissions, fixtures, and proof artifacts.
- **Local memory:** versioned skill records with candidate, promoted,
  superseded, and revoked states.
- **Permission and privacy controls:** explicit allow, review, and deny
  decisions; redaction; confirmation requirements; and server-authoritative
  action evidence.

The reference workspace is intentionally isolated. It creates email drafts,
tentative calendar holds, and a redacted report, but it does not send email,
commit invitations, or perform external network writes.

## Radeon and ROCm Evidence

- GPU: Radeon Pro W7900-class `gfx1100`, 47.98 GiB VRAM
- ROCm: 7.2.1
- Agent model: Qwen3-4B-Instruct-2507 FP16
- Speech model: Qwen3-ASR-0.6B FP16
- Agent median TTFT: 108.87 ms
- Agent median generation throughput: 22.02 tokens/s
- ASR warm median RTF: 0.0556, or 17.98x real-time
- vLLM graph concurrency-eight throughput: 257.65 output tokens/s
- Serialized Transformers concurrency-eight throughput: 20.66 output tokens/s
- Same-hardware serving throughput ratio: 12.47x
- Native ASR batch-eight: 85.35x aggregate real-time
- Compact output: 29.42% fewer output tokens and 30.03% lower generation
  latency

Exact reuse of an identical promoted skill measured 2.18 ms versus 24.09 s for
the recorded full compile path. This is an application fast path that avoids a
repeat model call; it is not presented as GPU inference acceleration for a new
or changed task.

The Quark INT8 study reduced model-load VRAM by 44.07% and increased KV-cache
capacity by 88.43%, but it was slower and failed the required policy-semantic
gate. The submitted production recommendation therefore remains FP16. This is
a measured rejection result, not a production quantization claim.

## Deployment and Privacy Boundary

Core ASR and Agent inference run on the participant-controlled Radeon Cloud
instance. Cloudflare Pages serves the public UI and forwards authenticated API
requests to that instance. Raw audio is not included in proof downloads.

Because the contest demo is publicly reachable through Cloudflare, reviewers
should use the supplied synthetic SOP fixture rather than real confidential
material. The same source can also run on a private network without the public
gateway.

## Evidence Boundaries

- Demo V3 is the authoritative final product recording.
- Demo V3 ends with a terminology card clarifying the exact Agent Skill
  Markdown, proof-hash, and ledger integrity boundaries.
- The Voice Evidence score is an internal deterministic quality-gate score,
  not an external ASR accuracy benchmark.
- The governance ledger uses SHA-256 payload and previous-entry hashes plus
  cross-checks against skill memory. It detects accidental or isolated
  modification in the stored artifacts. It is not an externally anchored,
  signed, or Byzantine-resistant audit log.
- Test counts belong to pinned revisions. The current local suite passes
  63/63; earlier Radeon validation snapshots retain their recorded counts.
- The synthetic Chinese SOP WAV is a reproducible fixture, not a claimed human
  recording.

## AI-Assisted Asset Disclosure

Demo narration uses AIDP `gemini-3.1-flash-tts-preview`, voice `Charon`.
Demo backgrounds use GPT Image 2. Captions, project labels, diagrams, and
all reported measurements were derived or typeset from repository evidence.
