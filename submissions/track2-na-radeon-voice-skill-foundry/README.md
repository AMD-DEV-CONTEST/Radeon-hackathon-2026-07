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

1. Multi-turn interaction:
   [`MULTI_TURN_INTERACTION.md`](MULTI_TURN_INTERACTION.md)
2. Multi-turn Director Cut (35.5 seconds):
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/MULTI_TURN_INTERACTION_DIRECTOR_CUT.mp4`
3. Raw multi-turn product capture (32 seconds):
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/MULTI_TURN_INTERACTION_DEMO.mp4`
4. Multi-turn supplement screenshot:
   [`MULTI_TURN_INTERACTION_DEMO.png`](MULTI_TURN_INTERACTION_DEMO.png)
5. Parent-child lineage:
   [`MULTI_TURN_LINEAGE.png`](MULTI_TURN_LINEAGE.png)
6. Live product:
   `https://radeon-voice-skill-foundry.pages.dev/`
7. Submission evidence map:
   [`SUBMISSION_EVIDENCE_MAP.md`](SUBMISSION_EVIDENCE_MAP.md)
8. Product Demo:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/RADEON_VOICE_SKILL_FOUNDRY_DEMO.mp4`
9. Project Specification: [`PROJECT_SPECIFICATION.pdf`](PROJECT_SPECIFICATION.pdf)
10. Technical evidence: [`TECHNICAL_EVIDENCE_INDEX.md`](TECHNICAL_EVIDENCE_INDEX.md)
11. Architecture: [`ARCHITECTURE.png`](ARCHITECTURE.png)
12. Poster: [`POSTER.pdf`](POSTER.pdf)
13. Multi-turn evidence:
   [`MULTI_TURN_REFINEMENT.png`](MULTI_TURN_REFINEMENT.png) and
   [`MULTI_TURN_REFINEMENT.json`](MULTI_TURN_REFINEMENT.json), with
   [`MULTI_TURN_REFINEMENT_PROOF.zip`](MULTI_TURN_REFINEMENT_PROOF.zip)
14. Performance Demo:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/RADEON_VOICE_SKILL_FOUNDRY_PERFORMANCE_DEMO.mp4`
15. Continuous Operation Demo:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/CONTINUOUS_OPERATION_DEMO.mp4`
16. Package integrity: [`SHA256SUMS.txt`](SHA256SUMS.txt)
17. Source:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry`

Demo captions:
`https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/RADEON_VOICE_SKILL_FOUNDRY_DEMO.srt`

Verified workflow proof package:
`https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/VERIFIED_WORKFLOW_PROOF.zip`

Demo governance ledger:
`https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/GOVERNANCE_LEDGER.jsonl`

Official submission:
`https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/pull/7`

## Traceable Multi-Turn Interaction

A correction creates a new child compile instead of changing the parent in
place. The child records `parentRunId`, receives regenerated constraints,
permissions and fixtures, and must pass verification again.

The submitted public workflow demonstrates:

- user correction: require confirmation before creating calendar holds
- parent run: `run_dbc1a6e2c6b5`
- verified child run: `run_79b986c46400`
- revision: `1 -> 2`
- generated fixtures: `7`
- local knowledge matches: `3`
- child proof hash: `422bc40e...ead6522`

See [`MULTI_TURN_INTERACTION.md`](MULTI_TURN_INTERACTION.md) for the compact
lineage and evidence links.

## Implemented Track 2 Capabilities

- **Local knowledge retrieval:** deterministic token-overlap retrieval over
  policy and SOP documents stored with the application.
- **Tool invocation:** typed file, report, email-draft, email-send, calendar,
  and network capabilities.
- **Multi-step planning:** spoken intent and action evidence compile into an
  ordered procedure, constraints, permissions, fixtures, and proof artifacts.
- **Multi-turn interaction:** a natural-language correction creates a child
  compilation revision with `parentRunId`, regenerated constraints, and new
  fixtures while preserving the prior run.
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
- The bundled governance ledger is a verified workflow sample with one
  `PROMOTE` entry. Supersede, revoke, and rollback remain implemented product
  lifecycle actions covered by the regression suite rather than events claimed
  to appear in this sample export.
- The Product Demo's recorded `GAIA-compatible` phrase refers only to portable
  Agent Skill Markdown. No external GAIA conformance or certification is
  claimed.
- Test counts belong to pinned revisions. The submission regression suite
  passes 63/63; Radeon benchmark snapshots retain their recorded counts.
- The synthetic Chinese SOP WAV is a reproducible fixture, not a claimed human
  recording.
