#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
venv_path=${COLORGRAPH_ROCM_VENV:-"$repo_root/.venv-rocm"}
output_root=${COLORGRAPH_AMD_OUTPUT_ROOT:-"$repo_root/output/evidence/amd-full-rocm-linux"}
project_id=${COLORGRAPH_AMD_PROJECT_ID:-"amd-demo-snowdonia-12-5s-bd7a0a7dd9"}
ollama_runtime_version=${COLORGRAPH_OLLAMA_CREATIVE_RUNTIME_VERSION:-"0.20.6"}
ollama_server_log=${COLORGRAPH_OLLAMA_SERVER_LOG:-}
batch_size=${COLORGRAPH_AMD_BATCH_SIZE:-4}
expected_ollama_digest=a2845456d7ad1e2100f620eaad82c3e63860a24330948111f6ad5d8202fd3634

colorgraph="$venv_path/bin/colorgraph"
python="$venv_path/bin/python"
if [[ ! -x "$colorgraph" || ! -x "$python" ]]; then
    printf 'ColorGraph ROCm environment is missing: %s\n' "$venv_path" >&2
    exit 1
fi
for command_name in ollama ffmpeg ffprobe; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        printf 'Required command is missing: %s\n' "$command_name" >&2
        exit 1
    fi
done
if [[ ! "$batch_size" =~ ^[1-9][0-9]*$ ]]; then
    printf 'COLORGRAPH_AMD_BATCH_SIZE must be a positive integer.\n' >&2
    exit 1
fi
if [[ -z "$ollama_server_log" || ! -r "$ollama_server_log" ]]; then
    printf 'Set COLORGRAPH_OLLAMA_SERVER_LOG to the readable Ollama server log.\n' >&2
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

ollama_metadata=$("$python" - <<'PY'
import json
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=5) as response:
    version = json.load(response)["version"]
with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=10) as response:
    models = json.load(response).get("models", [])
matches = [
    model for model in models
    if model.get("name") == "colorgraph-qwen3.5:9b"
    or model.get("model") == "colorgraph-qwen3.5:9b"
]
if len(matches) != 1:
    raise SystemExit(f"expected one colorgraph-qwen3.5:9b model, observed {len(matches)}")
model = matches[0]
print(version)
print(str(model.get("digest", "")).removeprefix("sha256:"))
print(model.get("details", {}).get("quantization_level", ""))
PY
)
mapfile -t ollama_fields <<<"$ollama_metadata"
if [[ "${ollama_fields[0]:-}" != "$ollama_runtime_version" ]]; then
    printf 'Ollama runtime mismatch: expected %s, observed %s\n' \
        "$ollama_runtime_version" "${ollama_fields[0]:-missing}" >&2
    exit 1
fi
if [[ "${ollama_fields[1]:-}" != "$expected_ollama_digest" ]]; then
    printf 'Ollama model digest mismatch: %s\n' "${ollama_fields[1]:-missing}" >&2
    exit 1
fi
if [[ "${ollama_fields[2]:-}" != "Q4_K_M" ]]; then
    printf 'Ollama model quantization is not Q4_K_M: %s\n' "${ollama_fields[2]:-missing}" >&2
    exit 1
fi

export LIBVA_DRIVER_NAME=${LIBVA_DRIVER_NAME:-radeonsi}
ffmpeg -hide_banner -loglevel error -y -vaapi_device "$vaapi_device" \
    -f lavfi -i 'color=c=black:s=256x256:r=1:d=0.04' \
    -vf 'format=nv12,hwupload' -frames:v 1 -an -c:v h264_vaapi -f null -
ffmpeg -hide_banner -loglevel error -y -vaapi_device "$vaapi_device" \
    -f lavfi -i 'color=c=black:s=256x256:r=1:d=0.04' \
    -vf 'format=p010le,hwupload' -frames:v 1 -an -c:v hevc_vaapi \
    -profile:v main10 -f null -

