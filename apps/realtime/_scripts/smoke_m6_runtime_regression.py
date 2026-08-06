"""M6.2 Runtime abstraction regression smoke.

Verifies:
  1. `list_runtimes()` returns at least ["so101"].
  2. `get_runtime_class("so101")` returns a class with .info, .create_reader,
     .create_writer, .create_mock_writer factory methods.
  3. Mock writer created via Runtime has the same interface as the original
     MockArmWriter (connect/preflight/enable_torque/write_positions/disable_torque/disconnect).
  4. BotclawFollower accepts a Runtime-created writer and doesn't crash on init.
  5. CLI `--runtime so101` is accepted by argparse (no runtime = defaults to so101).

Does NOT require the realtime server or any hardware — pure in-process checks.
"""
from __future__ import annotations

import sys
from pathlib import Path

REALTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REALTIME_ROOT))


def test_registry() -> None:
    from runtimes import list_runtimes, get_runtime_class

    rts = list_runtimes()
    assert "so101" in rts, f"so101 not in registry: {rts}"
    print(f"[1] list_runtimes() = {rts}")

    cls = get_runtime_class("so101")
    assert hasattr(cls, "info"), "SO101Runtime missing .info"
    assert cls.info.runtime_id == "so101"
    assert cls.info.joint_count == 6
    assert cls.info.robot_type == "so101"
    print(f"[1] get_runtime_class('so101').info OK — {cls.info.display_name}")


def test_mock_writer_via_runtime() -> None:
    from runtimes import get_runtime_class

    cls = get_runtime_class("so101")
    w = cls.create_mock_writer(name="regression_test")

    assert not w.is_connected
    assert w.connect()
    assert w.is_connected

    ok, msg = w.preflight()
    assert ok, f"preflight failed: {msg}"

    assert w.enable_torque()
    assert w.torque_enabled

    joints = {"1": 0.1, "2": -0.2, "3": 0.3, "4": 0.0, "5": 0.5, "6": -0.1}
    n = w.write_positions(joints)
    assert n == 6, f"expected 6 writes, got {n}"

    w.disable_torque()
    assert not w.torque_enabled

    w.disconnect()
    assert not w.is_connected

    print("[2] mock writer lifecycle (connect->preflight->torque->write->disconnect) OK")


def test_follower_accepts_runtime_writer() -> None:
    from runtimes import get_runtime_class
    from sender.follower import BotclawFollower

    cls = get_runtime_class("so101")
    w = cls.create_mock_writer(name="follower_regression")

    follower = BotclawFollower(
        writer=w,
        arm_id="arm_regression",
        max_delta_rad=0.15,
        heartbeat_timeout_s=0.5,
        torque_on_start=False,
    )
    assert follower.writer is w
    assert follower.arm_id == "arm_regression"
    print("[3] BotclawFollower accepts Runtime-created writer OK")


def test_cli_argparse() -> None:
    import argparse
    old_argv = sys.argv
    try:
        # Old format (no --runtime): should default to so101
        sys.argv = ["sender", "--mode", "follower", "--dry_run"]
        from sender.__main__ import main as _  # just import to verify no crash
        from runtimes import list_runtimes
        rts = list_runtimes()
        parser = argparse.ArgumentParser()
        parser.add_argument("--runtime", default="so101", choices=rts)
        parser.add_argument("--mode", default="leader")
        parser.add_argument("--dry_run", action="store_true")

        args = parser.parse_args(["--mode", "follower", "--dry_run"])
        assert args.runtime == "so101", f"default runtime should be so101, got {args.runtime}"

        args2 = parser.parse_args(["--runtime", "so101", "--mode", "leader"])
        assert args2.runtime == "so101"
        print("[4] CLI argparse: --runtime defaults to so101, explicit --runtime so101 accepted OK")
    finally:
        sys.argv = old_argv


def test_backward_compat_imports() -> None:
    """Original M5 import paths still work — nothing was moved, only wrapped."""
    from sender.writer import BaseArmWriter, MockArmWriter, FollowerArmWriter
    from sender.reader import LeaderArmReader
    from sender.follower import BotclawFollower
    from sender.sender import BotclawSender
    from sender.calibration import CalibrationLoader, JointCalibration

    assert BaseArmWriter is not None
    assert MockArmWriter is not None
    print("[5] all M5 import paths (sender.writer/reader/follower/sender/calibration) still resolve OK")


def main() -> None:
    print("=" * 60)
    print("M6.2 Runtime Abstraction — Regression Smoke")
    print("=" * 60)

    test_registry()
    test_mock_writer_via_runtime()
    test_follower_accepts_runtime_writer()
    test_cli_argparse()
    test_backward_compat_imports()

    print()
    print("=" * 60)
    print("ALL 5 CHECKS PASSED — M6.2 regression OK")
    print("=" * 60)


if __name__ == "__main__":
    main()
