# Radeon Cloud - Clean Start From Zero (avoiding the CUDA torch trap)

For: after the environment is messed up, **Destroy and start over**, or the first time on the cloud.
Follow in order, **do not skip steps**. Each step has **pass criteria**; if a step fails, stop - do not keep `pip install`-ing.

| Item | Value |
|----|-----|
| Repo | https://github.com/Marsbler/qingxi-character-workshop |
| Branch | `feature/character-workshop` |
| App dir | `.../qingxi-character-workshop/character-workshop` (contains `app.py`) |
| Cloud console | https://radeon-global.anruicloud.com/ |

---

## Absolutely forbidden (violating this breaks everything)

```bash
# FORBIDDEN: run before confirming ROCm torch
pip install -r requirements.txt
pip install torch
pip install accelerate          # pulls CUDA torch from the default index
pip install torch -i https://pypi.tuna.tsinghua.edu.cn/simple
```

```text
FORBIDDEN: pick NVIDIA / CUDA-specific images (the contest requires AMD Radeon + ROCm)
FORBIDDEN: continue download_models / generation after seeing device=cpu or torch=+cu*
```

---

## Step 0 - Destroy the old instance (when you need to start over)

1. Open Radeon Cloud in the browser -> **Profile**
2. **Active Instance** -> **Destroy Instance**
3. Wait for the instance to disappear

**PVC notes:**

- If a `+cu` torch was previously `pip install --user`-ed into the PVC, the new instance can still be dirty.
- If torch is still `+cu*` right after restarting, run the **Appendix: cleaning user site-packages** at the end.

---

## Step 1 - Create / launch the correct Template

1. **Profile -> My Templates -> Add Template** (or reuse an existing correct template)
2. Required:
   - **Container Image:** the name contains **ROCm** / **Radeon** / **PyTorch ROCm** (per the platform list)
   - **Storage: Persistent (PVC)**
3. **Launch** -> wait for 100% -> **Open Notebook** -> open **Terminal**

The current directory is usually `/workspace`.

---

## Step 2 - Hardware gate (switch the image if it fails)

```bash
rocm-smi
# if the command is missing:
ls -la /dev/kfd /dev/dri 2>/dev/null || true
cat /opt/rocm/.info/version 2>/dev/null || true
```

**Pass criteria:**

- `rocm-smi` sees an AMD GPU, **or**
- `/dev/kfd` exists and `/opt/rocm` has version info

**On failure:** Destroy, switch to a ROCm image Template; do not install software to force it.

---

## Step 3 - Image's built-in torch gate (check before installing)

```bash
python3 - <<'PY'
import torch
print("version:", torch.__version__)
print("available:", torch.cuda.is_available())
print("hip:", getattr(torch.version, "hip", None))
print("cuda_str:", getattr(torch.version, "cuda", None))
print("file:", torch.__file__)
if torch.cuda.is_available():
    print("name:", torch.cuda.get_device_name(0))
PY
```

### Case A - ideal (go straight to step 5)

```text
version: contains rocm (e.g. 2.x.x+rocm6.x)
available: True
hip: has a version number
```

-> Do **not** `pip install torch` again. Jump to **step 5**.

### Case B - no torch / ImportError

-> Do **step 4** to install ROCm torch.

### Case C - `+cu*` or `available: False`

-> Clean up first, then install ROCm (full step 4). If still False after cleaning -> image/GPU problem, switch Template.

---

## Step 4 - Install ROCm PyTorch only if needed

```bash
# 4.1 remove the wrong CUDA packages (uninstall if present; fine if not)
python3 -m pip uninstall -y torch torchvision torchaudio 2>/dev/null || true
python3 -m pip freeze 2>/dev/null | grep -iE '^nvidia-|^cuda-toolkit|^triton==' | cut -d= -f1 | xargs -r python3 -m pip uninstall -y

# 4.2 check the ROCm major version (to pick the wheel)
cat /opt/rocm/.info/version 2>/dev/null || echo "no /opt/rocm version file"

# 4.3 install from the official PyTorch ROCm index (do NOT use the Tsinghua default index for torch)
# adjust rocm6.2 -> rocm6.1 / rocm6.3 to match your ROCm
python3 -m pip install torch torchvision torchaudio \
  --index-url https://download.pytorch.org/whl/rocm6.2
```

**Then rerun the step 3 detection script.**

**Pass criteria (all must be satisfied):**

```text
available: True
version: contains rocm, and not something like plain +cu130
hip: not None
```

Not satisfied -> **STOP**, do not clone then install deps carelessly.

---

## Step 5 - Get the code

```bash
cd /workspace

# if cert errors (you hit these before)
export GIT_SSL_NO_VERIFY=1

# if the old directory is dirty, move it aside first
mv qingxi-character-workshop qingxi-character-workshop.bak.$(date +%s) 2>/dev/null || true

git clone https://github.com/Marsbler/qingxi-character-workshop.git
cd qingxi-character-workshop
git checkout feature/character-workshop
git pull origin feature/character-workshop

cd character-workshop
test -f app.py && echo "CODE OK" || (echo "CODE FAIL" && exit 1)
ls -la app.py requirements.txt scripts/install_app_deps.sh
```

**Pass criterion:** prints `CODE OK`, and `scripts/install_app_deps.sh` exists.

---

## Step 6 - Safely install app dependencies (the only recommended way)

```bash
cd /workspace/qingxi-character-workshop/character-workshop

# re-confirm ROCm torch (gate)
python3 -c "import torch; assert torch.cuda.is_available(); print(torch.__version__, torch.version.hip)"

# use the repo script (has preflight / postflight, prevents torch being overwritten to +cu)
bash scripts/install_app_deps.sh
```