huggingface_redirect="$repo_root/backend/models/huggingface.redirect"
if [[ -n "${COLORGRAPH_HUGGINGFACE_CACHE_DIR:-}" ]]; then
    huggingface_cache=$COLORGRAPH_HUGGINGFACE_CACHE_DIR
elif [[ -f "$huggingface_redirect" ]]; then
    huggingface_cache=$(<"$huggingface_redirect")
else
    huggingface_cache="$repo_root/backend/models/huggingface"
fi
declare -A required_snapshots=(
    [models--openai--clip-vit-base-patch32]=3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268
    [models--nvidia--segformer-b0-finetuned-ade-512-512]=489d5cd81a0b59fab9b7ea758d3548ebe99677da
    [models--depth-anything--Depth-Anything-V2-Small-hf]=5426e4f0f36572d16453bbda7a8389317b1bef99
)
for model_directory in "${!required_snapshots[@]}"; do
    snapshot="$huggingface_cache/$model_directory/snapshots/${required_snapshots[$model_directory]}"
    if [[ ! -d "$snapshot" ]]; then
        printf 'Required pinned Hugging Face snapshot is missing: %s\n' "$snapshot" >&2
        exit 1
    fi
done

mkdir -p "$output_root"
precision_report="$output_root/precision-gate-rocm.json"
full_report="$output_root/amd-full-pipeline-report.json"
source_manifest="$repo_root/output/evidence/bench-001-amd-demo-source/manifest.json"

export COLORGRAPH_DEVICE=rocm
export COLORGRAPH_VAAPI_DEVICE="$vaapi_device"
export COLORGRAPH_VIDEO_ENCODER=h264_vaapi
export COLORGRAPH_VIDEO_ENCODER_10BIT=hevc_vaapi
export COLORGRAPH_ENABLE_OLLAMA_CREATIVE_PROVIDER=true
export COLORGRAPH_OLLAMA_CREATIVE_MODEL=colorgraph-qwen3.5:9b
export COLORGRAPH_OLLAMA_CREATIVE_MODEL_DIGEST="$expected_ollama_digest"
export COLORGRAPH_OLLAMA_CREATIVE_RUNTIME_VERSION="$ollama_runtime_version"
export COLORGRAPH_OLLAMA_CREATIVE_QUANTIZATION=Q4_K_M
export COLORGRAPH_OLLAMA_CREATIVE_REQUIRE_GPU=true
export COLORGRAPH_OLLAMA_CREATIVE_MIN_GPU_OFFLOAD_RATIO=0.99
export COLORGRAPH_OLLAMA_CREATIVE_UNLOAD_AFTER_REQUEST=true
export COLORGRAPH_OLLAMA_CREATIVE_IMAGE_INPUT=true
export COLORGRAPH_OLLAMA_CREATIVE_STRICT_OUTPUT=true
export COLORGRAPH_OLLAMA_CREATIVE_MAX_CONTEXT_TOKENS=8192
export COLORGRAPH_OLLAMA_CREATIVE_MAX_IMAGES=1
export COLORGRAPH_OLLAMA_SERVER_LOG="$ollama_server_log"
export COLORGRAPH_HUGGINGFACE_CACHE_DIR="$huggingface_cache"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1

cd "$repo_root/backend"
printf '1/3 Verifying ROCm, OCIO, and media tools...\n'
"$colorgraph" doctor
printf '2/3 Running the three-repeat ROCm FP32 precision gate...\n'
"$colorgraph" precision-gate --require-runtime rocm --repeats 3 --output "$precision_report"
printf '3/3 Running AI, Ollama ROCm, AMD Demo, Main10 VAAPI, and hard QA...\n'
"$colorgraph" amd-full-pipeline "$project_id" \
    --source-manifest "$source_manifest" \
    --precision-report "$precision_report" \
    --output-dir "$output_root" \
    --output "$full_report" \
    --batch-size "$batch_size" \
    --ollama-server-log "$ollama_server_log"

printf 'Full AMD pipeline passed.\nReport: %s\n' "$full_report"
