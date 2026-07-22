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

## Project Materials

1. Live product:
   `https://radeon-voice-skill-foundry.pages.dev/`
2. Product Demo:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/RADEON_VOICE_SKILL_FOUNDRY_DEMO.mp4`
3. Project Specification: `PROJECT_SPECIFICATION.pdf`
4. Technical evidence: `TECHNICAL_EVIDENCE_INDEX.md`
5. Architecture: `ARCHITECTURE.png`
6. Poster: `POSTER.pdf`
7. Performance Demo:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/RADEON_VOICE_SKILL_FOUNDRY_PERFORMANCE_DEMO.mp4`
8. Continuous Operation Demo:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/CONTINUOUS_OPERATION_DEMO.mp4`
9. Package integrity: `SHA256SUMS.txt`
10. Source:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry`

Demo captions:
`https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/RADEON_VOICE_SKILL_FOUNDRY_DEMO.srt`

Demo proof package:
`https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/PRODUCT_DEMO_PROOF.zip`

Demo governance ledger:
`https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/GOVERNANCE_LEDGER.jsonl`

Official submission:
`https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/pull/7`

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

The public deployment includes a synthetic SOP fixture so no real confidential
material is needed when using the hosted application. The same source can also
run on a private network without the public gateway.

## Evidence Boundaries

- The Product Demo is the authoritative product recording.
- The Product Demo ends with a terminology card clarifying the exact Agent Skill
  Markdown, proof-hash, and ledger integrity boundaries.
- The Performance Demo's spoken `35/35` count belongs to its pinned recording
  revision; the submission regression suite is `63/63`.
- Proof ZIPs preserve immutable internal run and policy identifiers required
  for artifact verification; the submission exposes one canonical filename
  for each proof role.
- Voice Evidence values are internal deterministic quality-gate results, not
  external ASR accuracy measurements.
- The governance ledger uses SHA-256 payload and previous-entry hashes plus
  cross-checks against skill memory. It detects accidental or isolated
  modification in the stored artifacts. It is not an externally anchored,
  signed, or Byzantine-resistant audit log.
- The bundled governance ledger is the Product Demo sample and contains two
  `PROMOTE` entries. Supersede, revoke, and rollback remain implemented product
  lifecycle actions covered by the regression suite rather than events claimed
  to appear in this sample export.
- The Product Demo's recorded `GAIA-compatible` phrase refers only to portable
  Agent Skill Markdown. No external GAIA conformance or certification is
  claimed.
- Test counts belong to pinned revisions. The submission regression suite
  passes 63/63; Radeon benchmark snapshots retain their recorded counts.
- The synthetic Chinese SOP WAV is a reproducible fixture, not a claimed human
  recording.

## AI-Assisted Asset Disclosure

Demo narration uses AIDP `gemini-3.1-flash-tts-preview`, voice `Charon`.
Campaign backgrounds use GPT Image 2. Captions, project labels, diagrams, and
all reported measurements were derived or typeset from repository evidence.
