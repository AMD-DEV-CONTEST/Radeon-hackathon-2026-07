# Radeon Cloud validation checklist

This checklist controls the single permitted Phase 3 instance. Maximum intended
active time is 45 minutes; begin shutdown at 35, stop work at 40, destroy by 42,
and use the final three minutes to verify that Active Instance is empty.

## Before launch — no credits running

- [ ] Phase 2 PR is merged and `main` contains commit `a5f3008`.
- [ ] `radeon-validation` preparation commit is pushed.
- [ ] Smoke-test CLI help, unit tests, compilation, and local no-ROCm refusal pass.
- [ ] No model weights, caches, outputs, secrets, or private assets are committed.
- [ ] Browser timer is ready but not started.
- [ ] Starting credit balance is recorded privately.
- [ ] Active Instance is empty. If not, stop and investigate; do not launch another.
- [ ] Template title and visibility are verified.
- [ ] Container is an official Radeon-compatible ROCm 7.2.x image.
- [ ] Deploy type is Notebook / JupyterLab.
- [ ] Storage is Persistent (PVC), not ephemeral.
- [ ] A sanitized pre-launch screenshot is captured without account identifiers.

If the template is ephemeral, do not launch it. Create `BrandPilot-Track1-PVC`
with the same appropriate AMD container, Notebook/Jupyter deployment, Persistent
(PVC) storage, and profile-only visibility. Do not enable public access or SSH.

## Launch and timing

- [ ] Launch exactly one verified template.
- [ ] Record launch-click UTC time.
- [ ] Record 100%-ready UTC time.
- [ ] Start the 45-minute timer only when the instance is ready.
- [ ] Capture a sanitized ready-state screenshot.
- [ ] Open JupyterLab without public tunnels, public APIs, or rc-tunnel.

## Minutes 0–10 — hardware and storage

Run and save only non-sensitive output:

```bash
pwd
whoami
date -u
uname -a
python --version
python3 --version
df -hT
mount
which rocm-smi || true
rocm-smi
rocm-smi --showproductname --showmeminfo vram --showuse
which rocminfo || true
rocminfo | head -n 200
python -m torch.utils.collect_env
```

- [ ] PyTorch imports without installation or upgrade.
- [ ] `torch.cuda.is_available()` is true.
- [ ] `torch.cuda.device_count()` is at least one.
- [ ] Device name identifies AMD Radeon hardware.
- [ ] `torch.version.hip` is populated.
- [ ] Total/free GPU memory is recorded.
- [ ] No NVIDIA CUDA packages are installed.
- [ ] Actual PVC mount is identified from `df`/`mount`, not assumed.
- [ ] `PERSISTENT_ROOT` is set to the verified mount.
- [ ] A marker file is written and read back on that mount.

Do not save raw `env` output. If environment inspection is needed, record only
the allowlisted variables printed by `radeon_environment_check.py`.

## Minutes 10–20 — clone and lightweight dependencies

```bash
export PERSISTENT_ROOT="<verified-pvc-mount>"
mkdir -p "$PERSISTENT_ROOT/source"
git clone --branch radeon-validation --single-branch \
  https://github.com/kmt9967/brandpilot-local.git \
  "$PERSISTENT_ROOT/source/brandpilot-local"
cd "$PERSISTENT_ROOT/source/brandpilot-local"
git rev-parse HEAD
python scripts/radeon_environment_check.py \
  --output "$PERSISTENT_ROOT/environment-before-generation.json"
python -m pip show torch torchvision
python -m pip list
```

- [ ] Checked-out SHA matches the pushed preparation commit.
- [ ] Rights-safe `examples/browser-test-product.png` exists.
- [ ] Free persistent disk space is recorded.
- [ ] Existing package versions are inspected first.
- [ ] Only missing lightweight packages are installed.
- [ ] PyTorch, torchvision, ROCm, and system packages are not replaced.
- [ ] xformers, bitsandbytes, CUDA/NVIDIA wheels, IP-Adapter, and ControlNet are absent.

Permitted missing user-space dependencies:

```bash
python -m pip install --user diffusers transformers accelerate safetensors huggingface_hub Pillow
```

## Minutes 20–35 — one real generation

```bash
cd "$PERSISTENT_ROOT/source/brandpilot-local"
export PYTHON_BIN=python
bash scripts/run_radeon_session.sh
```

- [ ] Script resolves and records an exact 40-character model revision.
- [ ] At least 16 GiB selects SDXL; below/unknown selects SD 1.5.
- [ ] Only the selected model is downloaded.
- [ ] `rocm-smi` is observed during generation where practical.
- [ ] One real output is sufficient.
- [ ] A second warm run occurs only after success with at least 10 minutes remaining.
- [ ] OOM permits only one reduced-memory retry of the same model.
- [ ] No CPU or mock fallback occurs.
- [ ] No fine-tuning, LoRA, video, IP-Adapter, ControlNet, or web-app integration occurs.

Required persistent artifacts:

- [ ] `environment.json`
- [ ] `generation-metadata.json`
- [ ] `generation.log`
- [ ] `generated-output.png` if successful
- [ ] rights-safe input copy
- [ ] package versions
- [ ] sanitized GPU summary
- [ ] session timestamps and exact model revision

## Minutes 35–42 — mandatory shutdown

- [ ] Stop generation/download immediately at minute 35 if completion is at risk.
- [ ] Verify artifacts exist and run `sync`.
- [ ] Stop any running Python/model process.
- [ ] Return to Radeon Cloud Profile.
- [ ] Click **Destroy Instance**; closing JupyterLab is not sufficient.
- [ ] Confirm the destructive instance action.
- [ ] Record destroy-click UTC time.

## Minutes 42–45 — zero-active verification

- [ ] Active Instance is empty after refresh.
- [ ] No instance is Running, Starting, or Stopping.
- [ ] Final credit balance is recorded.
- [ ] A sanitized zero-active screenshot is captured.
- [ ] Total active duration and estimated credits consumed are calculated.
- [ ] No second instance was launched.

## Local evidence review

- [ ] Download only the required small evidence bundle.
- [ ] Do not download caches, weights, system files, or raw environment dumps.
- [ ] Remove emails, account/instance IDs, tokens, authenticated URLs, internal
      hostnames, session IDs, and irrelevant private paths.
- [ ] Retain AMD device name, HIP/ROCm/PyTorch versions, measured memory/timing,
      model/revision/settings, hashes, output, credit use, and sanitized screenshots.
- [ ] Do not update repository status until the instance is destroyed and evidence is verified.
