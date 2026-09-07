# Remote ROCm Setup

Environment detection is separate from installation. The remote instance is inspected
first; wheels are installed only when the existing HIP PyTorch build is missing or mismatched.

## Validated Radeon Cloud runtime (2026-08-04)

The validated native run used one device reported by PyTorch as `AMD Radeon Graphics`
(`gfx1100`, 48, 48.1 GiB visible memory) with this stack:

| Component | Measured value |
|---|---|
| Python | 3.12.3 |
| PyTorch | 2.9.1+rocm7.2.1.gitff65f5bc |
| HIP runtime reported by PyTorch | 7.2.53211-e1a6bc5663 |
| Genesis | 1.1.2 (`gs.amdgpu`, device `cuda:0`) |
| LeRobot | 0.6.0 |
| Transformers | 5.5.4 |

`check_env --require-amd --init-genesis` executed a real tensor/backward pass on
`cuda:0` and initialized the Genesis AMD backend. The contest notebook itself is an
unprivileged Kubernetes container, so it cannot start a nested Docker daemon or apply
container image layers (`CAP_SYS_ADMIN` is unavailable). The validated run therefore used
the exact dependency stack natively, with separate checks for the Compose model,
Dockerfile stages, pinned base-image digest, and container contract. The image remains
runnable on a normal ROCm Docker host with `/dev/kfd` and `/dev/dri` access.

## Step 1: Record the untouched environment

~~~bash
python3 --version
rocminfo | head -n 100
amd-smi
rocm-smi

python3 - <<'PY'
try:
    import torch
except Exception as exc:
    print("torch_import_error:", repr(exc))
else:
    print("torch:", torch.__version__)
    print("hip:", torch.version.hip)
    print("available:", torch.cuda.is_available())
    print("count:", torch.cuda.device_count())
PY
~~~

If torch.version.hip is non-null and the Radeon device is available, preserve that build.

## Step 2: Install a matching build only when needed

The Track 3 starter revision inspected on 2026-08-03 documents the following combination:

~~~text
Python 3.12
ROCm 7.2.1
torch 2.9.1 ROCm wheel
torchvision 0.24.0 ROCm wheel
torchaudio 2.9.0 ROCm wheel
triton 3.5.1 ROCm wheel
~~~

Use the exact commands from the official starter README only when the instance reports
that same ROCm and Python combination:

https://github.com/wangxunx/franka_fruit_pick_demo

For any other ROCm version, select the matching build from official AMD ROCm
documentation or the contest image instructions.

## Step 3: Protect the validated build

After installing the remaining dependencies:

~~~bash
python -m pip check
python - <<'PY'
import torch
assert torch.version.hip is not None
assert torch.cuda.is_available()
print(torch.__version__)
print(torch.version.hip)
print(torch.cuda.get_device_name(0))
PY
~~~

Then capture a package snapshot:

~~~bash
python -m pip freeze > docs/requirements.remote.freeze.txt
~~~

Do not use the local CPU requirements as the remote PyTorch installation source.
