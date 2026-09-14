import os
import sys
import unittest
from unittest.mock import MagicMock, Mock, call, patch


# The development container intentionally has no board GPIO package. Stub both
# import entries before importing production code so no hardware can be touched.
sys.modules["Hobot"] = MagicMock()
sys.modules["Hobot.GPIO"] = MagicMock()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from servo_ctrl import ServoController, WAVE_POSITION_HOLD_SECONDS  # noqa: E402


class TestWaveHands(unittest.TestCase):
    def setUp(self):
        self.controller = ServoController()
        self.sequence = Mock()
        self.controller.lift_left = self.sequence.lift_left
        self.controller.lower_left = self.sequence.lower_left
        self.controller.lift_right = self.sequence.lift_right
        self.controller.lower_right = self.sequence.lower_right
        self.sleep_patch = patch("servo_ctrl.time.sleep", self.sequence.hold)
        self.sleep_patch.start()
        self.addCleanup(self.sleep_patch.stop)

    def test_wave_hands_sequence(self):
        self.controller.wave_hands()

        self.assertEqual(
            self.sequence.mock_calls,
            [
                call.lift_left(),
                call.hold(WAVE_POSITION_HOLD_SECONDS),
                call.lower_left(),
                call.lift_right(),
                call.hold(WAVE_POSITION_HOLD_SECONDS),
                call.lower_right(),
            ],
        )


if __name__ == "__main__":
    unittest.main()
