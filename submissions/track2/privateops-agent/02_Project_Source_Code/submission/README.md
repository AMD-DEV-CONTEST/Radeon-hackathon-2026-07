# PrivateOps Agent - Submission Package

PrivateOps is a permission-first private computer AI for Track 2 of the 2026 AMD AI DevMaster Hackathon.

> Useful AI needs permission. PrivateOps can observe broad supported areas of the computer and project, but observation is not silent control. Read-only checks run safely; supported side effects require a second exact-action confirmation; unsafe exfiltration is blocked.

**Broad visibility. Deliberate action. Evidence for every decision.**

## Review order

1. `PrivateOps-Agent-Project-Specification.pdf` — scenario, permission model, architecture, all five capabilities, deployment, and measured optimization evidence.
2. `PrivateOps-Agent-Competition-Deck.pptx` — editable 10-slide English review deck.
3. `PrivateOps-Agent-Poster.pdf` — one-page permission-first value overview.
4. `assets/architecture.svg` or `assets/architecture.png` — permission and inference boundaries.
5. `example-prompts.md`, `demo-script.md`, and `video-shot-list.md` — official Radeon Cloud flow, prompts, and visual acceptance checks.
6. `radeon-cloud-runbook.md` — exact same-instance Radeon + ROCm reproduction steps.
7. `evidence/README.md`, `evidence/rocm-verified/`, and `evidence/rocm-retest-20260804/` — immutable primary proof plus an independent reproduction.
8. `benchmark-evidence.json` and `benchmark-evidence.csv` — authoritative copies generated from the immutable verified run.
9. `performance-and-stability-report.md` — measured facts, implemented optimizations, software stability scope, and explicit non-claims.
10. `pr-submission.md` — final English pull-request copy and title rule.
11. `final-checklist.md` — completed engineering gates and the remaining account-bound Fork/PR gates.

## Verified Radeon proof

- GPU: AMD Radeon Graphics (`gfx1100`), about 48 GiB reported VRAM
- ROCm: 7.2.1
- Model: `Qwen/Qwen2.5-7B-Instruct`
- Server: ROCm vLLM on `127.0.0.1:8000`
- Direct latency: 1,511.072 ms
- Completion throughput: 32.427 tokens/s
- Complete Chinese Agent task: 18,384.639 ms

The original verified instance was destroyed after capture. A 2026-08-04 reproduction instance independently confirmed the same runtime boundary and produced a separate 1,513.115 ms / 32.384 tokens/s machine record. The final demonstration video is publicly available at <https://www.bilibili.com/video/BV1nQuA6qEFS/>.

## Source verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts\stability_check.py
.\.venv\Scripts\python.exe scripts\sync_verified_evidence.py
.\.venv\Scripts\python.exe scripts\verify_submission.py
```

## Mode policy

Only `rocm-local` with a loopback endpoint is competition-eligible. AMD shared HTTPS API output is clearly labeled `development` / `amd-cloud-api`; it can help local product testing but is never counted as core inference or Radeon evidence. No synthetic GPU result is included.
