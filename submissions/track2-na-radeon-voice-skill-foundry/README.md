# Radeon Voice Skill Foundry

**Track 2: Development and Local Deployment of Private AI Agents**

**Participant:** Chengyuan Ma (`@Chengyuann`)
**Team:** None (solo)
**License:** MIT

Radeon Voice Skill Foundry converts a spoken operating procedure and six
server-recorded workflow actions into a reusable Agent Skill package. Before
reuse, the system retrieves local policy evidence, compiles typed constraints
and permissions, runs deterministic positive and adversarial tests, and
requires explicit human promotion.

## Judge First

1. [Judge result card](JUDGE_RESULT_CARD.png)
2. [Primary 4:49 Product Demo](https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/RADEON_VOICE_SKILL_FOUNDRY_DEMO.mp4)
3. [Live product](https://radeon-voice-skill-foundry.pages.dev/)
4. [Judge quickstart](JUDGE_QUICKSTART.md)
5. [35.5-second multi-turn Director Cut](https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/MULTI_TURN_INTERACTION_DIRECTOR_CUT.mp4)
6. [48.96-second unedited W7900 proof](https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/W7900_LIVE_EVIDENCE_UNEDITED.mp4)

## Project Materials

1. Judge quickstart:
   [`JUDGE_QUICKSTART.md`](JUDGE_QUICKSTART.md)
2. Primary contest Product Demo (4:49):
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/RADEON_VOICE_SKILL_FOUNDRY_DEMO.mp4`
3. Supplementary unedited W7900 live evidence (48.96 seconds):
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/W7900_LIVE_EVIDENCE_UNEDITED.mp4`
4. Unedited W7900 stage captions:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/W7900_LIVE_EVIDENCE_UNEDITED.srt`
5. W7900 live evidence summary:
   [`W7900_LIVE_EVIDENCE_SUMMARY.json`](W7900_LIVE_EVIDENCE_SUMMARY.json)
6. Public health summary and full history:
   [`PUBLIC_HEALTH_SUMMARY.json`](PUBLIC_HEALTH_SUMMARY.json) and
   [`PUBLIC_HEALTH_HISTORY.jsonl`](PUBLIC_HEALTH_HISTORY.jsonl)
7. Reproducibility:
   [`REPRODUCIBILITY.md`](REPRODUCIBILITY.md)
8. Multi-turn interaction:
   [`MULTI_TURN_INTERACTION.md`](MULTI_TURN_INTERACTION.md)
9. Multi-turn Director Cut (35.5 seconds):
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/MULTI_TURN_INTERACTION_DIRECTOR_CUT.mp4`
10. Raw multi-turn product capture (32 seconds):
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/MULTI_TURN_INTERACTION_DEMO.mp4`
11. Multi-turn supplement screenshot:
   [`MULTI_TURN_INTERACTION_DEMO.png`](MULTI_TURN_INTERACTION_DEMO.png)
12. Parent-child lineage:
   [`MULTI_TURN_LINEAGE.png`](MULTI_TURN_LINEAGE.png)
13. Agent harness and bounded repair evidence:
   [`AGENT_HARNESS_REPAIR_EVIDENCE.json`](AGENT_HARNESS_REPAIR_EVIDENCE.json)
   with [`AGENT_HARNESS_REPAIR_PROOF.zip`](AGENT_HARNESS_REPAIR_PROOF.zip)
14. Live product:
   `https://radeon-voice-skill-foundry.pages.dev/`
15. Submission evidence map:
   [`SUBMISSION_EVIDENCE_MAP.md`](SUBMISSION_EVIDENCE_MAP.md)
16. Project Specification: [`PROJECT_SPECIFICATION.pdf`](PROJECT_SPECIFICATION.pdf)
17. Technical evidence: [`TECHNICAL_EVIDENCE_INDEX.md`](TECHNICAL_EVIDENCE_INDEX.md)
18. Architecture: [`ARCHITECTURE.png`](ARCHITECTURE.png)
19. Judge result card: [`JUDGE_RESULT_CARD.png`](JUDGE_RESULT_CARD.png)
20. Poster: [`POSTER.pdf`](POSTER.pdf)
21. Multi-turn evidence:
   [`MULTI_TURN_REFINEMENT.png`](MULTI_TURN_REFINEMENT.png) and
   [`MULTI_TURN_REFINEMENT.json`](MULTI_TURN_REFINEMENT.json), with
   [`MULTI_TURN_REFINEMENT_PROOF.zip`](MULTI_TURN_REFINEMENT_PROOF.zip)
22. Performance Demo:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/RADEON_VOICE_SKILL_FOUNDRY_PERFORMANCE_DEMO.mp4`
23. Continuous Operation Demo:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/CONTINUOUS_OPERATION_DEMO.mp4`
24. Package integrity: [`SHA256SUMS.txt`](SHA256SUMS.txt)
25. Source:
   `https://github.com/Chengyuann/radeon-voice-skill-foundry`
26. Cross-modal policy induction:
   [`CROSS_MODAL_POLICY_INDUCTION.png`](CROSS_MODAL_POLICY_INDUCTION.png)

Demo captions:
`https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/RADEON_VOICE_SKILL_FOUNDRY_DEMO.srt`

Verified workflow proof package:
`https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/VERIFIED_WORKFLOW_PROOF.zip`

Demo governance ledger:
`https://github.com/Chengyuann/radeon-voice-skill-foundry/releases/download/submission/GOVERNANCE_LEDGER.jsonl`

Official submission:
`https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/pull/7`

## One-command Verification

```bash
npm ci
npm run verify:submission
```

This regenerates the agent-harness repair evidence, runs the 68-test suite and
the independent Supervisor-watchdog fault simulation, typechecks, builds the
production frontend, verifies `SHA256SUMS.txt`, and checks that the Project
Specification PDF contains the current P0 proof text.

Current live Radeon recovery evidence:
[`LIVE_RADEON_RECOVERY_EVIDENCE.json`](LIVE_RADEON_RECOVERY_EVIDENCE.json).
The August 2 evidence includes a controlled Supervisord shutdown: a detached
watchdog restored all six services and stable public Radeon health without
operator intervention.

The August 3 gateway upgrade adds Radeon Cloud `rc-tunnel` as primary and keeps
Cloudflare Quick Tunnel as fallback. Both one-tunnel-down cases were tested;
the stable Pages health URL stayed HTTP 200, and a stopped rc-tunnel was
re-exposed under a new domain and re-registered automatically.

The new unedited live capture runs one continuous public sequence:
`health -> ASR -> compile -> verify -> proof hash`. It lasts 48.96 seconds,
passes 7/7 fixtures, and ends at proof hash
`4181034f7cbc354d78df1ab6e248b720f9818e264b9d9bd1f589c2337b3f5510`.
The public-health history covers 187.6 minutes with 39/39 healthy samples and
zero observed failures.
Independent GitHub scheduling subsequently produced 29/29 successful W7900
health runs across 50.75 observed hours. GitHub scheduling is best-effort; the
exact run timestamps are preserved in
[`GITHUB_SCHEDULED_HEALTH_SUMMARY.json`](GITHUB_SCHEDULED_HEALTH_SUMMARY.json).

## Traceable Multi-Turn Interaction

A correction creates a new child compile instead of changing the parent in
place. The child records `parentRunId`, receives regenerated constraints,
permissions and fixtures, and must pass verification again.

The submitted public workflow demonstrates:

- **Cross-Modal Policy Induction with Audio-Native Verification:** speech
  supplies hidden rationale and prohibitions, demonstrated actions supply real
  tools and state transitions, and local policy retrieval supplies authority.
  The promoted result is a source-bound, least-privilege Agent Skill with
  proof and versioned memory.

- user correction: require confirmation before creating calendar holds
- parent run: `run_dbc1a6e2c6b5`
- verified child run: `run_79b986c46400`
- revision: `1 -> 2`
- generated fixtures: `7`
- local knowledge matches: `3`
- child proof hash: `422bc40e...ead6522`

See [`MULTI_TURN_INTERACTION.md`](MULTI_TURN_INTERACTION.md) for the compact
lineage and evidence links.

## Governed Agent Harness

Every new proof binds a server-authoritative `harness.json` and an independent
`verifier.json`. The harness records tools, context lineage, memory policy,
sandbox authority, and execution budgets. The verifier records completion
criteria, server-side isolation, repairable policy categories, manual-only
categories, and a two-attempt repair budget.

`AGENT_HARNESS_REPAIR_EVIDENCE.json` shows the verifier enforcing the final
permission contract. The verified child keeps `mail:send = deny`, preserves
all parent guardrails, and records the repair lineage in the proof ZIP.

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
- Fixed-workload vLLM graph GPU package energy: 4,939.16 J versus
  23,255.72 J for Transformers, a 78.76% reduction
- GPU package output-token efficiency: 0.6195 tok/J, 4.79x Transformers
- Native ASR batch-eight: 85.35x aggregate real-time
- Compact output: 29.42% fewer output tokens and 30.03% lower generation
  latency

Exact reuse of an identical promoted skill measured 2.18 ms versus 24.09 s for
the recorded full compile path. This is an application fast path that avoids a
repeat model call; it is not presented as GPU inference acceleration for a new
or changed task.

The precision admission study measured a 44.07% model-load VRAM reduction and
88.43% larger KV-cache capacity for Quark INT8, then selected the FP16 route
for production because it preserved policy semantics in the verification gate.

## Deployment and Privacy Boundary

Core ASR and Agent inference run on the participant-controlled Radeon Cloud
instance. Cloudflare Pages serves the public UI and forwards authenticated API
requests to that instance. Raw audio is not included in proof downloads.

The public deployment includes a synthetic SOP fixture so no real confidential
material is needed when using the hosted application. The same source can also
run on a private network without the public gateway.

## Evidence Boundaries

- The 4:49 Product Demo is the authoritative primary contest video.
- The Product Demo ends with a terminology card clarifying the exact Agent Skill
  Markdown, proof-hash, and ledger integrity boundaries.
- The Performance Demo's spoken `35/35` count belongs to its pinned recording
  revision; the submission regression suite is `68/68`.
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
- Test counts belong to pinned revisions. The current submission regression
  suite passes 68/68; Radeon benchmark snapshots retain their recorded counts.
- The synthetic Chinese SOP WAV is a reproducible fixture, not a claimed human
  recording.
