# Radeon Cloud Step-by-Step Checklist (Command Level)

For: **Qingxi Rift Character Workshop** - Task 13 real inference
Official cloud: https://radeon-global.anruicloud.com/
Official guide: https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/tree/main/Radeon-Cloud-User%20Guide

Local code worktree:

```text
D:\APP\...\.worktrees\character-workshop\character-workshop
```

**Remote repo (already pushed; use this for cloning on the cloud):**

| Item | Value |
|----|-----|
| GitHub | https://github.com/Marsbler/qingxi-character-workshop |
| Clone URL | `https://github.com/Marsbler/qingxi-character-workshop.git` |
| Dev branch | `feature/character-workshop` (contains the full `character-workshop/` app) |
| Default branch | `main` (early doc commits; **on the cloud please check out the feature branch**) |

---

## Re-start / First time on cloud: follow ONLY this document

If the environment is messed up, you Destroy and relaunch, or you configure it for the first time, **do NOT piece steps together from the scattered sections below**.

-> Open and follow strictly in order:

**[`character-workshop/docs/RADEON_CLOUD_CLEAN_START.md`](../../.worktrees/character-workshop/character-workshop/docs/RADEON_CLOUD_CLEAN_START.md)**

Path in the repo (after cloning):

```text
qingxi-character-workshop/character-workshop/docs/RADEON_CLOUD_CLEAN_START.md
```

**Core anti-pitfall order (memorize):**

```text
ROCm image Launch
  -> rocm-smi shows GPU
  -> torch in python is already ROCm and available=True   (else install ONLY ROCm torch)
  -> git clone + checkout feature/character-workshop
  -> bash scripts/install_app_deps.sh              (never `pip install -r` indiscriminately first)
  -> detect_device passes
  -> download_models -> generate card -> app.py
```

**Absolutely forbidden:** run `pip install -r requirements.txt` / `pip install torch` before confirming ROCm torch (the default index becomes `+cu*`).

Stages A-K below are per-item references; **when in conflict with "Clean Start From Zero", the from-zero document wins.**

---

## Stage A - Browser: create an instance (no shell commands)

### A1. Login and permissions

