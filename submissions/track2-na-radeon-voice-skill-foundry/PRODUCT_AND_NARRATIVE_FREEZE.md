# Product and Narrative Freeze

Freeze date: 2026-07-20 (UTC+8)

Production gate status: passed on commit `8950009`.

## Purpose

This freeze establishes the final contest product and the only canonical Demo
V3 story. Recording begins only after the frozen production path passes the
release checks below.

## Frozen Product

Radeon Voice Skill Foundry converts a private spoken SOP plus a real,
server-authoritative action demonstration into a reusable governed Agent Skill.
It is not a generic transcription tool, a voice chatbot, or a static policy
generator.

The frozen product path is:

```text
Voice SOP
-> server-authoritative six-step demonstration
-> W7900 Qwen3-ASR and Qwen3 skill compilation
-> typed constraints, policy, and permissions
-> Sandbox Replay v1
-> Promotion Impact Review
-> proof-bound promotion
-> Governance Audit Ledger
-> exact governed reuse
```

## Frozen Claims

- Core ASR and skill compilation run on the AMD Radeon Pro W7900-class
  `gfx1100` allocation with ROCm 7.2.1.
- The six action events are accepted and persisted by the server before the UI
  advances.
- The generated skill includes least-privilege permissions, positive fixtures,
  adversarial fixtures, receipts, and a hash-bound proof bundle.
- `mail.send` remains denied; drafts and tentative calendar holds do not become
  irreversible external side effects.
- Promotion is gated by compatibility and impact review.
- Governance events form a previous-hash chain with payload and entry hashes,
  receipt reconciliation, deletion/tamper detection, and JSONL export.
- Exact reuse applies only to an identical promoted skill and records reuse
  evidence; changed intent follows compilation and verification again.
- Cloudflare Pages is the stable public entry. A dual-token registrar validates
  the candidate through the tunnel, signs a fresh Radeon health proof, and
  recovers the rotating Quick Tunnel origin in KV without redeployment.

No metric, model, GPU, ROCm, performance, or reliability claim may be added
unless it is already backed by repository evidence.

## Allowed Changes After Freeze

- P0 functional bugs.
- Security, authorization, integrity, or privacy defects.
- Broken production links or deployment recovery failures.
- Caption timing, subtitle, pronunciation, or factual copy corrections.
- Packaging fixes that do not change product behavior.

## Disallowed Changes After Freeze

- New product features or modules.
- Layout redesigns or new visual systems.
- Workflow, policy, fixture, metric, or benchmark changes.
- New performance claims or model substitutions.
- Demo-only behavior that does not exist in the production path.

Any allowed change must record the reason, affected evidence, verification
commands, and whether Demo V3 must be re-recorded.

## Release Checks

- Full Vitest suite, TypeScript check, and production build pass.
- Public `/api/health` reports Radeon mode, the frozen model, W7900-class GPU,
  and ROCm 7.2.1.
- Governance ledger endpoint reports `valid`; JSONL export succeeds.
- Direct unauthenticated W7900 origin access remains rejected.
- Restarting only `rvsf-tunnel` produces a new origin and the stable Pages URL
  recovers without deployment.
- Desktop and 390px mobile checks show no blocking overlap or clipped controls.

The controlled infrastructure check restarted only `rvsf-tunnel`. The Quick
Tunnel origin changed, the W7900 registrar and remote KV converged to the new
origin, the stable Pages health and Governance Ledger endpoints recovered, and
the Pages deployment remained `fd2aa5ad` on source commit `8950009`.

## Demo V3 Contract

- Use a male TTS voice.
- Burn captions into the video and include an embedded subtitle track.
- Record the final public product, not a local mock.
- Preserve real model waiting time; do not imply cached output is fresh
  inference.
- Show the complete frozen path once, continuously, with the Governance Audit
  Ledger and exact reuse as the closing proof.

## Demo V3 Completion

Recorded and validated on 2026-07-20 after the frozen release gate passed.

- Duration: `278.56 s`
- Resolution: `1920x1080`
- Video: H.264
- Audio: AAC, male `Charon` narration
- Captions: burned in plus embedded English subtitle track
- Product path: public Cloudflare Pages to W7900 Qwen3-ASR and Qwen3
- Verification: `7/7`
- Final lifecycle: promoted
- Exact reuse count shown: `1`
- Governance ledger: `valid`, two entries after recording
- MP4 SHA-256:
  `85d989a952561650195322c080a46543b93b3070c84e0f89021e59d451a4148e`
- SRT SHA-256:
  `a0406750ee3c3081597d8ede9ff8eccc853958dda76e54a024d98a87cf21c1ce`
- Proof ZIP SHA-256:
  `7898d888112b113d53fce7ca2f9f46eecdaf318c79625af665fa908622f78cc2`
- Ledger JSONL SHA-256:
  `ca04585f5531fc42333f219153b7e3cbabfd3c629917cb4c621e6066ab95fcb3`
