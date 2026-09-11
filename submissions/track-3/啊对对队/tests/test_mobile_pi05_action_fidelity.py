import math
import unittest

from parcel_sorter.mobile_pi05_action_fidelity import (
    absolute_action_fidelity,
    action_fidelity_gate,
    aggregate_absolute_action_fidelity,
    quaternion_geodesic_error_rad,
)


def _action() -> list[float]:
    return [
        0.0,
        0.0,
        0.0,
        -0.6,
        0.4,
        1.5,
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.6,
        0.4,
        1.5,
        1.0,
        0.0,
        0.0,
        0.0,
        -1.0,
        1.0,
        0.0,
        0.0,
        0.5,
    ]


class MobilePI05ActionFidelityTests(unittest.TestCase):
    def test_quaternion_distance_is_sign_invariant(self) -> None:
        self.assertAlmostEqual(
            quaternion_geodesic_error_rad(
                (1.0, 0.0, 0.0, 0.0), (-1.0, 0.0, 0.0, 0.0)
            ),
            0.0,
        )
        self.assertAlmostEqual(
            quaternion_geodesic_error_rad(
                (1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0)
            ),
            math.pi,
        )

    def test_exact_action_passes_fidelity_gate(self) -> None:
        row = absolute_action_fidelity(_action(), _action())
        aggregate = aggregate_absolute_action_fidelity([row, row, row])

        self.assertTrue(all(action_fidelity_gate(aggregate).values()))

    def test_large_pose_error_is_rejected(self) -> None:
        target = _action()
        predicted = _action()
        predicted[3] += 0.25
        row = absolute_action_fidelity(predicted, target)
        aggregate = aggregate_absolute_action_fidelity([row, row, row])

        gate = action_fidelity_gate(aggregate)
        self.assertFalse(gate["median_arm_position"])
        self.assertFalse(gate["maximum_arm_position"])

    def test_nonfinite_action_fails_closed(self) -> None:
        predicted = _action()
        predicted[0] = math.nan
        row = absolute_action_fidelity(predicted, _action())
        aggregate = aggregate_absolute_action_fidelity([row])

        self.assertFalse(action_fidelity_gate(aggregate)["finite"])
