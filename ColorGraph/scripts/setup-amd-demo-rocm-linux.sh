#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
venv_path=${1:-"$repo_root/.venv-rocm"}
official_requirements="$repo_root/backend/requirements-amd-rocm-linux-7.2.1.txt"
cloud_requirements="$repo_root/backend/requirements-amd-rocm-linux-radeon-cloud-7.2.1.txt"
platform_python=${COLORGRAPH_ROCM_SOURCE_PYTHON:-}

if [[ -z "$platform_python" && -x /opt/venv/bin/python ]]; then
    platform_identity=$(/opt/venv/bin/python -c \
        'import torch; print(torch.__version__); print(torch.version.hip or "")')
    mapfile -t platform_fields <<<"$platform_identity"
    if [[ "${platform_fields[0]:-}" == "2.9.1+gitff65f5b" \
        && "${platform_fields[1]:-}" == 7.2.53211-* ]]; then
        platform_python=/opt/venv/bin/python
    fi
fi

for command_name in python3 rocminfo amd-smi ffmpeg ffprobe; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        printf 'Required command is missing: %s\n' "$command_name" >&2
        exit 1
    fi
done

python_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [[ "$python_version" != "3.12" ]]; then
    printf 'Python 3.12 is required; observed %s\n' "$python_version" >&2
    exit 1
fi

mapfile -t render_nodes < <(find /dev/dri -maxdepth 1 -name 'renderD*' -print 2>/dev/null | sort)
if [[ -n "${COLORGRAPH_VAAPI_DEVICE:-}" ]]; then
    vaapi_device=$COLORGRAPH_VAAPI_DEVICE
elif [[ ${#render_nodes[@]} -eq 1 ]]; then
    vaapi_device=${render_nodes[0]}
else
    printf 'Set COLORGRAPH_VAAPI_DEVICE; discovered %d render nodes.\n' "${#render_nodes[@]}" >&2
    exit 1
fi
if [[ ! -r "$vaapi_device" || ! -w "$vaapi_device" ]]; then
    printf 'VAAPI render node is not readable and writable: %s\n' "$vaapi_device" >&2
    exit 1
fi

encoders=$(ffmpeg -hide_banner -encoders 2>&1)
for encoder in h264_vaapi hevc_vaapi; do
    if ! grep -Eq "(^|[[:space:]])${encoder}([[:space:]]|$)" <<<"$encoders"; then
        printf 'FFmpeg does not expose %s\n' "$encoder" >&2
        exit 1
    fi
done

if [[ ! -x "$venv_path/bin/python" ]]; then
    if [[ -e "$venv_path" ]]; then
        printf 'Refusing to reuse a non-venv path: %s\n' "$venv_path" >&2
        exit 1
    fi
    python3 -m venv "$venv_path"
fi

"$venv_path/bin/python" -m pip install --upgrade pip wheel
if [[ -n "$platform_python" ]]; then
    source_identity=$("$platform_python" -c \
        'import torch, torchvision; print(torch.__version__); print(torchvision.__version__); print(torch.version.hip or "")')
    mapfile -t source_fields <<<"$source_identity"
    if [[ "${source_fields[0]:-}" != "2.9.1+gitff65f5b" \
        || "${source_fields[1]:-}" != "0.24.1+d801a34" \
        || "${source_fields[2]:-}" != 7.2.53211-* ]]; then
        printf 'Unsupported platform ROCm identity: %s / %s / %s\n' \
            "${source_fields[0]:-missing}" \
            "${source_fields[1]:-missing}" \
            "${source_fields[2]:-missing}" >&2
        exit 1
    fi
    "$venv_path/bin/python" -m pip install --no-cache-dir -r "$cloud_requirements"
    source_site=$($platform_python -c \
        'import site; print(next(path for path in site.getsitepackages() if path.endswith("site-packages")))')
    destination_site=$("$venv_path/bin/python" -c \
        'import site; print(next(path for path in site.getsitepackages() if path.endswith("site-packages")))')
    "$venv_path/bin/python" - "$source_site" "$destination_site" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1]).resolve()
destination = Path(sys.argv[2]).resolve()
patterns = (
    "torch",
    "torch-*.dist-info",
    "torchvision",
    "torchvision-*.dist-info",
    "functorch",
    "torchgen",
    "triton",
    "triton-*.dist-info",
    "triton_kernels",
    "triton_kernels-*.dist-info",
)
for pattern in patterns:
    matches = sorted(source.glob(pattern))
    if not matches:
        raise SystemExit(f"platform ROCm package is missing: {pattern}")
    for package in matches:
        link = destination / package.name
        if link.exists() or link.is_symlink():
            if not link.is_symlink() or link.resolve() != package.resolve():
                raise SystemExit(f"refusing to replace existing package path: {link}")
            continue
        link.symlink_to(package, target_is_directory=package.is_dir())
PY
else
    "$venv_path/bin/python" -m pip install --no-cache-dir -r "$official_requirements"
fi
"$venv_path/bin/python" -m pip install --no-deps -e "$repo_root/backend"
"$venv_path/bin/python" -m pip check

export COLORGRAPH_DEVICE=rocm
export COLORGRAPH_VAAPI_DEVICE="$vaapi_device"
"$venv_path/bin/colorgraph" doctor

printf 'ROCm environment ready: %s\n' "$venv_path"
printf 'VAAPI device: %s\n' "$vaapi_device"
