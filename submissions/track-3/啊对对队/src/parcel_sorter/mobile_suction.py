"""Physical tri-cup suction controller for the mobile Bi-Franka left arm."""

from __future__ import annotations

import math
from typing import Any

from .suction import (
    SuctionAttachment,
    compliant_suction_wrench,
    create_attachment,
    inertia_scaled_rotational_gains,
    rotate_vector,
)


def discover_mobile_suction_cup_geoms(robot: Any) -> frozenset[int]:
    indices = frozenset(
        int(geom.idx)
        for link in robot.links
        for geom in link.geoms
        if "mobile_left_suction_cup_" in str(getattr(geom, "name", ""))
        and str(getattr(geom, "name", "")).endswith("_collision")
    )
    if len(indices) != 3:
        gripper = next(
            (
                link
                for link in robot.links
                if str(getattr(link, "name", "")) == "panda0_gripper"
            ),
            None,
        )
        collision_geoms = tuple(gripper.geoms) if gripper is not None else ()
        if len(collision_geoms) >= 3:
            indices = frozenset(int(geom.idx) for geom in collision_geoms[-3:])
    if len(indices) != 3:
        raise RuntimeError(
            f"expected three mobile suction cup collision geoms, got {len(indices)}"
        )
    return indices


class MobileTriSuctionController:
    """Latch on verified cup contacts and apply a bounded compliant wrench."""

    def __init__(
        self,
        *,
        robot: Any,
        hand: Any,
        parcel: Any,
        torch: Any,
        np: Any,
        min_sealed_cups: int = 2,
        force_limit_n: float = 30.0,
    ) -> None:
        if not 1 <= min_sealed_cups <= 3:
            raise ValueError("min_sealed_cups must be in [1, 3]")
        if not 0.0 < force_limit_n < 35.0:
            raise ValueError("suction force limit must be in (0, 35) N")
        self.robot = robot
        self.hand = hand
        self.parcel = parcel
        self.torch = torch
        self.np = np
        self.min_sealed_cups = min_sealed_cups
        self.force_limit_n = force_limit_n
        self.cup_geom_indices = discover_mobile_suction_cup_geoms(robot)
        self._ordered_cup_geom_indices = tuple(sorted(self.cup_geom_indices))
        self.attachment: SuctionAttachment | None = None
        self.latch_count = 0
        self.break_count = 0
        self.max_force_n = 0.0
        self.max_contact_force_n = 0.0
        self.last_sealed_cups = 0
        self.last_sealed_cup_mask = (False, False, False)
        self.last_attachment_position_error_m = 0.0
        self.last_attachment_orientation_error_rad = 0.0
        self.last_break_reason: str | None = None
        inertia_matrix = self.np.asarray(
            self.parcel.base_link.inertial_i,
            dtype=self.np.float64,
        )
        principal_inertias = self.np.linalg.eigvalsh(inertia_matrix)
        self.minimum_principal_inertia_kg_m2 = max(
            1e-8,
            float(self.np.min(principal_inertias)),
        )
        (
            self.rotational_stiffness_nm_rad,
            self.rotational_damping_nm_s_rad,
        ) = inertia_scaled_rotational_gains(
            self.minimum_principal_inertia_kg_m2,
        )

    def contact_snapshot(self) -> tuple[int, float]:
        contacts = self.robot.get_contacts(with_entity=self.parcel)
        geom_a = contacts["geom_a"]
        if geom_a.numel() == 0:
            self.last_sealed_cups = 0
            self.last_sealed_cup_mask = (False, False, False)
            return 0, 0.0
        geom_b = contacts["geom_b"]
        valid = contacts.get("valid_mask")
        forces = contacts["force_a"]
        sealed: set[int] = set()
        mask = self.torch.zeros_like(geom_a, dtype=self.torch.bool)
        for geom_index in self.cup_geom_indices:
            cup_mask = (geom_a == geom_index) | (geom_b == geom_index)
            if valid is not None:
                cup_mask &= valid
            if bool(cup_mask.any().item()):
                sealed.add(geom_index)
                mask |= cup_mask
        force_n = 0.0
        if bool(mask.any().item()):
            force_n = float(self.torch.linalg.vector_norm(forces[mask], dim=-1).max().item())
        self.last_sealed_cups = len(sealed)
        self.last_sealed_cup_mask = tuple(
            geom_index in sealed for geom_index in self._ordered_cup_geom_indices
        )
        self.max_contact_force_n = max(self.max_contact_force_n, force_n)
        return len(sealed), force_n

    def sealed_cup_mask(self) -> tuple[bool, bool, bool]:
        return self.last_sealed_cup_mask

    def try_latch(self) -> bool:
        sealed_cups, contact_force_n = self.contact_snapshot()
        if contact_force_n >= 35.0 or sealed_cups < self.min_sealed_cups:
            return False
        self.attachment = create_attachment(
            _flat_tuple(self.hand.get_pos()),
            _flat_tuple(self.hand.get_quat()),
            _flat_tuple(self.parcel.get_pos()),
            _flat_tuple(self.parcel.get_quat()),
            sealed_cup_count=sealed_cups,
        )
        self.latch_count += 1
        return True

    def update(self) -> bool:
        if self.attachment is None:
            self._zero_wrench()
            return False
        velocity = _flat_tuple(self.parcel.get_dofs_velocity())
        wrench = compliant_suction_wrench(
            self.attachment,
            _flat_tuple(self.hand.get_pos()),
            _flat_tuple(self.hand.get_quat()),
            _flat_tuple(self.parcel.get_pos()),
            _flat_tuple(self.parcel.get_quat()),
            velocity[:3],
            velocity[3:],
            translational_stiffness_n_m=800.0,
            translational_damping_n_s_m=18.0,
            rotational_stiffness_nm_rad=self.rotational_stiffness_nm_rad,
            rotational_damping_nm_s_rad=self.rotational_damping_nm_s_rad,
            max_force_n=self.force_limit_n,
            max_torque_nm=self.force_limit_n * 0.025,
            break_distance_m=0.08,
            break_angle_rad=0.65,
            free_twist_axis_world=(
                rotate_vector(_flat_tuple(self.hand.get_quat()), (0.0, 0.0, 1.0))
                if self.attachment.sealed_cup_count == 1
                else None
            ),
        )
        self.last_attachment_position_error_m = wrench.position_error_m
        self.last_attachment_orientation_error_rad = wrench.orientation_error_rad
        if wrench.broken:
            self.last_break_reason = (
                "position" if wrench.position_error_m > 0.08 else "orientation"
            )
            self.break_count += 1
            self.release()
            return False
        force_n = math.sqrt(sum(value * value for value in wrench.force_world_n))
        self.max_force_n = max(self.max_force_n, force_n)
        self.parcel.control_dofs_force(
            self.np.asarray((*wrench.force_world_n, *wrench.torque_world_nm))
        )
        return True

    def release(self) -> None:
        self.attachment = None
        self._zero_wrench()

    def _zero_wrench(self) -> None:
        self.parcel.control_dofs_force(self.np.zeros(6, dtype=self.np.float32))

    def summary(self) -> dict[str, float | int | bool | str | None]:
        return {
            "attached": self.attachment is not None,
            "sealed_cups": self.last_sealed_cups,
            "sealed_cup_mask": list(self.last_sealed_cup_mask),
            "latch_count": self.latch_count,
            "break_count": self.break_count,
            "max_suction_force_n": self.max_force_n,
            "max_contact_force_n": self.max_contact_force_n,
            "last_attachment_position_error_m": self.last_attachment_position_error_m,
            "last_attachment_orientation_error_rad": (
                self.last_attachment_orientation_error_rad
            ),
            "last_break_reason": self.last_break_reason,
            "minimum_principal_inertia_kg_m2": (
                self.minimum_principal_inertia_kg_m2
            ),
            "rotational_stiffness_nm_rad": self.rotational_stiffness_nm_rad,
            "rotational_damping_nm_s_rad": self.rotational_damping_nm_s_rad,
        }


def _flat_tuple(value: Any) -> tuple[float, ...]:
    if hasattr(value, "detach"):
        value = value.detach().cpu()
    if hasattr(value, "reshape"):
        value = value.reshape(-1)
    return tuple(float(item) for item in value)
