from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.v10_agency_trajectory_corpus import TARGET_OUTCOME_COUNTS  # noqa: E402
from prooflaunch_remix.v10_sft_corpus import stable_sha256  # noqa: E402


def main() -> int:
    root = ROOT / "data/v10_agency_trajectories"
    trajectories = [json.loads(line) for line in (root / "trajectories.jsonl").read_text(encoding="utf-8").splitlines() if line]
    index = [json.loads(line) for line in (root / "trajectory-index.jsonl").read_text(encoding="utf-8").splitlines() if line]
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    upstream = [json.loads(line) for line in (ROOT / manifest["upstream_path"]).read_text(encoding="utf-8").splitlines() if line]
    failures: list[str] = []
    if trajectories[:456] != upstream:
        failures.append("reused_records_not_byte_semantic_equal")

    ids = [row["trajectory_id"] for row in trajectories]
    index_ids = [row["trajectory_id"] for row in index]
    if len(set(ids)) != 1_000 or set(ids) != set(index_ids):
        failures.append("trajectory_identity_or_index_mismatch")
    by_id = {row["trajectory_id"]: row for row in trajectories}
    split_by_group: dict[str, set[str]] = defaultdict(set)
    for row in index:
        split_by_group[row["source_group_id"]].add(row["corpus_split"])
    if any(len(splits) != 1 for splits in split_by_group.values()):
        failures.append("source_group_split_leakage")

    event_count = 0
    generated_replay_count = 0
    for trajectory_id in ids:
        row = by_id[trajectory_id]
        events = row.get("events", [])
        event_count += len(events)
        if [event.get("step_index") for event in events] != list(range(len(events))):
            failures.append(f"noncontiguous:{trajectory_id}")
        if not events or not events[-1].get("terminal") or not events[-1].get("terminal_signal"):
            failures.append(f"missing_terminal:{trajectory_id}")
        if any(event.get("terminal") for event in events[:-1]):
            failures.append(f"early_terminal:{trajectory_id}")
        if any(event.get("next_observation_sha256") != events[i + 1].get("observation_sha256") for i, event in enumerate(events[:-1])):
            failures.append(f"broken_chain:{trajectory_id}")
        if row.get("hidden_chain_of_thought_present"):
            failures.append(f"hidden_reasoning:{trajectory_id}")
        if row.get("schema") == "ProofLaunchSourceBoundAgencyTrajectoryV2":
            generated_replay_count += 1
            if not row.get("rights_verified") or not row.get("training_allowed"):
                failures.append(f"rights:{trajectory_id}")
            for event in events:
                checks = {
                    "observation_sha256": stable_sha256(event["observation"]),
                    "action_sha256": stable_sha256(event["action"]),
                    "tool_response_sha256": stable_sha256(event["tool_response"]),
                    "next_observation_sha256": stable_sha256(event["next_observation"]),
                }
                if any(event[key] != expected for key, expected in checks.items()):
                    failures.append(f"event_replay_hash:{trajectory_id}:{event['step_index']}")
            if row["trace_sha256"] != stable_sha256(events):
                failures.append(f"trace_hash:{trajectory_id}")
            material = dict(row)
            digest = material.pop("content_sha256")
            if digest != stable_sha256(material):
                failures.append(f"content_hash:{trajectory_id}")

    observed = {
        "trajectory_count": len(trajectories),
        "reused_existing_count": sum(row["source_kind"] == "reused_verified_v1" for row in index),
        "newly_constructed_count": sum(row["source_kind"] == "source_bound_v2" for row in index),
        "train_count": sum(row["corpus_split"] == "train" for row in index),
        "validation_count": sum(row["corpus_split"] == "validation" for row in index),
        "outcome_counts": dict(sorted(Counter(row["outcome_kind"] for row in trajectories).items())),
        "event_count": event_count,
        "generated_replay_count": generated_replay_count,
        "unique_trace_count": len({row["trace_sha256"] for row in trajectories}),
        "outcome_kind_count": len({row["outcome_kind"] for row in trajectories}),
    }
    exact = {
        "trajectory_count": 1_000,
        "reused_existing_count": 456,
        "newly_constructed_count": 544,
        "train_count": 900,
        "validation_count": 100,
        "outcome_counts": dict(TARGET_OUTCOME_COUNTS),
        "generated_replay_count": 544,
        "unique_trace_count": 1_000,
        "outcome_kind_count": 6,
    }
    for key, expected in exact.items():
        if observed[key] != expected or manifest.get(key) != expected and key in manifest:
            failures.append(f"recount:{key}")
    trajectory_bytes = (root / "trajectories.jsonl").read_bytes()
    index_bytes = (root / "trajectory-index.jsonl").read_bytes()
    if hashlib.sha256(trajectory_bytes).hexdigest() != manifest["trajectory_file_sha256"]:
        failures.append("trajectory_file_hash")
    if hashlib.sha256(index_bytes).hexdigest() != manifest["index_file_sha256"]:
        failures.append("index_file_hash")

    report = {
        "schema": "ProofLaunchAgencyTrajectoryIndependentReplayAuditV2",
        "status": "passed_exact_1000_visible_replay_not_training" if not failures else "failed",
        **observed,
        "group_safe_split": not any("split_leakage" in item for item in failures),
        "all_generated_events_replayed": generated_replay_count == 544 and not any("hash:" in item for item in failures),
        "hidden_chain_of_thought_count": sum(bool(row.get("hidden_chain_of_thought_present")) for row in trajectories),
        "rights_failure_count": sum(not row.get("rights_verified", row.get("rights_id") == "project-owned-synthetic-v1") for row in trajectories),
        "model_teacher_used": False,
        "human_reviewed": False,
        "training_observed": False,
        "failure_count": len(failures),
        "failures": failures[:100],
        "manifest_sha256": manifest["manifest_sha256"],
    }
    output = ROOT / "evidence/v10/agency-trajectories-1000-independent-replay.json"
    atomic_write_text(output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
