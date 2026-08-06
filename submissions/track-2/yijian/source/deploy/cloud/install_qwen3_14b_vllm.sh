#!/usr/bin/env bash
set -euo pipefail

PERSIST_ROOT="${YIJIAN_PERSIST_ROOT:-/persistent/yijian}"
WORKSPACE_ROOT="${YIJIAN_WORKSPACE_ROOT:-/workspace/yijian}"
VENV="$WORKSPACE_ROOT/vllm-venv"
HF_HOME="${HF_HOME:-$WORKSPACE_ROOT/huggingface}"
MODEL_DIR="${YIJIAN_QWEN3_14B_MODEL_PATH:-$WORKSPACE_ROOT/qwen3-14b-bf16}"
REVISION="${YIJIAN_QWEN3_14B_REVISION:-40c069824f4251a91eefaf281ebe4c544efd3e18}"
VLLM_ROCM_VARIANT="${YIJIAN_VLLM_ROCM_VARIANT:-rocm721}"
VLLM_COMMIT="${YIJIAN_VLLM_COMMIT:-321fa2d6d1644629ac39d173f6393f37e14bf7b4}"
VLLM_VERSION="${YIJIAN_VLLM_VERSION:-0.20.2rc1.dev15+g321fa2d6d.rocm721}"
VLLM_WHEEL="${YIJIAN_VLLM_WHEEL:-https://wheels.vllm.ai/rocm/$VLLM_COMMIT/vllm-0.20.2rc1.dev15%2Bg321fa2d6d.rocm721-cp312-cp312-manylinux_2_34_x86_64.whl}"
ROCM_INDEX="https://wheels.vllm.ai/rocm/nightly/$VLLM_ROCM_VARIANT"
ROCM_WHEEL_ROOT="https://wheels.vllm.ai/rocm/$VLLM_COMMIT"
ROCM_BOOTSTRAP_WHEELS=(
  "$ROCM_WHEEL_ROOT/torch-2.10.0%2Bgit8514f05-cp312-cp312-manylinux_2_35_x86_64.whl"
  "$ROCM_WHEEL_ROOT/torchvision-0.24.1%2Bd801a34-cp312-cp312-manylinux_2_34_x86_64.whl"
  "$ROCM_WHEEL_ROOT/torchaudio-2.9.0%2Beaa9e4e-cp312-cp312-manylinux_2_34_x86_64.whl"
  "$ROCM_WHEEL_ROOT/flash_attn-2.8.3-cp312-cp312-manylinux_2_34_x86_64.whl"
  "$ROCM_WHEEL_ROOT/triton-3.6.0-cp312-cp312-manylinux_2_35_x86_64.whl"
  "$ROCM_WHEEL_ROOT/amd_aiter-0.1.10.post3-cp312-cp312-manylinux_2_34_x86_64.whl"
  "$ROCM_WHEEL_ROOT/amdsmi-26.2.2%2Be1a6bc5663-py3-none-any.whl"
)

mkdir -p "$WORKSPACE_ROOT" "$HF_HOME" "$WORKSPACE_ROOT/models" \
  "$PERSIST_ROOT/logs" "$PERSIST_ROOT/environment"

command -v rocminfo >/dev/null
gfx_arch="$(rocminfo | grep -m1 -oE 'gfx[0-9]+' || true)"
if [[ "$gfx_arch" != "gfx1100" ]]; then
  echo "当前GPU架构为${gfx_arch:-unknown}，本配置只允许已验收的gfx1100。" >&2
  exit 2
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  python3.12 -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip uv
"$VENV/bin/uv" pip install --python "$VENV/bin/python" \
  --no-deps "${ROCM_BOOTSTRAP_WHEELS[@]}"
"$VENV/bin/uv" pip install --python "$VENV/bin/python" \
  --pre "$VLLM_WHEEL" \
  --index-url "$ROCM_INDEX" \
  --extra-index-url https://pypi.org/simple \
  --index-strategy unsafe-best-match
"$VENV/bin/uv" pip install --python "$VENV/bin/python" huggingface_hub

"$VENV/bin/python" - "$VLLM_VERSION" <<'PY'
import importlib.metadata
import sys

import torch

expected = sys.argv[1]
actual = importlib.metadata.version("vllm")
if actual != expected:
    raise SystemExit(f"vLLM版本不匹配：{actual} != {expected}")
if not torch.version.hip:
    raise SystemExit("vLLM环境错误地安装了CUDA版PyTorch，而不是ROCm版")
nvidia = sorted(
    dist.metadata["Name"]
    for dist in importlib.metadata.distributions()
    if str(dist.metadata.get("Name") or "").lower().startswith("nvidia-")
)
if nvidia:
    raise SystemExit(f"vLLM ROCm环境包含NVIDIA依赖：{nvidia}")
PY

export HF_HOME
export HF_HUB_CACHE="${HF_HUB_CACHE:-$HF_HOME/hub}"
if [[ ! -f "$MODEL_DIR/config.json" ]]; then
  "$VENV/bin/hf" download Qwen/Qwen3-14B \
    --revision "$REVISION" --local-dir "$MODEL_DIR"
fi

"$VENV/bin/python" - "$MODEL_DIR" "$REVISION" "$gfx_arch" "$VLLM_COMMIT" \
  "$PERSIST_ROOT/environment/qwen3-14b-vllm.json" <<'PY'
import hashlib
import importlib.metadata
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

model_dir, revision, gfx_arch, vllm_commit, output = sys.argv[1:]
config = Path(model_dir) / "config.json"
value = {
    "schemaVersion": "yijian-qwen3-14b-vllm-environment-v1",
    "createdAt": datetime.now(timezone.utc).isoformat(),
    "host": platform.node(),
    "python": platform.python_version(),
    "vllm": importlib.metadata.version("vllm"),
    "vllmCommit": vllm_commit,
    "torch": importlib.metadata.version("torch"),
    "transformers": importlib.metadata.version("transformers"),
    "gfxArch": gfx_arch,
    "model": "Qwen/Qwen3-14B",
    "modelRevision": revision,
    "configSha256": hashlib.sha256(config.read_bytes()).hexdigest(),
    "modelPath": model_dir,
}
Path(output).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(value, ensure_ascii=False))
PY

echo "Qwen3-14B与vLLM ROCm隔离环境已准备完成。"