The script will:

1. Check torch is already ROCm-available
2. `pip install -r requirements.txt` (does **not** include the accelerate hard dependency that drags in CUDA torch)
3. **Check again** that torch is still ROCm

**Pass criterion:** the script prints `INSTALL APP DEPS OK`.

If it fails and says torch got overwritten -> go back to step 4; do **not** keep running `pip install -r`.

---

## Step 7 - Project device detection

```bash
cd /workspace/qingxi-character-workshop/character-workshop
export MOCK=0

python3 - <<'PY'
from src.device import detect_device, vram_profile
d = detect_device()
print(d)
print("profile", vram_profile(d))
assert d.mock_mode is False
assert d.device_type == "cuda", d
assert d.rocm_hint or (d.torch_version and "rocm" in d.torch_version.lower())
print("PROJECT DEVICE OK")
PY
```

**Pass criterion:** `PROJECT DEVICE OK`, `device_type=cuda`, `vram_gb` has a value.

---

## Step 8 - Download models

```bash
cd /workspace/qingxi-character-workshop/character-workshop
export MOCK=0
# optional HF mirror
# export HF_ENDPOINT=https://hf-mirror.com

bash scripts/download_models.sh
```

This takes a long time; keep the instance alive (do not Destroy). The PVC keeps the cache.

---

## Step 9 - Real-hardware card smoke test (P0)

```bash
cd /workspace/qingxi-character-workshop/character-workshop
export MOCK=0

python3 - <<'PY'
from src.orchestrator import generate_card_job, JobState
r = generate_card_job(
    user_text="A quiet green-robed Void traveler carrying a paper lantern",
    affinity_pref="Void",
    mock=False,
)
print(r.state, r.job_id, r.error)
print("card", r.card_path)
assert r.state == JobState.READY
assert r.card_path and r.card_path.exists()
print("CARD E2E OK")
PY
```

**Pass criterion:** `CARD E2E OK`, `outputs/<id>/card.png` is a real portrait (not MOCK color-block text).

---

## Step 10 - Launch the Web UI

```bash
cd /workspace/qingxi-character-workshop/character-workshop
export MOCK=0
export PORT=7860
python3 app.py
```

Optional public access (official tunnel):

```bash
# open another Terminal
/var/run/secrets/frp-self-service/install
export PATH="$HOME/.local/bin:$PATH"
rc-tunnel expose --port 7860
```

When done:

```bash
rc-tunnel stop 2>/dev/null || true
# Destroy the instance in the browser to save quota
```

---

## Correct order master list (memorize)

```text
Destroy dirty instance (optional)
  -> pick a ROCm image, Launch
  -> rocm-smi shows GPU
  -> torch in python is already ROCm and available=True
       (else install ONLY ROCm torch, never the default torch)
  -> git clone + checkout feature/character-workshop
  -> bash scripts/install_app_deps.sh   <- the only recommended way to install deps
  -> detect_device passes
  -> download_models
  -> generate_card_job MOCK=0
  -> app.py
```

> If the PVC is already offline-persisted, replace step "install deps" with `bash scripts/setup_env.sh` (see Step 11).

---

## Step 11 - PVC offline persistence (download once, then restore with zero network)

### 11.1 One-time prep (online, do once)

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

### 11.2 After every Launch (fully offline restore)

```bash
cd /persistent/qingxi-character-workshop/character-workshop
bash scripts/setup_env.sh
export MOCK=0
python3 app.py
```

**Verify offline mode** (output should contain):

```text
==> wheels:   OFFLINE source /persistent/wheels
SKIP (exists): Qwen/Qwen2.5-7B-Instruct -> models/llm
SKIP (exists): cagliostrolab/animagine-xl-3.1 -> models/image
```

If the PVC mount is not `/persistent`: `PVC_WORKSPACE=/your/path bash scripts/setup_env.sh`.

---

## Appendix A - Clean leftover CUDA packages in PVC

When a new instance starts with `+cu*`:

```bash
python3 -c "import torch,sys; print(torch.__file__); print(sys.path)"

# leftovers in the user directory
rm -rf ~/.local/lib/python*/site-packages/torch*
rm -rf ~/.local/lib/python*/site-packages/nvidia*
rm -rf ~/.local/lib/python*/site-packages/cuda*

python3 -m pip uninstall -y torch torchvision torchaudio 2>/dev/null || true
# then redo steps 3-4
```

---

## Appendix B - Git cert errors

```bash
export GIT_SSL_NO_VERIFY=1
# or
sudo apt-get update && sudo apt-get install -y ca-certificates && sudo update-ca-certificates
```

---

## Appendix C - Sync the cloud after local code changes

**Local:**

```powershell
cd "D:\APP\...\.worktrees\character-workshop"
git add -A
git commit -m "your message"
git push origin feature/character-workshop
```

**On the cloud:**

```bash
cd /workspace/qingxi-character-workshop
export GIT_SSL_NO_VERIFY=1
git pull origin feature/character-workshop
cd character-workshop
# usually no need to reinstall deps; only rerun install_app_deps.sh if requirements changed
```

---

## Appendix D - Mapping to the old checklist sections

| Old section | This document |
|--------|--------|
| A create instance | steps 0-1 |
| B GPU self-check | step 2 |
| C clone | step 5 |
| D deps | steps 3-6 (**this document wins**) |
| E models | step 8 |
| F smoke | step 9 |
| G Web | step 10 |
