# -*- coding: utf-8 -*-
"""Consolidate immutable evidence before the competition model alias may move."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


SCHEMA = "yijian-award-release-gate-v2"
EXPECTED_REVISION = "40c069824f4251a91eefaf281ebe4c544efd3e18"
EXPECTED_TASK_COUNTS = {
    "planner": 216,
    "answer": 288,
    "followup": 144,
    "memory_privacy": 72,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_hash(path: Path) -> str:
    digest = hashlib.sha256()
    # Keep this byte-for-byte compatible with freeze_lora_adapter.tree_hash.
    # Native Path ordering is platform-dependent (notably for case on
    # Windows), which can reject an unchanged adapter frozen on Linux.
    files = sorted(
        (item for item in path.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(path).as_posix().encode("utf-8"),
    )
    for item in files:
        relative = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(item)))
    return digest.hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"{path} 顶层必须是对象")
    return value


def build_release(
    *,
    agent: dict[str, Any],
    smoke: dict[str, Any],
    micro: dict[str, Any],
    full: dict[str, Any],
    evaluation: dict[str, Any],
    blind: dict[str, Any],
    sealed: dict[str, Any],
    coexist: dict[str, Any],
    public_snapshot: dict[str, Any],
    freeze: dict[str, Any],
    adapter_dir: Path,
) -> dict[str, Any]:
    adapter_tree = tree_hash(adapter_dir) if adapter_dir.is_dir() else None
    micro_learning = micro.get("learningProof") or {}
    full_dev = full.get("devLearningProof") or {}
    full_tasks = full.get("devTaskLearningProof") or {}
    task_values = (full_tasks.get("tasks") or {}).values()
    profile_reports = coexist.get("profileReports") or []
    valid_profiles = [
        row for row in profile_reports
        if row.get("passed") is True
        and int(row.get("cycles") or 0) >= 30
        and float(((row.get("combined") or {}).get("p95Seconds") or 999)) <= 12
        and int(row.get("oomCount") or 0) == 0
    ]
    gates = {
        "agent720": (
            agent.get("passed") is True
            and (agent.get("counts") or {}).get("train") == 720
            and agent.get("taskCounts") == EXPECTED_TASK_COUNTS
        ),
        "smokeFourStepsUnder45GiB": (
            (smoke.get("passed") is True or smoke.get("smokePassed") is True)
            and int(smoke.get("optimizerSteps") or 4) == 4
            and float(smoke.get("peakReservedGiB") or 999) <= 45
        ),
        "microThirtyStepsAndFivePercent": (
            micro.get("passed") is True
            and int(micro.get("optimizerSteps") or 0) == 30
            and micro_learning.get("lossDropped") is True
            and float(micro_learning.get("relativeLossDrop") or 0) >= .05
            and float(micro.get("peakReservedGiB") or 999) <= 45
        ),
        "fullTwoEpochsNinetySteps": (
            full.get("passed") is True
            and abs(float(full.get("completedEpochs") or 0) - 2.0) <= 1e-6
            and int(full.get("optimizerSteps") or 0) == 90
            and float(full.get("peakReservedGiB") or 999) <= 45
        ),
        "fullDevImproved": (
            full_dev.get("lossDropped") is True
            and int(full_tasks.get("improvedTaskCount") or 0) >= 2
            and bool(list(task_values))
            and not any(row.get("regressedMoreThanTenPercent") for row in task_values)
        ),
        "adapterFrozen": (
            adapter_tree is not None
            and (adapter_dir / "adapter_config.json").is_file()
            and freeze.get("frozen") is True
            and freeze.get("baseRevision") == EXPECTED_REVISION
            and freeze.get("adapterTreeSha256") == adapter_tree
        ),
        "formalEvaluation": evaluation.get("passed") is True,
        "blindReview": blind.get("passed") is True,
        "sealedOnceAfterFreeze": (
            sealed.get("passed") is True
            and sealed.get("accessedAfterAdapterFreeze") is True
            and int(sealed.get("cases") or 0) == 8
            and int(sealed.get("severeContradictions") or 0) == 0
            and float(sealed.get("meanTeachingQuality") or 0) >= 4
        ),
        "coexistMatrix": (
            coexist.get("passed") is True
            and bool(coexist.get("passingProfiles"))
            and bool(valid_profiles)
        ),
        "publicSnapshot": (
            public_snapshot.get("passed") is True
            and int(public_snapshot.get("secretFindings") or 0) == 0
            and int(public_snapshot.get("privateDataFindings") or 0) == 0
        ),
    }
    return {
        "schemaVersion": SCHEMA,
        "passed": all(gates.values()),
        "maySwitchCompetitionAlias": all(gates.values()),
        "fallbackModel": "Yijian-Qwen3.6-27B-GoCoach",
        "candidateModel": "yijian-lora",
        "candidateDisplayName": "弈鉴 LoRA",
        "gates": gates,
        "adapterTreeSha256": adapter_tree,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-manifest", type=Path, required=True)
    parser.add_argument("--smoke-profile", type=Path, required=True)
    parser.add_argument("--learning-profile", type=Path, required=True)
    parser.add_argument("--full-metrics", type=Path, required=True)
    parser.add_argument("--adapter-dir", type=Path, required=True)
    parser.add_argument("--adapter-freeze-manifest", type=Path, required=True)
    parser.add_argument("--eval-manifest", type=Path, required=True)
    parser.add_argument("--blind-result", type=Path, required=True)
    parser.add_argument("--sealed-result", type=Path, required=True)
    parser.add_argument("--coexist-summary", type=Path, required=True)
    parser.add_argument("--public-snapshot-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    inputs = {
        "agent": read(args.agent_manifest),
        "smoke": read(args.smoke_profile),
        "learning": read(args.learning_profile),
        "full": read(args.full_metrics),
        "evaluation": read(args.eval_manifest),
        "blind": read(args.blind_result),
        "sealed": read(args.sealed_result),
        "coexist": read(args.coexist_summary),
        "public": read(args.public_snapshot_result),
        "freeze": read(args.adapter_freeze_manifest),
    }
    artifact_paths = {
        "agentManifest": args.agent_manifest,
        "smokeProfile": args.smoke_profile,
        "learningProfile": args.learning_profile,
        "fullMetrics": args.full_metrics,
        "evalManifest": args.eval_manifest,
        "blindResult": args.blind_result,
        "sealedResult": args.sealed_result,
        "coexistSummary": args.coexist_summary,
        "publicSnapshotResult": args.public_snapshot_result,
        "adapterFreezeManifest": args.adapter_freeze_manifest,
    }
    result = build_release(
        agent=inputs["agent"], smoke=inputs["smoke"], micro=inputs["learning"],
        full=inputs["full"], evaluation=inputs["evaluation"], blind=inputs["blind"],
        sealed=inputs["sealed"], coexist=inputs["coexist"],
        public_snapshot=inputs["public"], freeze=inputs["freeze"],
        adapter_dir=args.adapter_dir.resolve(),
    )
    result.update({
        "artifacts": {name: sha256_file(path) for name, path in artifact_paths.items()},
    })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 4)


if __name__ == "__main__":
    main()
