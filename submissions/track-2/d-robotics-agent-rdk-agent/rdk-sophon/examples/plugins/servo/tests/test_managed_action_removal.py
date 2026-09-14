import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch


sys.modules["Hobot"] = MagicMock()
sys.modules["Hobot.GPIO"] = MagicMock()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import servo_ctrl  # noqa: E402


class TestManagedActionRemoval(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.actions_dir = Path(self.temporary.name) / "servo_actions"
        self.actions_dir.mkdir()
        self.environment = patch.dict(
            os.environ,
            {"MAGICBOX_SERVO_ACTIONS_DIR": str(self.actions_dir)},
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def write_action(self, name="wave-left-hand"):
        package = self.actions_dir / name
        package.mkdir()
        (package / "registry.json").write_text(
            json.dumps({
                "schema": "rdk-servo-action/v1",
                "id": name,
                "description": "挥动左手",
                "entrypoint": "action.py:run",
                "start": "left",
                "arguments": [],
                "skill": {"intentExamples": ["挥动左手"], "risk": "motion"},
            }),
            encoding="utf-8",
        )
        (package / "action.py").write_text(
            "def run(context, params):\n    context.lift_left()\n",
            encoding="utf-8",
        )
        return package

    def test_remove_moves_the_complete_action_package_to_backup(self):
        package = self.write_action()

        backup = servo_ctrl.remove_managed_action("wave-left-hand")

        self.assertFalse(package.exists())
        self.assertTrue((backup / "wave-left-hand" / "registry.json").is_file())
        self.assertTrue((backup / "wave-left-hand" / "action.py").is_file())

    def test_registry_loads_only_the_matching_module_and_start_policy(self):
        self.write_action()

        run, start = servo_ctrl.load_managed_action("wave-left-hand")
        controller = MagicMock()
        run(controller, [])

        self.assertEqual(start, "left")
        controller.lift_left.assert_called_once_with()

    def test_remove_rejects_builtin_unknown_and_unsafe_names(self):
        with self.assertRaisesRegex(ValueError, "内置动作"):
            servo_ctrl.remove_managed_action("lift-left")
        with self.assertRaisesRegex(ValueError, "动作名必须"):
            servo_ctrl.remove_managed_action("../servo_ctrl")

    def test_discovery_ignores_a_malformed_package(self):
        self.write_action()
        malformed = self.actions_dir / "broken-action"
        malformed.mkdir()
        (malformed / "registry.json").write_text("not-json", encoding="utf-8")

        self.assertEqual(servo_ctrl.managed_action_names(), ["wave-left-hand"])

    def test_help_discovers_description_from_local_registry(self):
        self.write_action()

        with patch("sys.stdout", new_callable=StringIO) as output, \
                patch.object(sys, "argv", ["servo_ctrl.py", "--help"]), \
                self.assertRaises(SystemExit) as exit_context:
            servo_ctrl.main()

        self.assertEqual(exit_context.exception.code, 0)
        self.assertIn("wave-left-hand       挥动左手", output.getvalue())

    def test_v1_managed_action_rejects_runtime_arguments_before_starting_pwm(self):
        self.write_action()

        with patch.object(servo_ctrl, "ServoController") as controller, \
                patch("sys.stderr", new_callable=StringIO), \
                patch.object(sys, "argv", ["servo_ctrl.py", "wave-left-hand", "unexpected"]), \
                self.assertRaises(SystemExit) as exit_context:
            servo_ctrl.main()

        self.assertEqual(exit_context.exception.code, 2)
        controller.return_value._start_left.assert_not_called()

    def test_remove_main_does_not_construct_a_servo_controller(self):
        with patch.object(servo_ctrl, "remove_managed_action", return_value=Path("/tmp/backup")) as remove, \
                patch.object(servo_ctrl, "ServoController") as controller, \
                patch("sys.stdout", new_callable=StringIO), \
                patch.object(sys, "argv", ["servo_ctrl.py", "remove", "wave-left-hand"]):
            servo_ctrl.main()

        remove.assert_called_once_with("wave-left-hand")
        controller.assert_not_called()


if __name__ == "__main__":
    unittest.main()
