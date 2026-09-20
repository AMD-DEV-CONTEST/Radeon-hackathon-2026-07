"""Build and validate fail-closed replay plans from physics preflight results.

The formal renderer must not discover replay failures after spending minutes on
three high-resolution cameras.  A replay plan is a small, auditable manifest of
demo UUIDs that already passed the task's unmodified ``env.reward`` predicate
on the exact runtime and control frequency used for collection.
"""

from __future__ import annotations

import json
from pathlib import Path


SCHEMA_VERSION = 1
CANONICAL_ACTION_REPRESENTATION = "absolute"
CURRENT_20HZ_MODES = ("absolute_current_20", "delta_current_20")


def _read_json(path: str | Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def build_replay_plan(
    compatibility_report: dict,
    requested: dict[str, int],
    *,
    allowed_modes: tuple[str, ...] = CURRENT_20HZ_MODES,
) -> dict:
    """Select distinct successful UUIDs without mixing action-label semantics."""

    report_tasks = compatibility_report.get("tasks", {})
    if not isinstance(report_tasks, dict):
        raise ValueError("compatibility report has no tasks object")
    if not requested:
        raise ValueError("at least one requested task is required")

    plan_tasks: dict[str, dict] = {}
    all_ready = True
    for task, amount in requested.items():
        if not isinstance(amount, int) or amount < 1:
            raise ValueError(f"{task}: requested amount must be a positive integer")
        task_report = report_tasks.get(task)
        if not isinstance(task_report, dict):
            raise ValueError(f"compatibility report is missing task: {task}")
        successful = task_report.get("successful_by_uuid", {})
        if not isinstance(successful, dict):
            raise ValueError(f"{task}: successful_by_uuid must be an object")

        candidates: list[dict] = []
        for demo_uuid, verified_modes in sorted(successful.items()):
            modes = set(verified_modes)
            selected_mode = next(
                (mode for mode in allowed_modes if mode in modes),
                None,
            )
            if selected_mode is None:
                continue
            representation = selected_mode.split("_", 1)[0]
            candidates.append(
                {
                    "demo_uuid": demo_uuid,
                    "source_action_representation": representation,
                    "verified_mode": selected_mode,
                    "control_frequency_hz": 20,
                }
            )

        selected = candidates[:amount]
        available = len(candidates)
        ready = available >= amount
        all_ready = all_ready and ready
        plan_tasks[task] = {
            "requested": amount,
            "available": available,
            "shortfall": max(amount - available, 0),
            "status": "ready" if ready else "insufficient_successful_demos",
            "episodes": selected,
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ready" if all_ready else "blocked_insufficient_successful_demos",
        "runtime": "current",
        "control_frequency_hz": 20,
        "dataset_action_representation": CANONICAL_ACTION_REPRESENTATION,
        "allowed_verified_modes": list(allowed_modes),
        "tasks": plan_tasks,
    }


def write_replay_plan(path: str | Path, plan: dict) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination


def filter_canonical_verified_plan(
    replay_plan: dict,
    verification_report: dict,
    *,
    replay_plan_sha256: str,
) -> dict:
    """Return a ready subset containing only canonical-replay successes.

    The physics verifier intentionally records all failures instead of stopping
    on the first one.  This function makes those exclusions explicit and
    refuses partial or stale reports, so rendering cannot accidentally consume
    an unverified UUID.
    """

    if verification_report.get("replay_plan_sha256") != replay_plan_sha256:
        raise ValueError("verification report does not match replay plan SHA-256")
    rows = verification_report.get("episodes")
    if not isinstance(rows, list):
        raise ValueError("verification report has no episodes list")
    verified = {}
    for row in rows:
        key = (str(row.get("task")), str(row.get("demo_uuid")))
        if not all(key) or key in verified:
            raise ValueError("verification report has duplicate or missing UUIDs")
        verified[key] = row

    filtered_tasks = {}
    all_ready = True
    for task, task_plan in replay_plan["tasks"].items():
        kept = []
        excluded = []
        for episode in task_plan.get("episodes", []):
            key = (task, str(episode.get("demo_uuid")))
            if key not in verified:
                raise ValueError(f"verification report is incomplete for {task}/{key[1]}")
            row = verified[key]
            if row.get("passed") is True:
                kept.append(episode)
            else:
                excluded.append(
                    {
                        "demo_uuid": key[1],
                        "source_reward": row.get("source_reward"),
                        "canonical_absolute_reward": row.get(
                            "canonical_absolute_reward"
                        ),
                        "max_qpos_error": row.get("max_qpos_error"),
                    }
                )
        ready = bool(kept)
        all_ready = all_ready and ready
        filtered_tasks[task] = {
            "requested": len(kept),
            "available": len(kept),
            "shortfall": 0,
            "status": "ready" if ready else "no_canonical_verified_demos",
            "preverification_requested": task_plan.get("requested"),
            "canonical_excluded": excluded,
            "episodes": kept,
        }

    return {
        **replay_plan,
        "status": "ready" if all_ready else "blocked_no_canonical_verified_demos",
        "canonical_verification": {
            "replay_plan_sha256": replay_plan_sha256,
            "report_status": verification_report.get("status"),
            "failed_replays": verification_report.get("failed_replays", []),
        },
        "tasks": filtered_tasks,
    }


def load_replay_plan(
    path: str | Path,
    *,
    expected_tasks: list[str] | tuple[str, ...] | None = None,
    require_ready: bool = True,
) -> dict:
    """Load a plan and reject stale, partial, duplicate, or mixed-rate input."""

    plan = _read_json(path)
    if plan.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported replay-plan schema_version")
    if plan.get("runtime") != "current":
        raise ValueError("formal collection requires a current-runtime replay plan")
    if plan.get("control_frequency_hz") != 20:
        raise ValueError("formal collection requires a 20 Hz replay plan")
    if plan.get("dataset_action_representation") != CANONICAL_ACTION_REPRESENTATION:
        raise ValueError("dataset actions must use the canonical absolute representation")
    if require_ready and plan.get("status") != "ready":
        raise ValueError(
            "replay plan is not ready: "
            f"{plan.get('status', 'missing status')}"
        )

    tasks = plan.get("tasks")
    if not isinstance(tasks, dict) or not tasks:
        raise ValueError("replay plan has no tasks")
    if expected_tasks is not None and set(tasks) != set(expected_tasks):
        raise ValueError(
            "replay-plan tasks do not match collection tasks: "
            f"{sorted(tasks)} != {sorted(expected_tasks)}"
        )

    seen: set[tuple[str, str]] = set()
    for task, task_plan in tasks.items():
        if not isinstance(task_plan, dict):
            raise ValueError(f"{task}: invalid task plan")
        episodes = task_plan.get("episodes", [])
        if require_ready and len(episodes) != task_plan.get("requested"):
            raise ValueError(f"{task}: replay plan does not satisfy requested count")
        for episode in episodes:
            representation = episode.get("source_action_representation")
            if representation not in {"absolute", "delta"}:
                raise ValueError(f"{task}: invalid source action representation")
            if episode.get("control_frequency_hz") != 20:
                raise ValueError(f"{task}: episode is not verified at 20 Hz")
            key = (task, str(episode.get("demo_uuid")))
            if not key[1] or key in seen:
                raise ValueError(f"{task}: duplicate or missing demo UUID")
            seen.add(key)
    return plan


def plan_entries(plan: dict, task: str) -> list[dict]:
    return list(plan["tasks"][task]["episodes"])


def select_replay_plan_tasks(replay_plan: dict, tasks: list[str]) -> dict:
    """Extract an exact-task plan while retaining verification provenance."""

    if not tasks or len(set(tasks)) != len(tasks):
        raise ValueError("tasks must be a non-empty distinct list")
    missing = [task for task in tasks if task not in replay_plan["tasks"]]
    if missing:
        raise ValueError(f"replay plan is missing tasks: {missing}")
    selected = {task: replay_plan["tasks"][task] for task in tasks}
    status = (
        "ready"
        if all(task_plan.get("status") == "ready" for task_plan in selected.values())
        else "blocked_selected_tasks_not_ready"
    )
    return {**replay_plan, "status": status, "tasks": selected}


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--compatibility-report", required=True)
    parser.add_argument(
        "--request",
        action="append",
        required=True,
        metavar="TASK=COUNT",
        help="requested successful episodes; repeat for multiple tasks",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    requested: dict[str, int] = {}
    for item in args.request:
        try:
            task, amount = item.rsplit("=", 1)
            requested[task] = int(amount)
        except (ValueError, TypeError) as exc:
            parser.error(f"invalid --request {item!r}: {exc}")
    report = _read_json(args.compatibility_report)
    plan = build_replay_plan(report, requested)
    write_replay_plan(args.output, plan)
    for task, task_plan in plan["tasks"].items():
        print(
            f"{task}: requested={task_plan['requested']} "
            f"available={task_plan['available']} "
            f"shortfall={task_plan['shortfall']}"
        )
    print(f"status={plan['status']} output={args.output}")
    return 0 if plan["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