1. Open https://radeon-global.anruicloud.com/ -> **Login with Email**
2. Confirm you joined the AMD Developer Program (China: https://developer.amd.com.cn/)
3. Confirm the Luma hackathon is registered and cloud quota is available

### A2. Add a Template

1. Top-right avatar -> **Profile**
2. **My Templates** -> **Add Template**
3. Recommended:
   - **Title:** `qingxi-workshop`
   - **Container Image:** pick an image with **PyTorch + ROCm** (names per the platform list)
   - **Storage:** **Persistent (PVC)** <- must enable, or models are lost when the instance is destroyed
   - Optional: turn on **SSH Access** (handy for local VS Code / scp)
4. Click **Add Template** to save

### A3. Launch

1. In the Templates list, click **Launch**
2. Wait for **Your workspace is ready (100%)**
3. Click **Open Notebook** -> enter JupyterLab

From then on, commands run in **JupyterLab -> Terminal**.

---

## Stage B - First login: system and GPU self-check

```bash
# identity and system
whoami
uname -a
pwd
df -h
nvidia-smi 2>/dev/null || true
rocm-smi 2>/dev/null || true

# Python / Torch
python3 --version
python3 - <<'PY'
import torch
print("torch", torch.__version__)
print("cuda_available", torch.cuda.is_available())
print("hip", getattr(torch.version, "hip", None))
if torch.cuda.is_available():
    print("device", torch.cuda.get_device_name(0))
    print("vram_gb", round(torch.cuda.get_device_properties(0).total_memory/1024**3, 2))
PY
```

**Pass criteria:**

- `cuda_available True`
- `hip` not empty **or** the version string contains `rocm` (ROCm stack)
- prints the GPU name and VRAM

On failure: switch to a ROCm PyTorch image, or reinstall torch per the image docs; **do not** install the CUDA version of torch first.

---

## Stage C - Get the project onto the cloud

**Recommended order: push to Gitee/GitHub locally -> `git clone` on the cloud.**
If you have no remote, use C2 package upload or C3 scp.

### Method C0 - local: commit and push to the remote (do this before going to the cloud)

Local development happens on the worktree branch `feature/character-workshop`:

```text
D:\APP\...\.worktrees\character-workshop
```

#### C0.1 Confirm the status and commit unsaved changes

```powershell
cd "D:\APP\...\.worktrees\character-workshop"

git status -sb
git branch --show-current
# should show feature/character-workshop

# if there are uncommitted files:
git add character-workshop
git status
git commit -m "chore: sync workshop code for Radeon Cloud"
```

#### C0.2 Remote repo status (already done for this project)

| Item | Value |
|----|-----|
| Platform | **GitHub** |
| Repo | https://github.com/Marsbler/qingxi-character-workshop |
| HTTPS | `https://github.com/Marsbler/qingxi-character-workshop.git` |
| Branches | `feature/character-workshop` (app code), `main` (base docs) |

If you need to recreate the remote on a **new machine** (when a local repo already exists):

```powershell
cd "D:\APP\...\.worktrees\character-workshop"
git remote remove origin 2>$null
git remote add origin https://github.com/Marsbler/qingxi-character-workshop.git
git remote -v
```

#### C0.3 Push again locally (after changing code)

```powershell
cd "D:\APP\...\.worktrees\character-workshop"

git add -A
git status
git commit -m "feat: describe your change"
# first-time upstream setup (if not set yet):
git push -u origin feature/character-workshop
# afterwards:
git push origin feature/character-workshop
```

Auth: GitHub username + **Personal Access Token** (`repo` scope). **Do not** write the token into any file that would be `git add`-ed.

Verify by opening in the browser:

https://github.com/Marsbler/qingxi-character-workshop/tree/feature/character-workshop/character-workshop

You should see `app.py`, `src/`, `configs/`.

#### C0.4 When the push is rejected because the remote was initialized with a README

```powershell
git pull origin master --allow-unrelated-histories
# or: git pull origin main --allow-unrelated-histories
# after resolving conflicts:
git push -u origin feature/character-workshop
git push -u origin main
```

#### C0.5 After later code changes, sync to the cloud

```powershell
cd "D:\APP\...\.worktrees\character-workshop"
git add -A
git status
git commit -m "feat: describe your change"
git push origin feature/character-workshop
```

If you already have a clone on the cloud, in Jupyter Terminal:

```bash
cd ~/AMDAIHackathon   # your clone dir
git fetch origin
git checkout feature/character-workshop
git pull origin feature/character-workshop
cd character-workshop
```

---

### Method C1 - Cloud: git clone (recommended)

Run in **Radeon Cloud JupyterLab -> Terminal** (public repo, usually no token needed).
Your current working directory is `/workspace`; you can clone right there.

#### C1.0 If you get: `server certificate verification failed. CAfile: none`

The container is missing CA certs. **Fix the certs first, then clone** (try in order):

**Method 1 - install CA (preferred)**

```bash
# Debian/Ubuntu image
sudo apt-get update
sudo apt-get install -y ca-certificates
sudo update-ca-certificates

# then try again
export REPO_URL="https://github.com/Marsbler/qingxi-character-workshop.git"
git clone "$REPO_URL" qingxi-character-workshop
```

**Method 2 - temporarily disable Git SSL verification (current shell only, enough to fetch the code)**

```bash
export GIT_SSL_NO_VERIFY=1
# or: git config --global http.sslVerify false

export REPO_URL="https://github.com/Marsbler/qingxi-character-workshop.git"
cd /workspace
git clone "$REPO_URL" qingxi-character-workshop
```

> Method 2 lowers security; **only use it to fetch public code in a temporary hackathon environment.** To restore after fetching:
> `git config --global --unset http.sslVerify`, or open a new Terminal (without the export it has no effect).

**Method 3 - use ghproxy / a mirror (when direct GitHub SSL still fails)**

```bash
export GIT_SSL_NO_VERIFY=1
git clone https://ghproxy.com/https://github.com/Marsbler/qingxi-character-workshop.git qingxi-character-workshop
# if ghproxy is unavailable, try another GitHub proxy, or use C2 package upload below
```

**Method 4 - still failing: use C2 local tar upload** (no dependence on the cloud's GitHub access).

---

#### C1.1 Normal clone steps

```bash
# your environment example: /workspace
cd /workspace
# or: cd ~

export REPO_URL="https://github.com/Marsbler/qingxi-character-workshop.git"
# if you still have cert issues, keep this:
# export GIT_SSL_NO_VERIFY=1

# first clone
git clone "$REPO_URL" qingxi-character-workshop
cd qingxi-character-workshop

# must check out the dev branch (main may not have the full app code)
git fetch origin
git checkout feature/character-workshop
git pull origin feature/character-workshop

cd character-workshop
pwd
ls -la app.py configs src README.md

# confirm
test -f app.py && echo "PROJECT OK"
```

After you `git push` new commits locally, update on the cloud:

```bash
cd /workspace/qingxi-character-workshop
# if you still have cert issues: export GIT_SSL_NO_VERIFY=1
git checkout feature/character-workshop
git pull origin feature/character-workshop
cd character-workshop
```

If the repo becomes **private**, cloning needs a PAT (**do not write it into files that get committed**):

```bash
export GIT_SSL_NO_VERIFY=1   # only if you still get cert errors
git clone "https://<GitHubUserName>:<PAT>@github.com/Marsbler/qingxi-character-workshop.git" qingxi-character-workshop
```

---

### Method C2 - Local package upload (no remote / git not working)

**Local PowerShell:**

```powershell
cd "D:\APP\...\.worktrees\character-workshop"
# exclude large dirs and caches
tar -czf "$env:TEMP\qingxi-workshop.tgz" `
  --exclude=character-workshop/.venv `
  --exclude=character-workshop/outputs `
  --exclude=character-workshop/models `
  --exclude=character-workshop/.pytest_cache `
  character-workshop
Write-Host "Archive: $env:TEMP\qingxi-workshop.tgz"
```

Upload `qingxi-workshop.tgz` via the **Upload** button on the left of JupyterLab; on the cloud:

```bash
cd ~
mkdir -p work && cd work
# if you uploaded to $HOME:
tar -xzf ~/qingxi-workshop.tgz
# or: tar -xzf /path/to/qingxi-workshop.tgz
cd character-workshop
ls -la app.py
```

### Method C3 - SSH + scp (Template has SSH on)

Paste your local public key in Profile, then Launch; copy from the page:

```bash
ssh <user>@<host> -p <port>
```

Local:

```powershell
scp -P <port> -r "D:\APP\...\.worktrees\character-workshop\character-workshop" <user>@<host>:~/character-workshop
```

---

## Stage D - Python dependencies

> **Complete anti-pitfall steps: see `RADEON_CLOUD_CLEAN_START.md` steps 3-7.**
> Below is a summary; when in conflict, the from-zero document wins.

### The only recommended dependency-install command

```bash
cd /workspace/qingxi-character-workshop/character-workshop

# gate: must have ROCm torch available=True first
python3 -c "import torch; assert torch.cuda.is_available(); print(torch.__version__, torch.version.hip)"

# safe script (preflight + requirements + accelerate --no-deps + postflight)
bash scripts/install_app_deps.sh

export MOCK=0
python3 -c "from src.device import detect_device; d=detect_device(); print(d); assert d.device_type=='cuda'"
```

### Forbidden

```bash
pip install torch                          # default index usually becomes +cu*
pip install -r requirements.txt            # forbidden until torch is ready
pip install accelerate                     # forbidden without --no-deps
```

---

## Stage E - Download models (slow, uses PVC)

```bash
cd ~/work/character-workshop   # change to your path
export MOCK=0

# if Hugging Face network is flaky, set a mirror (if the environment allows)
# export HF_ENDPOINT=https://hf-mirror.com

bash scripts/download_models.sh
```

The script pulls (see `configs/models.yaml`):

- LLM: `Qwen/Qwen2.5-7B-Instruct`
- Image: `cagliostrolab/animagine-xl-3.1`

**If VRAM is tight (~16GB)**, first switch to a smaller LLM by editing `configs/models.yaml`:

```yaml
llm:
  model_id: Qwen/Qwen2.5-3B-Instruct
```

Then download only the LLM:

```bash
python3 - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download("Qwen/Qwen2.5-3B-Instruct")
print("llm ok")
PY
```

Check the cache size:

```bash
du -sh ~/.cache/huggingface 2>/dev/null || du -sh $HOME/.cache/huggingface
```

---

## Stage F - Step-by-step smoke tests (before Web)

Always in the project root, with `export MOCK=0`.

### F1. MOCK regression (confirm the code is not broken)

```bash
export MOCK=1
python3 -m pytest -q
python3 scripts/run_eval_json.py
export MOCK=0
```

### F2. LLM to JSON only

```bash
export MOCK=0
python3 - <<'PY'
from src.llm_role import generate_character
card = generate_character("A green-robed Void traveler carrying a paper lantern", affinity_pref="Void", mock=False)
print(card.name, card.primary_affinity)
print(card.image_prompt[:200])
print("LLM OK")
PY
```

**On failure:** OOM -> switch to 3B; bad JSON -> read the error, check prompts; permissions/download -> rerun download.

### F3. Image only (VRAM heavy)

```bash
export MOCK=0
python3 - <<'PY'
from pathlib import Path
from src.llm_role import generate_character
from src.image_gen import generate_portrait, unload_image_models
card = generate_character("red-haired Matter-affinity warrior", affinity_pref="Matter", mock=False)
out = Path("outputs/_smoke_portrait.png")
out.parent.mkdir(exist_ok=True)
p = generate_portrait(card, out, mock=False)
print("portrait", p, p.stat().st_size)
unload_image_models()
print("IMAGE OK")
PY
```

**OOM:** lower `width/height` in the `image` section of `configs/models.yaml` (e.g. 768x1024) and `steps: 24`, then retry.

### F4. Full card (P0 hard gate)

```bash
export MOCK=0
python3 - <<'PY'
from src.orchestrator import generate_card_job, JobState
r = generate_card_job(
    user_text="A quiet green-robed Void traveler carrying a paper lantern",
    affinity_pref="Void",
    mock=False,
)
print(r.state, r.job_id, r.error)
print(r.card_path, r.portrait_path)
assert r.state == JobState.READY
assert r.card_path and r.card_path.exists()
print("CARD E2E OK")
PY
```

Download/preview: open `outputs/<job_id>/card.png` in the Jupyter file tree.

### F5. Revision path

```bash
export MOCK=0
python3 - <<'PY'
from src.orchestrator import generate_card_job, revise_job, JobState
base = generate_card_job("black-haired Mind-affinity youth", affinity_pref="Mind", mock=False)
assert base.state == JobState.READY
r = revise_job(base.job_id, "change to golden short hair", mock=False)
print(r.state, r.error)
assert r.state == JobState.READY
print("REVISE OK", r.card_path)
PY
```

---

## Stage G - Start the Web UI

```bash
cd ~/work/character-workshop
export MOCK=0
export PORT=7860

# run in the background (optional)
# nohup python3 app.py > /tmp/qingxi-app.log 2>&1 &

python3 app.py
```

### G1. Notebook-only access

Open the proxy URL Jupyter provides, or the port mapping described by the platform.
If only the local port works, confirm in Terminal:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:7860/
```

Expect `200` or `302`.

### G2. Public tunnel (for screen recording / external demo)

```bash
# official rc-tunnel (inside Notebook)
/var/run/secrets/frp-self-service/install
export PATH="$HOME/.local/bin:$PATH"
rc-tunnel version

# the app must already be listening on 127.0.0.1:7860
rc-tunnel expose --port 7860
# note the https://rc-xxxx.radeon.firstdg.ai URL

rc-tunnel status
# to stop:
# rc-tunnel stop
```

**Note:** do not leave the public URL exposed for long; after the demo run `stop` and **Destroy Instance** to save quota.

### G3. UI real-hardware check list

- [ ] Chinese input -> generate character card -> real portrait (not MOCK color-block text)
- [ ] Download/view `card.png`
- [ ] Optional: test one reference image
- [ ] Revision
- [ ] Top-bar device is not mock

---

## Stage H - Commands for demo recording material

```bash
# open another Terminal before screen recording
rocm-smi
# or
python3 - <<'PY'
from src.device import detect_device
print(detect_device())
PY
```

Suggested recording order:

1. `rocm-smi` / device print
2. `export MOCK=0 && python3 app.py`
3. UI generate card (case01)
4. revision or reference image
5. show `outputs/.../card.png`

---

## Stage I - Save quota and persistence

```bash
# before finishing, confirm important outputs are on the PVC path
pwd
ls outputs/

# stop the tunnel
rc-tunnel stop 2>/dev/null || true

# stop the app: Ctrl+C, or
pkill -f "python3 app.py" 2>/dev/null || true
```

Browser: **Profile -> Active Instance -> Destroy Instance**
Next Launch of the same Template + PVC should keep the code and HF cache (depends on the platform's PVC mount point).

---

## Stage I.1 - PVC offline persistence (download once, then restore with zero network)

**Goal:** env / weights / deps all live on the PVC; every Launch after that is one command with no re-download.

### I.1.1 One-time prep (online, do once on the current instance)

```bash
cd /persistent/qingxi-character-workshop/character-workshop

# (a) confirm model markers are complete (True True = models count as present)
python3 -c "from src.model_paths import has_local_llm, has_local_image; print(has_local_llm(), has_local_image())"

# (b) pre-download pip dependency wheels to the PVC (once only)
mkdir -p /persistent/wheels
python3 -m pip download -r requirements.txt -d /persistent/wheels
python3 -m pip download 'accelerate>=0.33.0' --no-deps -d /persistent/wheels
python3 -m pip download psutil packaging -d /persistent/wheels
ls /persistent/wheels | wc -l   # expect dozens of wheels
```

If (a) is not `True True`: check `models/llm/config.json` and `models/image/model_index.json` exist; complete them or re-run `bash scripts/download_models.sh`.

### I.1.2 After every Launch (fully offline restore)

```bash
cd /persistent/qingxi-character-workshop/character-workshop
bash scripts/setup_env.sh
export MOCK=0
python3 app.py
```

Offline behavior of the script:

| Step | Result |
|------|--------|
| torch check | provided by image, not reinstalled |
| deps | `--no-index --find-links /persistent/wheels` fully offline |
| accelerate | same offline |
| models | marker present -> **SKIP, 0 downloads** |
| code load | prefers local `models/` weights |

**Verify offline mode** (output should contain):

```text
==> wheels:   OFFLINE source /persistent/wheels
SKIP (exists): Qwen/Qwen2.5-7B-Instruct -> models/llm
SKIP (exists): cagliostrolab/animagine-xl-3.1 -> models/image
```

If the PVC mount is not `/persistent`: `PVC_WORKSPACE=/your/path bash scripts/setup_env.sh`.

---

## Stage J - Troubleshooting quick reference

| Symptom | Command/Fix |
|------|-----------|
| `cuda_available False` | Switch to a ROCm image; do not install NVIDIA wheels |
| HF download timeout | `HF_ENDPOINT` mirror; retry `download_models.sh` |
| LLM/image OOM | 3B LLM; lower resolution/steps; `unload` then run in stages |
| `No module named src` | `cd` to the directory containing `app.py` |
| Gradio will not open | `curl 127.0.0.1:7860`; check `PORT`; use `rc-tunnel` |
| Still MOCK images | `echo $MOCK` must be empty or `0`; restart the app |
| Quota ran out | Destroy; keep editing code with local MOCK |

---

## Stage K - Minimal "done today" path (compressed)

```bash
# 1) self-check GPU
python3 -c "import torch; print(torch.cuda.is_available(), getattr(torch.version,'hip',None))"

# 2) enter the project, install deps
cd ~/work/character-workshop
pip install -r requirements.txt

# 3) download models
bash scripts/download_models.sh

# 4) generate a card on real hardware
export MOCK=0
python3 -c "from src.orchestrator import generate_card_job,JobState as S;r=generate_card_job('Void traveler in green robes',affinity_pref='Void',mock=False);print(r.state,r.card_path);assert r.state==S.READY"

# 5) Web
python3 app.py
# optional: rc-tunnel expose --port 7860
```

**Definition of done today:** step 4 prints `READY` and `card.png` is a real portrait-composed card.

---

## Relationship to submission (Task 14 preview)

After the real hardware run, prepare:

- Demo video 3-5 min
- English PDF (architecture + ROCm adaptation)
- PPT/poster
- PR: `Track 1, <Team>, Qingxi Character Workshop`

---

## Related documents

- Local MOCK testing: `docs/LOCAL_TESTING.md`
- English README: `README.md`
- Design spec: repo `docs/superpowers/specs/2026-07-26-amd-hackathon-character-workshop-design.md`
- Implementation plan T13: `docs/superpowers/plans/2026-07-26-character-workshop-implementation.md`
