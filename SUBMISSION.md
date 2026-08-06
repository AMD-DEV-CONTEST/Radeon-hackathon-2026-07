# Hackathon Submission — 3DGenerateFlow

> Track 1: Multimodal AI Content Creation Tool Development  
> Platform: AMD Radeon GPU + ROCm

---

## 1. Project Repository

- **Main repo**: `https://github.com/SuppartWang/3DGenerateFlow`
- **Hackathon fork / PR target**: `https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07`
- **Your fork for the PR**: `https://github.com/SuppartWang/Radeon-hackathon-selfuse`

---

## 2. Deliverables Checklist

| # | Item | File / Location | Status |
|---|---|---|---|
| 1 | Source code | `SuppartWang/3DGenerateFlow` repo | ✅ Ready |
| 2 | English README | `README.md` (this repo) | ✅ Ready |
| 3 | Project introduction (PDF) | `docs/PROJECT_INTRO_EN.pdf` | ✅ Ready |
| 4 | Poster / PPT (PDF) | `docs/POSTER_EN.pdf` | ✅ Ready |
| 5 | Demo video (3–5 min) | Upload to your video host; link in PR description | ⬜ You record & upload |
| 6 | Demo script | `docs/DEMO_SCRIPT.md` | ✅ Ready |
| 7 | Video production guide | `docs/VIDEO_PRODUCTION.md` | ✅ Ready |
| 8 | PR description template | `docs/PR_DESCRIPTION.md` | ✅ Ready |

---

## 3. How to Submit via Pull Request

### Step A — Fork the official repo

Open `https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07` in your browser and click **Fork**.

If you already have `SuppartWang/Radeon-hackathon-selfuse`, use that one.

### Step B — Push this project into your fork

Run these commands on your local machine (replace `SuppartWang` with your GitHub username if different):

```bash
# 1. Go to the project root
cd /Volumes/ORICO/Users/suppartwang/Coding/3DGenerateFlow

# 2. Add your hackathon fork as a remote
git remote add hackathon https://github.com/SuppartWang/Radeon-hackathon-selfuse.git

# 3. Push the current main branch to your fork
git push hackathon main --force
```

### Step C — Open the Pull Request

1. Open `https://github.com/SuppartWang/Radeon-hackathon-selfuse/pulls`
2. Click **New pull request**
3. Set:
   - **base repository**: `AMD-DEV-CONTEST/Radeon-hackathon-2026-07`
   - **base branch**: `main`
   - **head repository**: `SuppartWang/Radeon-hackathon-selfuse`
   - **compare branch**: `main`
4. Paste the content of `docs/PR_DESCRIPTION.md` into the PR body.
5. Add the demo video link in the PR body (see Step D).
6. Attach the two PDFs:
   - `docs/PROJECT_INTRO_EN.pdf`
   - `docs/POSTER_EN.pdf`
7. Submit the PR.

### Step D — Upload the demo video

Record a 3–5 minute screen capture showing:

1. Open the Web UI landing page and confirm the **AMD ROCm Ready** badge.
2. Upload a photo and type a prompt (e.g., `realistic 3D full-body bride` or `2.5D relief coin, skateboard dog`).
3. Click **Plan Style** and then **Generate Model**.
4. Show the Director Console storyboard and task log updating.
5. Wait for completion and show the Result page (3D preview + print report).
6. Download `model.glb` or `relief.stl`.

Upload the video to:

- YouTube (unlisted or public)
- Bilibili
- Google Drive / 百度网盘 (make sure the link is public)

Copy the public URL and paste it into the PR description.

---

## 4. Quick Check Before Submitting

- [ ] `docs/PROJECT_INTRO_EN.pdf` exists and opens correctly.
- [ ] `docs/POSTER_EN.pdf` exists and opens correctly.
- [ ] `README.md` is in English.
- [ ] `git status` shows all intended files committed.
- [ ] Demo video is recorded and uploaded.
- [ ] PR is opened against `AMD-DEV-CONTEST/Radeon-hackathon-2026-07`.

---

## 5. Useful Links

- Your main repo: https://github.com/SuppartWang/3DGenerateFlow
- Your hackathon fork: https://github.com/SuppartWang/Radeon-hackathon-selfuse
- Official hackathon repo: https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07
- PR page: https://github.com/SuppartWang/Radeon-hackathon-selfuse/pulls
