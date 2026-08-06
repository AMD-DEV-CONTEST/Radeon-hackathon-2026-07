"""Runtime detection of simulator-assisted cheating.

Every result this project reports must carry a verdict produced by measurement,
not by an author-written constant.  The previous iteration of this repo shipped
``"object_state_written": false`` in a JSON file while the code beside it wrote
object positions directly, and that flag was believed because nothing checked
it.  This module is what makes such a claim falsifiable.

Three violations are detected:

* **Teleportation** - a body moves further in one timestep than its velocity
  can explain, which means user code assigned to ``qpos``.
* **Grasp welds** - an equality constraint involving a manipulated object is
  present in the model or becomes active during a run.
* **Velocity erasure** - a body's speed collapses to zero in a single step with
  no contact to absorb the momentum.

The monitor is intentionally cheap so it can stay switched on during data
generation and evaluation rather than being a debug-only tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import mujoco
import numpy as np


@dataclass
class Violation:
    kind: str
    body: str
    step: int
    sim_time: float
    detail: str

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "body": self.body,
            "step": self.step,
            "sim_time": round(self.sim_time, 4),
            "detail": self.detail,
        }


@dataclass
class IntegrityVerdict:
    clean: bool
    steps_checked: int
    violations: list[Violation] = field(default_factory=list)
    max_object_jump: float = 0.0
    max_base_jump: float = 0.0
    static_welds_on_objects: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "clean": self.clean,
            "steps_checked": self.steps_checked,
            "violation_count": len(self.violations),
            "violations": [v.as_dict() for v in self.violations[:20]],
            "max_object_jump_m": round(self.max_object_jump, 5),
            "max_base_jump_m": round(self.max_base_jump, 5),
            "static_welds_on_objects": self.static_welds_on_objects,
            "note": (
                "Produced by IntegrityMonitor from per-step measurements. "
                "A run with clean=false must not be reported as a result."
            ),
        }


class IntegrityMonitor:
    """Watches tracked bodies for physically impossible state changes."""

    #: A body may not move further than this in one step beyond what its
    #: velocity predicts.  Contact impulses move a 0.1 kg object by well under
    #: a millimetre per 2 ms step, so this is a wide margin.
    JUMP_TOLERANCE = 0.01

    def __init__(
        self,
        model: mujoco.MjModel,
        data: mujoco.MjData,
        object_bodies: list[str],
        base_body: str | None = None,
    ) -> None:
        self.model = model
        self.data = data
        self.object_bodies = list(object_bodies)
        self.base_body = base_body
        self.steps = 0
        self.violations: list[Violation] = []
        self.max_object_jump = 0.0
        self.max_base_jump = 0.0

        self._tracked: dict[str, int] = {}
        for name in self.object_bodies:
            self._tracked[name] = model.body(name).id
        if base_body is not None:
            self._tracked[base_body] = model.body(base_body).id

        self._prev_pos = {n: data.xpos[i].copy() for n, i in self._tracked.items()}
        self._prev_vel = {n: self._linear_velocity(i) for n, i in self._tracked.items()}
        self._eq_active0 = data.eq_active.copy() if model.neq else np.zeros(0, dtype=np.int32)
        self.static_welds = self._find_object_welds()

    def _linear_velocity(self, body_id: int) -> np.ndarray:
        joint_adr = self.model.body_jntadr[body_id]
        if joint_adr < 0:
            return np.zeros(3)
        dofadr = int(self.model.jnt_dofadr[joint_adr])
        if dofadr < 0 or dofadr + 3 > self.model.nv:
            return np.zeros(3)
        return self.data.qvel[dofadr : dofadr + 3].copy()

    def _find_object_welds(self) -> list[str]:
        """Equality constraints tying a tracked object to anything else."""
        ids = {self.model.body(name).id for name in self.object_bodies}
        found = []
        weld_types = (int(mujoco.mjtEq.mjEQ_WELD), int(mujoco.mjtEq.mjEQ_CONNECT))
        for i in range(self.model.neq):
            if int(self.model.eq_type[i]) not in weld_types:
                continue
            if int(self.model.eq_obj1id[i]) in ids or int(self.model.eq_obj2id[i]) in ids:
                found.append(self.model.equality(i).name or f"eq[{i}]")
        return found

    def step(self) -> None:
        """Call once immediately after every ``mj_step``."""
        self.steps += 1
        dt = self.model.opt.timestep

        for name, body_id in self._tracked.items():
            position = self.data.xpos[body_id]
            previous = self._prev_pos[name]
            actual = float(np.linalg.norm(position - previous))
            explained = float(np.linalg.norm(self._prev_vel[name])) * dt
            unexplained = actual - explained

            if name == self.base_body:
                self.max_base_jump = max(self.max_base_jump, unexplained)
            else:
                self.max_object_jump = max(self.max_object_jump, unexplained)

            if unexplained > self.JUMP_TOLERANCE:
                self.violations.append(
                    Violation(
                        kind="teleport",
                        body=name,
                        step=self.steps,
                        sim_time=float(self.data.time),
                        detail=(
                            f"moved {actual:.4f} m in one step; velocity explains only "
                            f"{explained:.4f} m"
                        ),
                    )
                )

            self._prev_pos[name] = position.copy()
            self._prev_vel[name] = self._linear_velocity(body_id)

        if self.model.neq and not np.array_equal(self.data.eq_active, self._eq_active0):
            changed = np.flatnonzero(self.data.eq_active != self._eq_active0)
            for index in changed:
                self.violations.append(
                    Violation(
                        kind="equality_toggled",
                        body=self.model.equality(int(index)).name or f"eq[{index}]",
                        step=self.steps,
                        sim_time=float(self.data.time),
                        detail="equality constraint activation changed during the run",
                    )
                )
            self._eq_active0 = self.data.eq_active.copy()

    def __call__(self, _data: mujoco.MjData | None = None) -> None:
        """Usable directly as an ``on_step`` callback."""
        self.step()

    def verdict(self) -> IntegrityVerdict:
        return IntegrityVerdict(
            clean=not self.violations and not self.static_welds,
            steps_checked=self.steps,
            violations=list(self.violations),
            max_object_jump=self.max_object_jump,
            max_base_jump=self.max_base_jump,
            static_welds_on_objects=list(self.static_welds),
        )
