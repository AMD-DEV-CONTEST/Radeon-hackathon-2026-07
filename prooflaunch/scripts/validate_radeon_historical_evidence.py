#!/usr/bin/env python3
"""Validate the archived Radeon Gemma-4 execution receipt against Notebook bytes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "gemma4_emotion_lora_modelscope_single_gpu_original.ipynb"
RECEIPT = ROOT / "evidence" / "RADEON_GEMMA4_EXECUTION_RECEIPT_2026-08-06.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def output_text(cell: dict) -> str:
    values: list[str] = []
    for output in cell.get("outputs", []):
        candidates = [output.get("text"), output.get("data", {}).get("text/plain")]
        for candidate in candidates:
            if candidate is None:
                continue
            if isinstance(candidate, list):
                candidate = "".join(candidate)
            values.append(str(candidate))
    return "\n".join(values)


def main() -> int:
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    cells = notebook["cells"]
    checks = {
        "notebook_sha256": sha256_file(NOTEBOOK) == receipt["source"]["sha256"],
        "notebook_bytes": NOTEBOOK.stat().st_size == receipt["source"]["bytes"],
        "radeon_device": "device name: AMD Radeon Graphics" in output_text(cells[4]),
        "single_gpu": "torch.cuda.device_count(): 1" in output_text(cells[4]),
        "hip_version": "HIP version: 7.2.53211" in output_text(cells[14]),
        "model_on_gpu": "Base model device: cuda:0" in output_text(cells[14]),
        "key_inference": "'joy'" in output_text(cells[16]),
        "evaluation": all(
            value in output_text(cells[20])
            for value in ("'accuracy': 0.625", "'evaluated_examples': 400")
        ),
        "lora_training": all(
            value in output_text(cells[28])
            for value in ("global_step=250", "training_loss=0.3145033791065216", "train_runtime': 702.3645")
        ),
        "adapter_saved": "Saved adapter and tokenizer" in output_text(cells[30]),
    }
    status = "passed" if all(checks.values()) else "failed"
    print(json.dumps({"schema": "ProofLaunchHistoricalRadeonEvidenceValidationV1", "status": status, "checks": checks}, indent=2))
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
