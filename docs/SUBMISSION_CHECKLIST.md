# Submission Checklist — Track 2 · PrivateLocalAgent

Team: **说干就干**  
GitHub: **Wyf66669**  
Project: **PrivateLocalAgent**  
Deadline: **2026-08-06 23:59 (UTC+8)**

## PR title (to official repo)

```text
Track 2, 说干就干, PrivateLocalAgent
```

Fork: https://github.com/Wyf66669/Radeon-hackathon-2026-07  
Branch with code: `track2-private-local-agent`  
Upstream: https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07  
Official PR: https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/pull/40  
PR draft text: `docs/PR_BODY.md`

## Required materials (Track 2)

| Item | Status | Path / note |
|------|--------|-------------|
| Project specification | Done | `docs/PROJECT_SPECIFICATION.md` |
| Architecture | Done | `docs/ARCHITECTURE.md` |
| AMD/ROCm optimization notes | Done | `docs/AMD_ROCM_OPTIMIZATION.md` |
| Source code + README | Done | `src/`, `app.py`, `README.md` |
| Run / reproduce guide | Done | `README.md`, `docs/RADEON_CLOUD_RUN.md` |
| Poster outline | Done | `docs/POSTER_OUTLINE.md` |
| Notebook visual demo (rc-tunnel) | Done | `notebooks/visual_no_tunnel.ipynb` |
| Multi-agent + workflows + six apps | Done | `src/agent/multi_agent.py`, `docs/SIX_APPS.md`, `scripts/demo_six_apps.py` |
| Development skills (real files) | Done | `src/skills/`, `scripts/run_skill.py` |
| Privacy guard + audit | Done | `src/privacy/` |
| ROCm bench | Done | `scripts/bench_rocm.py` |
| 10k FAQ generator | Done | `scripts/generate_kb_faqs.py`, `docs/KB_10K.md` |
| Demo video (3–5 min) | Done | https://github.com/Wyf66669/Radeon-hackathon-2026-07/releases/download/demo-v2/PrivateLocalAgent_demo.mp4 |
| Open PR to official repo | Done | https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/pull/40 |

## Verified on Radeon Cloud (2026-07)

- [x] Instance: AMD OneClick Base (ROCm)
- [x] Local Transformers backend on GPU
- [x] CLI demo (`scripts/demo_cli.py`)
- [x] Notebook one-cell visual chat (no tunnel)
- [x] Mandatory `kb_search` + Chinese grounded answers
- [x] Demo video uploaded + linked in PR
- [x] PR opened to `AMD-DEV-CONTEST/Radeon-hackathon-2026-07` (#40)

## Final submit steps

1. ~~Open PR~~ Done (#40, title correct)
2. ~~Demo video~~ Done (Release `demo-v2`)
3. Optional later: replace walkthrough MP4 with live Radeon Cloud screen recording if judges prefer raw footage
4. Destroy cloud instance when idle to save credit

## Certificates (AMD official)

Valid submitted teams may receive a **Certificate of Completion**.  
Final review may also award Gold / Silver / Bronze / **Excellent** certificates.

## Pre-maintenance backup (2026-07-31 18:00 UTC+8)

| Action | Command / place |
|--------|-----------------|
| NFS persistence | `/workspace/persistence` |
| One-shot backup | `python scripts/backup_to_persistence.py` |
| Push code | `git push origin track2-private-local-agent` |
| Demo video copy | Release `demo-v2` on the fork |

## Contact

Contest email: ai_dev_contests@amd.com
