# Submission Checklist

## Identity and Access

- [x] Project name: Radeon Voice Skill Foundry
- [x] Track: Development and Local Deployment of Private AI Agents
- [x] Participant: Chengyuann
- [x] Team: N/A (solo)
- [x] License: MIT
- [x] Public product URL is documented
- [x] Source repository and official submission URL are documented
- [x] Submission evidence map covers all six Track 2 requirements
- [x] GitHub Actions runs typecheck, tests, and production build

## Product Evidence

- [x] Product Demo records the public Cloudflare-to-W7900 workflow
- [x] Performance Demo preserves the real W7900 model wait
- [x] Continuous Operation Demo is labeled as deterministic lifecycle evidence
- [x] English SRT captions are included for every video
- [x] Verified workflow proof ZIP and governance ledger are included
- [x] Performance and continuous-operation proof ZIPs are included
- [x] Multi-turn interaction has a dedicated brief and lineage diagram
- [x] Live multi-turn screenshot, API lineage JSON, and proof ZIP are included

## Radeon and ROCm

- [x] Radeon Pro W7900-class `gfx1100`
- [x] ROCm 7.2.1
- [x] Qwen3-ASR-0.6B FP16
- [x] Qwen3-4B-Instruct-2507 FP16
- [x] Same-hardware serving and ASR batching measurements are documented
- [x] Compact-output and exact-reuse measurements are bounded correctly
- [x] Quark INT8 rejection and FP16 production decision are documented

## Verification and Governance

- [x] Six server-authoritative workflow actions
- [x] Sandbox Replay with five fail-closed probes
- [x] Audio-backed proof passes 7/7 fixtures
- [x] `mail.send = deny`
- [x] Promotion requires a proof-bound impact review
- [x] Governance ledger verifies sequence, payload, and previous-entry hashes
- [x] Exact reuse applies only to an identical promoted skill
- [x] Runtime drift requires child-run revalidation

## Quality and Integrity

- [x] Submission regression suite passes 63/63
- [x] Typecheck and production build pass
- [x] Synthetic SOP audio is disclosed as a reproducible fixture
- [x] Voice Evidence is described as an internal deterministic gate
- [x] Ledger hashes are not described as external signatures or anchoring
- [x] AI-assisted narration and image assets are disclosed
- [x] Canonical filenames contain no release-generation suffixes
- [x] `SHA256SUMS.txt` covers every finalized artifact except itself
