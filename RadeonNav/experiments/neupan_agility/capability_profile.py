#!/usr/bin/env python3
"""NAG-801 part 1: capability profile derived from archived evaluations.

Turns the stage-A capability matrix from hand-curated knowledge into a
machine-readable routing profile: per affordance class, goal-reaching
success and traversal speed measured from archived result JSONs. Routing
semantics: success below 0.5 -> IMPASSABLE (treated as solid obstacle);
otherwise a traversal cost multiplier free_speed / class_speed >= 1.

Honest scope: single-seed nominal-mu evidence (n=1 per class, demo
criterion = goal reached), recorded verbatim in `source_runs`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "experiment-results/quadrupedal-agility"
CTRL_DT = 0.02
STAIRS_ROUTING_CLASS = 6  # routing-only region id; TSC still sees frame(1)

# class -> (name, run dir, reached-step field, course distance in metres).
# Distances are the archived start->final-goal waypoint-chain lengths
# (metrics.start_xy_m to contracts.goals[-1], via intermediate goals for
# poles), audit-corrected 2026-07-31 per NAG-801 independent review.
# Note on the stairs source: all NAG-701-STAIRS result.json files carry a
# stale contracts.stairs string claiming riser 0.10; fragment_sha256 proves
# ft1_r005 ran assets/stairs.xml (riser 0.05). See tracker NAG-801 entry.
SOURCES: dict[int, tuple[str, str, str, float]] = {
    0: ("bar", "NAG-210B-S16-WY-GO-FT1", "reached_final_step", 2.7),
    2: ("poles", "NAG-210P-S16-WY-GO-FT1", "reached_final_step", 4.24),
    3: ("seesaw", "NAG-210S-S16-WY-GO-FT1", "reached_final_step", 3.7),
    4: ("tire", "NAG-210R-S16-WY-GO-FT1", "reached_final_step", 2.7),
    5: ("tunnel", "NAG-210T-S16-WY-GO-FT1", "reached_final_step", 3.5),
    6: ("stairs", "NAG-701-STAIRS/ft1_r005", "reached_step", 6.0),
}
FREE_SOURCE = (1, "frame", "NAG-210F-S16-WY-GO-FT1", "reached_final_step", 3.6)


@dataclass(frozen=True)
class ClassCapability:
    name: str
    success_rate: float
    traversal_speed_mps: float | None
    verdict: str  # TRAVERSABLE | IMPASSABLE
    cost_multiplier: float | None
    source_runs: tuple[dict, ...]


@dataclass(frozen=True)
class CapabilityProfile:
    free_space_class: int
    free_speed_mps: float
    classes: dict[int, ClassCapability]

    def is_impassable(self, label: int) -> bool:
        entry = self.classes.get(label)
        return entry is not None and entry.verdict == "IMPASSABLE"

    def cost_multiplier(self, label: int) -> float:
        entry = self.classes.get(label)
        if entry is None or entry.cost_multiplier is None:
            return 1.0
        return entry.cost_multiplier


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_run(run_dir: str, reached_field: str, distance_m: float) -> dict:
    path = RESULTS / run_dir / "result.json"
    payload = json.loads(path.read_text())
    reached = payload["metrics"].get(reached_field)
    speed = (
        distance_m / (reached * CTRL_DT)
        if reached is not None and reached > 0
        else None
    )
    return {
        "run_dir": run_dir,
        "result_sha256": _sha256(path),
        "run_id": payload.get("run_id"),
        # The archived run's own strict verdict (may be FAILED on contact
        # gates while the goal was still reached — disclosed, not hidden).
        "source_status": payload.get("status"),
        "reached_step": reached,
        "distance_m": distance_m,
        "speed_mps": speed,
        "criterion": "goal reached (demo scope)",
    }


def build_profile() -> CapabilityProfile:
    _, free_name, free_dir, free_field, free_dist = FREE_SOURCE
    free = _load_run(free_dir, free_field, free_dist)
    if free["speed_mps"] is None:
        raise RuntimeError(f"free-space source {free_name} did not reach goal")
    free_speed = float(free["speed_mps"])
    classes: dict[int, ClassCapability] = {
        FREE_SOURCE[0]: ClassCapability(
            name=free_name,
            success_rate=1.0,
            traversal_speed_mps=free_speed,
            verdict="TRAVERSABLE",
            cost_multiplier=1.0,
            source_runs=(free,),
        )
    }
    for label, (name, run_dir, field, distance) in SOURCES.items():
        run = _load_run(run_dir, field, distance)
        success = 1.0 if run["reached_step"] is not None else 0.0
        if success < 0.5:
            entry = ClassCapability(name, success, None, "IMPASSABLE", None, (run,))
        else:
            speed = float(run["speed_mps"])
            entry = ClassCapability(
                name,
                success,
                speed,
                "TRAVERSABLE",
                max(free_speed / speed, 1.0),
                (run,),
            )
        classes[label] = entry
    return CapabilityProfile(
        free_space_class=FREE_SOURCE[0], free_speed_mps=free_speed, classes=classes
    )


def profile_to_json(profile: CapabilityProfile) -> dict:
    return {
        "free_space_class": profile.free_space_class,
        "free_speed_mps": profile.free_speed_mps,
        "classes": {str(k): asdict(v) for k, v in profile.classes.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=RESULTS / "NAG-801" / "capability_profile.json",
    )
    args = parser.parse_args()
    profile = build_profile()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(profile_to_json(profile), indent=2))
    for label, entry in sorted(profile.classes.items()):
        print(
            f"class {label} {entry.name}: {entry.verdict}"
            f" success={entry.success_rate}"
            f" speed={entry.traversal_speed_mps}"
            f" cost={entry.cost_multiplier}"
        )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
