# ProofLaunch Agent Architecture

## Decision

ProofLaunch is an L2 deterministic workflow with a bounded
evaluator–optimizer loop. It does not use a free-running multi-agent swarm.
The path is knowable, release mistakes are costly, and every autonomous repair
must therefore earn its place through a mechanical audit.

## One-page system

```text
Multimodal Mission (image / PDF / audio / video / text)
    |
    v
Signature + rights intake ------- hashes, MIME, dedupe
    |
    v
Qwen3-VL / Whisper / PDF -------- source IDs + bbox/frame/time/page locators
    |
    +--> GroundingDINO ---------- open-set product box
             |
             +--> SAM2 ---------- frame-by-frame product mask
    |
    v
SourceBoundEvidenceMiner ---- exact source spans + Claim IDs
    |
    v
DeterministicCreativeDirector ---- approved claims only
    |
    +--> GemmaAudiencePulse (local Radeon adapter, advisory)
    |
    v
IdentityLockedStudio
    |        \
    |         \-- DiffusersBackgroundProvider (local ROCm key inference)
    |              or clearly-labelled procedural fallback
    v
FourGateReleaseAuditor
  [claim | product identity | typography | platform safe zone]
    |
    +--> SigLIP2SemanticScorer (local Radeon fifth gate)
    |
    +--> LTX-Video 2B -------- image-conditioned short video
    |       \-- exact product overlay before encode
    |       \-- decoded H.264 identity tolerance after encode
    |       \-- CLAP semantics + timestamped A/V alignment
    |
    +--> CrossMediaReleaseGate
    | fail, max 2
    v
DeterministicRepairer -------- rebuilds around immutable product
    |
    +--------> auditor
    |
    v pass
VerifiedCampaignExporter ---- hashes + manifest + ZIP
    |
    v
Human review before publish
```

## Seven required boundaries

- Entry point: typed CLI or Radeon Gate Notebook.
- Model calls: Qwen3-VL understanding, optional Whisper ASR, GroundingDINO
  localization, Gemma emotion, Diffusers background, SigLIP2 semantic, LTX
  video, SAM2 tracking, and CLAP audio-text
  adapters are explicit; none owns workflow state. The Radeon router loads
  them sequentially and unloads each before the next large phase.
- Tools: local filesystem and caller-owned local pipelines only in the
  competition path.
- State: checkpoint JSON, final state JSON, and append-only hash ledger.
- Task graph: graph hash is immutable; killed runs resume only from successful
  steps and cannot silently adopt a changed plan.
- Permissions: publishing, sending, destructive work, and connectors are
  outside the release path and require a code-enforced human approval.
- Termination: pass mechanical, semantic, cross-media, encoded-identity, and
  A/V alignment gates; exhaust two repairs; or fail closed.
- Trace points: every stage transition, audit count, repair round, export, and
  adapter failure is ledgered.

## Three trust-losing failure modes

1. A numerical or product claim appears without an exact supplied source span.
2. A generative model redraws or obscures the supplied product.
3. The tool exports content that is unreadable or hidden behind platform UI.
4. A cross-media claim loses its page, timestamp, frame, or bounding-box source.

Those failures are caught by separate gates so a good average cannot hide
one catastrophic release.
