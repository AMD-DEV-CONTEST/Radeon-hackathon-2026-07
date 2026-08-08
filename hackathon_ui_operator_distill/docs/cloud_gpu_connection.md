# Cloud GPU Connection Notes

Use this when you get a cloud GPU machine from Kaggle, RunPod, Vast.ai, Lambda, Paperspace, or a hackathon cluster.

## Option A: SSH Cloud GPU

On your laptop:

```powershell
ssh-keygen -t ed25519 -C "ui-operator-hackathon"
type $env:USERPROFILE\.ssh\id_ed25519.pub
```

Copy the public key into the cloud GPU provider.

Connect:

```powershell
ssh ubuntu@YOUR_SERVER_IP
```

Keep a second terminal open for file sync:

```powershell
scp -r .\hackathon_ui_operator_distill ubuntu@YOUR_SERVER_IP:~/hackathon_ui_operator_distill
```

Download results back:

```powershell
scp -r ubuntu@YOUR_SERVER_IP:~/hackathon_ui_operator_distill/runs .\hackathon_ui_operator_distill\
scp ubuntu@YOUR_SERVER_IP:~/hackathon_ui_operator_distill/cloud/ui_detector_int8.onnx .\hackathon_ui_operator_distill\local_runtime\models\
```

## Option B: Kaggle Notebook

1. Create a new Kaggle notebook.
2. Enable GPU in notebook settings.
3. Upload this folder as a dataset or clone from GitHub.
4. Run:

```bash
cd /kaggle/working
git clone YOUR_REPO_URL hackathon_ui_operator_distill
cd hackathon_ui_operator_distill
bash cloud/setup_cloud_gpu.sh
```

For AMD-specific hackathon points, Kaggle may not be enough if it provides NVIDIA GPUs. Use AMD ROCm hardware if the organizer provides it.

## Option C: AMD ROCm Node

Check GPU:

```bash
rocminfo | head
rocm-smi
```

Install PyTorch ROCm according to the official selector for your ROCm version:

```bash
python -m pip install --upgrade pip
pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm6.1
```

Verify:

```bash
python - <<'PY'
import torch
print(torch.__version__)
print(torch.cuda.is_available())
print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else "no gpu")
PY
```

PyTorch ROCm still uses the `cuda` API name in code, so `torch.cuda.is_available()` can be true on AMD ROCm.

## Kubernetes AMD GPU Error

If you see:

```text
Insufficient amd.com/gpu
```

it means the cluster has no free AMD GPU for your pod right now, or your quota/device plugin is not exposing GPUs. It is usually not a ban.

Try reducing GPU request:

```yaml
resources:
  limits:
    amd.com/gpu: 1
```

Or wait for capacity / ask organizers for GPU quota.

