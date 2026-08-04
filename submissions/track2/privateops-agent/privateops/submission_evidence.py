from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any


SOURCE_RELATIVE = Path("submission/evidence/rocm-verified/radeon-benchmark-run.json")
AGENT_LATENCY_RELATIVE = Path("submission/evidence/rocm-verified/rocm-agent-live-latency-zh.txt")
REQUIRED_RUN_FIELDS = {
    "run_id",
    "provider_mode",
    "verified",
    "gpu_name",
    "rocm_version",
    "model_name",
    "latency_ms",
    "tokens_per_second",
    "prompt_tokens",
    "completion_tokens",
}


def build_submission_evidence(root: Path) -> dict[str, Any]:
    source_path = root / SOURCE_RELATIVE
    latency_path = root / AGENT_LATENCY_RELATIVE
    run = json.loads(source_path.read_text(encoding="utf-8"))
    missing = sorted(REQUIRED_RUN_FIELDS.difference(run))
    if missing:
        raise ValueError(f"Verified Radeon record is missing: {', '.join(missing)}")
    if run["provider_mode"] != "rocm-local" or run["verified"] is not True:
        raise ValueError("Verified Radeon record must use rocm-local and verified=true.")
    agent_latency_seconds = float(latency_path.read_text(encoding="utf-8").strip())
    derived_run = dict(run)
    derived_run["agent_latency_ms"] = round(agent_latency_seconds * 1000, 3)
    return {
        "schema_version": "1.0",
        "status": "verified_radeon_rocm_capture",
        "claim": "Measured on AMD Radeon + ROCm through a same-instance loopback vLLM endpoint.",
        "source": "evidence/rocm-verified/radeon-benchmark-run.json",
        "agent_latency_source": "evidence/rocm-verified/rocm-agent-live-latency-zh.txt",
        "runs": [derived_run],
    }


def render_submission_csv(payload: dict[str, Any]) -> str:
    fields = [
        "run_id",
        "created_at",
        "label",
        "provider_mode",
        "verified",
        "gpu_name",
        "rocm_version",
        "model_name",
        "latency_ms",
        "tokens_per_second",
        "prompt_tokens",
        "completion_tokens",
        "agent_latency_ms",
        "notes",
    ]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(payload["runs"])
    return stream.getvalue()
