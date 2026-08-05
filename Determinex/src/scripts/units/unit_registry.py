"""
Controlled registry for trained specialist units.

Units move through a strict lifecycle:
candidate -> trained -> evaluated -> safety_checked -> deployed -> retired

Deployment is allowed only when eval, safety, and license locks exist.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

_STATUS_ORDER = ["candidate", "trained", "evaluated", "safety_checked", "deployed", "retired"]


@dataclass
class UnitSpec:
    unit_id: str
    specialty: str
    model: str
    training_corpus: list[str]
    eval_lock: str
    safety_lock: str
    license_clearance: str
    status: str = "candidate"
    allowed_tasks: list[str] = field(default_factory=list)
    blocked_tasks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class UnitRegistry:
    def __init__(self, registry_path: Path, lock_dir: Path):
        self.registry_path = registry_path
        self.lock_dir = lock_dir
        self.units: dict[str, UnitSpec] = {}
        self.load()

    def load(self) -> None:
        if not self.registry_path.is_file():
            self.units = {}
            return
        data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.units = {item["unit_id"]: UnitSpec(**item) for item in data.get("units", [])}

    def save(self) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "units": [
                unit.to_dict() for unit in sorted(self.units.values(), key=lambda u: u.unit_id)
            ]
        }
        self.registry_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )

    def register(self, unit: UnitSpec) -> None:
        if unit.unit_id in self.units:
            raise ValueError(f"unit already exists: {unit.unit_id}")
        self._validate_status(unit.status)
        self.units[unit.unit_id] = unit
        self.save()

    def promote(self, unit_id: str, new_status: str) -> UnitSpec:
        self._validate_status(new_status)
        unit = self.units[unit_id]
        old_idx = _STATUS_ORDER.index(unit.status)
        new_idx = _STATUS_ORDER.index(new_status)
        if new_idx < old_idx:
            raise ValueError("status regression is not allowed")
        unit.status = new_status
        self.save()
        return unit

    def can_deploy(self, unit_id: str) -> tuple[bool, str]:
        unit = self.units[unit_id]
        if unit.status != "safety_checked":
            return False, f"status_not_safety_checked:{unit.status}"
        for lock_name in (unit.eval_lock, unit.safety_lock, unit.license_clearance):
            if not (self.lock_dir / lock_name).is_file():
                return False, f"missing_lock:{lock_name}"
        if not unit.training_corpus:
            return False, "missing_training_corpus"
        if not unit.allowed_tasks:
            return False, "missing_allowed_tasks"
        return True, "ok"

    def deploy(self, unit_id: str) -> UnitSpec:
        ok, reason = self.can_deploy(unit_id)
        if not ok:
            raise ValueError(reason)
        return self.promote(unit_id, "deployed")

    def route(self, task_type: str) -> list[UnitSpec]:
        return [
            unit
            for unit in self.units.values()
            if unit.status == "deployed"
            and task_type in unit.allowed_tasks
            and task_type not in unit.blocked_tasks
        ]

    @staticmethod
    def _validate_status(status: str) -> None:
        if status not in _STATUS_ORDER:
            raise ValueError(f"invalid unit status: {status}")
