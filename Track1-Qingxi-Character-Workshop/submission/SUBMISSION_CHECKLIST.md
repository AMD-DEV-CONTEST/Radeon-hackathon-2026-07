# Submission Checklist — Track 1 (Multimodal AI)

Official rules: https://luma.com/amd-4dhi
Repo to fork: https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07
Deadline: **2026-08-06 11:59 PM Beijing time (UTC+8)**

---

## 0. Eligibility (prize requires all)

- [ ] Registered on Luma (AMD AI DevMaster Hackathon)
- [ ] Member of AMD Developer Program (China: developer.amd.com.cn)
- [ ] (If China-based) joined the WeChat group; PR/materials in English

## 1. Project Profile Document (PDF)  — required

Source: `submission/PROJECT_PROFILE.md`
- [ ] Export to **PDF**, English
- [ ] Sections present: Background / Users & Scenarios / Architecture /
      Models & Algorithms / AMD Radeon + ROCm adaptation / Innovation

## 2. Project Source Code  — required

Repo: `Marsbler/qingxi-character-workshop` branch `feature/character-workshop`
- [ ] Code complete on the branch (push latest)
- [ ] README.md covers env config, startup guide, dependency list
- [ ] No secrets in repo (tokens, keys)
- [ ] Reproduce run works: `bash scripts/setup_env.sh && python3 app.py`

## 3. Demo Video  — required, 3–5 min

Follow `docs/DEMO_VIDEO_SCRIPT.md` (English)
- [ ] 3–5 min, 1080p MP4
- [ ] Shows real AMD Radeon run: `rocm-smi` + UI generate (clarity/stability/diversity)
- [ ] No third-party IP in inputs/outputs
- [ ] Backup card images ready in `outputs/`

## 4. Supplementary Material  — choose one

- [ ] **PPT** or **Poster** built from `submission/POSTER_PPT_CONTENT.md`
      (English, export PDF for the PR if you like)

## 5. Open the Pull Request  — required

1. Fork https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07
2. Add your materials to the fork (place under a folder named by your app,
   e.g. `qingxi-character-workshop/`):
   - `PROJECT_PROFILE.pdf`
   - source code (or link to the public repo + copy of code)
   - `README.md`
   - demo video (or public link + local file)
   - PPT/poster PDF
3. PR title format (exactly): `Track 1, <TeamName>, Qingxi Character Workshop`
4. Fill PR description with a short overview + links
5. Double check: PR body and all submitted docs are **in English**

---

## Team / identity placeholders to fill

- Team name: ____________ (used in PR title)
- Contact email (registered): ____________
- Repo public URL: https://github.com/Marsbler/qingxi-character-workshop
