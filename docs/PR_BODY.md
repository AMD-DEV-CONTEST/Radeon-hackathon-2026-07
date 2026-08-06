## Local Incident Commander

Track 2 submission: a private, evidence-first SRE incident investigation agent for local deployment on AMD Radeon and ROCm.

### What this submission includes

- Bounded four-step Agent workflow: deployment inspection, metrics inspection, sanitized log search, and cited synthesis.
- Native OpenAI-compatible tool calling through the Hermes parser used by the Radeon vLLM launch configuration.
- Persistent investigation sessions, append-only evidence ledger, immutable simulation-only decisions, cited follow-up memory, and deterministic fallback.
- Complete Python source, tests, specification, security notes, architecture source, poster, and English-subtitled demo video.

### Links

- Source: https://github.com/8dgeRunner/Radeon-hackathon-2026-07/tree/codex/track2-local-incident-commander-submit
- README: https://github.com/8dgeRunner/Radeon-hackathon-2026-07/blob/codex/track2-local-incident-commander-submit/README.md
- Specification: https://github.com/8dgeRunner/Radeon-hackathon-2026-07/blob/codex/track2-local-incident-commander-submit/docs/SPECIFICATION.md
- Demo video (public MP4): https://raw.githubusercontent.com/8dgeRunner/Radeon-hackathon-2026-07/codex/track2-local-incident-commander-submit/demo/Local-Incident-Commander-demo.mp4
- Demo video (GitHub file page): https://github.com/8dgeRunner/Radeon-hackathon-2026-07/blob/codex/track2-local-incident-commander-submit/demo/Local-Incident-Commander-demo.mp4
- Poster: https://github.com/8dgeRunner/Radeon-hackathon-2026-07/blob/codex/track2-local-incident-commander-submit/poster/poster.png
- Radeon benchmark evidence: https://github.com/8dgeRunner/Radeon-hackathon-2026-07/tree/codex/track2-local-incident-commander-submit/benchmarks
- Architecture: https://github.com/8dgeRunner/Radeon-hackathon-2026-07/blob/codex/track2-local-incident-commander-submit/docs/architecture.svg

### Verification

- Automated suite: 43/43 tests passed.
- `compileall` and `git diff --check` passed.
- Demo: 1600x900 H.264/AAC, 3:55.92, with burned-in English subtitles.
- Live Radeon session captured on 2026-08-06: ROCm 7.2.1, Qwen3-8B-AWQ served by local vLLM, Radeon PRO W7900 (`gfx1100`, 49136 MB VRAM), `/api/health` mode `local-radeon`, and zero remote core requests.
- The live session includes the four-step plan, all three read-only tools, server-owned evidence citations, human approval and rejection of simulation-only actions, final RCA, and cited follow-up memory. The later deterministic fallback segment is explicitly labelled as degraded recovery.

### Safety boundary

The Agent is read-only for incident data. Proposed remediation is simulation-only and requires an immutable operator decision; no remediation command executor is included.
