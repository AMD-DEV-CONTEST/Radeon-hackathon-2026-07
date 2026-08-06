#!/usr/bin/env python3
"""Build the single machine-readable source of truth used by submission documents."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def load(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def file_hash(path: Path | None) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path and path.is_file() else None


def adapter_freeze_verified(value: dict[str, Any]) -> bool:
    """Treat a frozen, content-addressed adapter as a passed freeze stage."""
    return (
        value.get("schemaVersion") == "yijian-lora-adapter-freeze-v1"
        and value.get("frozen") is True
        and isinstance(value.get("adapterTreeSha256"), str)
        and len(value["adapterTreeSha256"]) == 64
        and value.get("baseRevision") == "40c069824f4251a91eefaf281ebe4c544efd3e18"
    )


def environment_verified(value: dict[str, Any]) -> bool:
    """Verify the pinned ROCm/vLLM environment evidence without inventing a flag."""
    required_text = ("vllm", "vllmCommit", "torch", "transformers", "gfxArch")
    return (
        value.get("schemaVersion") == "yijian-qwen3-14b-vllm-environment-v1"
        and value.get("model") == "Qwen/Qwen3-14B"
        and value.get("modelRevision") == "40c069824f4251a91eefaf281ebe4c544efd3e18"
        and all(isinstance(value.get(key), str) and bool(value[key]) for key in required_text)
        and value.get("gfxArch") == "gfx1100"
    )


def artifact(
    path: Path | None,
    verifier: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    value = load(path)
    return {
        "available": value is not None,
        "passed": bool(value and (verifier(value) if verifier else value.get("passed") is True)),
        "sha256": file_hash(path),
        "data": value,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-manifest", type=Path, required=True)
    parser.add_argument("--smoke", type=Path, required=True)
    parser.add_argument("--micro", type=Path)
    parser.add_argument("--full", type=Path)
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--environment", type=Path)
    parser.add_argument("--evaluation", type=Path)
    parser.add_argument("--blind", type=Path)
    parser.add_argument("--sealed", type=Path)
    parser.add_argument("--coexist", type=Path)
    parser.add_argument("--public-snapshot", type=Path)
    parser.add_argument("--release-gate", type=Path)
    parser.add_argument("--video-status", default="pending")
    parser.add_argument("--video-schedule", default="today")
    parser.add_argument("--presentation-status", default="owner_managed")
    parser.add_argument("--presentation-schedule", default="owner_decides")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    agent = load(args.agent_manifest)
    smoke = load(args.smoke)
    if not agent or (agent.get("counts") or {}).get("train") != 720:
        parser.error("agent manifest must prove exactly 720 train records")
    if not smoke or not (smoke.get("passed") is True or smoke.get("smokePassed") is True):
        parser.error("smoke profile must be passed")
    stages = {
        "smoke": {"available": True, "passed": True, "sha256": file_hash(args.smoke), "data": smoke},
        "micro": artifact(args.micro),
        "full": artifact(args.full),
        "adapterFreeze": artifact(args.freeze, adapter_freeze_verified),
        "environment": artifact(args.environment, environment_verified),
        "formalEvaluation": artifact(args.evaluation),
        "blindReview": artifact(args.blind),
        "sealedTest": artifact(args.sealed),
        "coexistence": artifact(args.coexist),
        "publicSnapshot": artifact(args.public_snapshot),
        "releaseGate": artifact(args.release_gate),
    }
    result = {
        "schemaVersion": "yijian-submission-status-v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "project": "YIJIAN",
        "track": 2,
        "candidateModel": "Qwen3-14B + YIJIAN LoRA",
        "fallbackModel": "YIJIAN Qwen3.6-27B Go Coach",
        "baseRevision": "40c069824f4251a91eefaf281ebe4c544efd3e18",
        "data": {
            "gold": 64, "creatorTrain": 48, "creatorDev": 8, "creatorSealed": 8,
            "agentTrain": 720, "agentDev": 24, "agentSealed": 24,
            "agentTaskCounts": agent.get("taskCounts"),
            "agentManifestSha256": file_hash(args.agent_manifest),
        },
        "stages": stages,
        "competitionAlias": "yijian-lora" if stages["releaseGate"]["passed"] else "current-27b",
        "video": {"status": args.video_status, "scheduled": args.video_schedule},
        "presentation": {
            "status": args.presentation_status,
            "scheduled": args.presentation_schedule,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)
    print(json.dumps({"competitionAlias": result["competitionAlias"], "availableStages": [name for name, value in stages.items() if value["available"]]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
