"""Static and runtime guards for the sensor-only, no-IK contract."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import mujoco


FORBIDDEN_SOURCE_PATTERNS = {
    "IK/Jacobian": re.compile(
        r"\bmj_jac\w*\b|\bsolve_topdown\b|\binverse[_ ]?kinematics\b|\bsolve_\w*ik\b",
        re.IGNORECASE,
    ),
    "direct qpos write": re.compile(r"(?:\bdata|\bself\.data)\.qpos\s*\[[^\n]+\]\s*="),
    "direct qvel write": re.compile(r"(?:\bdata|\bself\.data)\.qvel\s*\[[^\n]+\]\s*="),
    "equality activation": re.compile(r"\.eq_active\s*\["),
    "legacy controller import": re.compile(
        r"(?:from|import)\s+(?:cleanup_robot|stretch_cleanup\.(?:robot|grasp|mission|planner))"
    ),
}


@dataclass(frozen=True)
class SourceViolation:
    path: str
    line: int
    rule: str
    text: str


def audit_source_tree(paths: list[Path]) -> list[SourceViolation]:
    violations: list[SourceViolation] = []
    for root in paths:
        candidates = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in candidates:
            if path.name == "integrity.py":
                continue
            text = path.read_text(encoding="utf-8")
            for line_number, line in enumerate(text.splitlines(), start=1):
                for rule, pattern in FORBIDDEN_SOURCE_PATTERNS.items():
                    if pattern.search(line):
                        violations.append(
                            SourceViolation(
                                path=str(path),
                                line=line_number,
                                rule=rule,
                                text=line.strip(),
                            )
                        )
    return violations


def assert_clean_source(paths: list[Path]) -> None:
    violations = audit_source_tree(paths)
    if violations:
        rendered = "\n".join(
            f"{item.path}:{item.line}: {item.rule}: {item.text}" for item in violations
        )
        raise RuntimeError(f"realtime source integrity failed:\n{rendered}")


def assert_no_object_constraints(model: mujoco.MjModel, object_names: list[str]) -> None:
    object_ids = {model.body(name).id for name in object_names}
    forbidden_types = {int(mujoco.mjtEq.mjEQ_WELD), int(mujoco.mjtEq.mjEQ_CONNECT)}
    for equality_id in range(model.neq):
        if int(model.eq_type[equality_id]) not in forbidden_types:
            continue
        if (
            int(model.eq_obj1id[equality_id]) in object_ids
            or int(model.eq_obj2id[equality_id]) in object_ids
        ):
            name = model.equality(equality_id).name
            raise RuntimeError(f"object weld/connect is forbidden: {name}")


def lock_python_state_writes(data: mujoco.MjData) -> None:
    """Block Python qpos/qvel assignment after episode initialization."""

    data.qpos.flags.writeable = False
    data.qvel.flags.writeable = False


def assert_state_write_lock(data: mujoco.MjData) -> None:
    if data.qpos.flags.writeable or data.qvel.flags.writeable:
        raise RuntimeError("qpos/qvel Python write lock is not active")
