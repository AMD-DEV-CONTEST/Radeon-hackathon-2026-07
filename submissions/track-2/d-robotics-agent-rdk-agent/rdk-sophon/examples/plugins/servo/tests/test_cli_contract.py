import unittest
import tomllib
import sys
import os
from unittest.mock import patch, MagicMock

# 1. 静态解析 plugin.toml
plugin_path = os.path.join(os.path.dirname(__file__), '..', 'plugin.toml')
with open(plugin_path, 'rb') as f:
    plugin_config = tomllib.load(f)

API_VERSION = plugin_config['api_version']
PLUGIN_ID = plugin_config['id']
ENTRYPOINT = plugin_config['entrypoint']

# 2. Mock Hobot 模块，避免导入时初始化 GPIO
sys.modules['Hobot'] = MagicMock()
sys.modules['Hobot.GPIO'] = MagicMock()

# 3. 导入 CLI 模块（此时必须已 mock Hobot）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from servo_ctrl import ACTIONS, LEFT_INITIAL_DUTY, MANAGED_ACTION_RESERVED, RIGHT_INITIAL_DUTY, ServoController  # noqa: E402

# 4. 验证 ACTIONS 包含目标动作
TARGET_ACTIONS = {'lift-left', 'lower-left', 'lift-right', 'lower-right'}
assert TARGET_ACTIONS.issubset(ACTIONS.keys()), f"ACTIONS missing required keys: {TARGET_ACTIONS - ACTIONS.keys()}"


class TestPWMStartIsolation(unittest.TestCase):
    def setUp(self):
        self.left_pwm = MagicMock()
        self.right_pwm = MagicMock()
        from servo_ctrl import GPIO
        GPIO.cleanup.reset_mock()
        with patch('servo_ctrl.GPIO.PWM', side_effect=[self.left_pwm, self.right_pwm]):
            self.controller = ServoController()

    def test_start_left_does_not_touch_right_pwm(self):
        self.controller._start_left(LEFT_INITIAL_DUTY)

        self.left_pwm.ChangeDutyCycle.assert_called_once_with(LEFT_INITIAL_DUTY)
        self.left_pwm.start.assert_called_once_with(LEFT_INITIAL_DUTY)
        self.right_pwm.ChangeDutyCycle.assert_not_called()
        self.right_pwm.start.assert_not_called()

        self.controller.close()
        self.left_pwm.stop.assert_called_once()
        self.right_pwm.stop.assert_not_called()
        from servo_ctrl import GPIO
        GPIO.cleanup.assert_called_once_with([self.controller.left_pin])

    def test_start_right_does_not_touch_left_pwm(self):
        self.controller._start_right(RIGHT_INITIAL_DUTY)

        self.right_pwm.ChangeDutyCycle.assert_called_once_with(RIGHT_INITIAL_DUTY)
        self.right_pwm.start.assert_called_once_with(RIGHT_INITIAL_DUTY)
        self.left_pwm.ChangeDutyCycle.assert_not_called()
        self.left_pwm.start.assert_not_called()

        self.controller.close()
        self.right_pwm.stop.assert_called_once()
        self.left_pwm.stop.assert_not_called()
        from servo_ctrl import GPIO
        GPIO.cleanup.assert_called_once_with([self.controller.right_pin])


# 5. 测试类
class TestCLIServiceContract(unittest.TestCase):

    def test_plugin_manifest_valid(self):
        self.assertEqual(API_VERSION, 1)
        self.assertEqual(PLUGIN_ID, "servo")
        self.assertEqual(ENTRYPOINT, ["/usr/bin/python3", "/userdata/magicbox/scripts/servo_ctrl.py"])

    def test_retired_wave_right_hand_is_not_an_available_action(self):
        self.assertNotIn("wave-right-hand", ACTIONS)

    def test_managed_packages_cannot_shadow_builtin_commands(self):
        self.assertEqual(MANAGED_ACTION_RESERVED, set(ACTIONS) | {"servo", "remove"})

    def assert_single_side_lowering(self, action, start_method, untouched_start_method, initial_duty, action_method):
        with patch('sys.argv', ['servo_ctrl.py', action, '--hold', '0']), \
                patch('servo_ctrl.ServoController') as mock_servo_controller, \
                patch('signal.signal'), \
                patch('atexit.register'), \
                patch('servo_ctrl.time.sleep'):
            from servo_ctrl import main
            main()

        controller = mock_servo_controller.return_value
        controller._start.assert_not_called()
        getattr(controller, start_method).assert_called_once_with(initial_duty)
        getattr(controller, untouched_start_method).assert_not_called()
        getattr(controller, action_method).assert_called_once()

    def test_lower_left_starts_only_left_pwm(self):
        self.assert_single_side_lowering(
            'lower-left', '_start_left', '_start_right', LEFT_INITIAL_DUTY, 'lower_left'
        )

    def test_lower_right_starts_only_right_pwm(self):
        self.assert_single_side_lowering(
            'lower-right', '_start_right', '_start_left', RIGHT_INITIAL_DUTY, 'lower_right'
        )

if __name__ == '__main__':
    unittest.main()
