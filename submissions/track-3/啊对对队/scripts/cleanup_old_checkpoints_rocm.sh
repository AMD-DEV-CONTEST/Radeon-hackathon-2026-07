#!/usr/bin/env bash
set -euo pipefail

MAX_MANAGED_BYTES=$((100 * 1024 * 1024 * 1024))
CHECKPOINT_ROOTS=(
  /workspace/parcel-sorter-opt-v1/outputs/train
  /workspace/parcel-sorter-rocm/outputs/train
  /workspace/parcel-sorter-opt-v1/outputs/mobile-rgbd-v1
  /workspace/parcel-sorter-opt-v1/outputs/mobile-self-improvement-v3-cycle1
)
MANAGED_ROOTS=(
  /workspace/parcel-sorter-opt-v1/outputs
  /workspace/parcel-sorter-rocm/outputs
  /root/.cache/huggingface
  /root/pi05-assets
  /root/pi05-runs
)

for root in "${CHECKPOINT_ROOTS[@]}"; do
  [[ -d "${root}" ]] || continue
  resolved="$(readlink -f "${root}")"
  case "${resolved}" in
    /workspace/parcel-sorter-opt-v1/outputs/*|/workspace/parcel-sorter-rocm/outputs/*) ;;
    *)
      echo "ERROR: refusing unsafe checkpoint root: ${resolved}" >&2
      exit 3
      ;;
  esac
  find "${resolved}" -type d -name checkpoints -prune -print
  find "${resolved}" -type d -name checkpoints -prune -exec rm -rf -- {} +
done

for failed_media in \
  /workspace/parcel-sorter-opt-v1/outputs/pi05-contact-proof-v1 \
  /workspace/parcel-sorter-opt-v1/outputs/pi05-contact-proof-v2 \
  /workspace/parcel-sorter-opt-v1/outputs/pi05-contact-proof-v3; do
  [[ -e "${failed_media}" ]] || continue
  resolved="$(readlink -f "${failed_media}")"
  case "${resolved}" in
    /workspace/parcel-sorter-opt-v1/outputs/pi05-contact-proof-v[123])
      rm -rf -- "${resolved}"
      ;;
    *)
      echo "ERROR: refusing unsafe failed-media path: ${resolved}" >&2
      exit 4
      ;;
  esac
done

stale_dataset_cache=/root/.cache/huggingface/datasets
if [[ -d "${stale_dataset_cache}" ]]; then
  resolved="$(readlink -f "${stale_dataset_cache}")"
  if [[ "${resolved}" != /root/.cache/huggingface/datasets ]]; then
    echo "ERROR: refusing unsafe Hugging Face dataset cache: ${resolved}" >&2
    exit 5
  fi
  rm -rf -- "${resolved}"
fi

existing_roots=()
for root in "${MANAGED_ROOTS[@]}"; do
  [[ -e "${root}" ]] && existing_roots+=("${root}")
done
managed_bytes="$(du -sb "${existing_roots[@]}" | awk '{total += $1} END {print total + 0}')"
printf 'managed_bytes=%s\nmanaged_gib=%.2f\n' \
  "${managed_bytes}" "$(awk -v bytes="${managed_bytes}" 'BEGIN {print bytes / 1073741824}')"
if (( managed_bytes > MAX_MANAGED_BYTES )); then
  echo "ERROR: managed Physical AI assets exceed the 100 GiB budget" >&2
  exit 6
fi
