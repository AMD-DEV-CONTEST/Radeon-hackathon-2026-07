# Radeon Host Capture Protocol

This segment is a hard truth gate for the final film. Run it only on the actual AMD Radeon machine that executes the project. Record one continuous 1920×1080 or 4K screen capture; do not replace or composite terminal output.

## Preflight

Frame the terminal large enough for device identity and output paths to remain readable after 1080p delivery. Show the system clock, then run:

```bash
rocminfo | sed -n '1,120p'
rocm-smi --showproductname --showmeminfo vram --showuse --showtemp
python - <<'PY'
import json, torch
print(json.dumps({
    "torch": torch.__version__,
    "hip": torch.version.hip,
    "cuda_api_available": torch.cuda.is_available(),
    "device_count": torch.cuda.device_count(),
    "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    "total_memory_bytes": torch.cuda.get_device_properties(0).total_memory if torch.cuda.is_available() else None,
}, indent=2))
PY
```

## Project-bound observation

Capture the project-owned runtime probe and preserve its exit code:

```bash
python scripts/capture_v10_radeon_live_preflight.py \
  --output evidence/v10/radeon-live-preflight.json
printf 'exit_code=%s\n' "$?"
jq '{observed_at,host,torch,radeon_runtime_observed,bf16_matmul_observed,backward_observed,sdpa_observed,probe_elapsed_seconds,peak_memory_allocated_bytes,preflight_passed,content_sha256}' \
  evidence/v10/radeon-live-preflight.json
```

Then execute the exact product/model command selected for the submission while a second visible pane runs:

```bash
watch -n 1 rocm-smi --showproductname --showmeminfo vram --showuse --showtemp
```

The command, its completion, resulting file, `ffprobe` output and SHA-256 must appear in the same continuous recording.

## Required receipt fields

- `gpu_name`
- `total_vram_bytes` and observed free/peak memory
- `rocm_version`
- `hip_version`
- `torch_version`
- BF16 forward, backward and attention pass status
- exact project command and exit code
- model or workload identifier and immutable revision
- elapsed time and peak VRAM
- final output path, byte size and SHA-256
- `execution_observed: true`

## Reject conditions

Reject the segment if the device name is hidden, the terminal is cut between command and completion, the receipt says `false` or `null`, the output cannot be opened, or the result shown after the run has a different hash from the result in the receipt.

Current status: blocked. Existing project receipts explicitly report `radeon_execution_observed: false`.
