"""M6.3 Reachy Mini Runtime dry smoke.

Verifies (without real hardware or reachy_mini SDK installed):
  1. reachy_mini runtime is registered and discoverable.
  2. Mock writer lifecycle works (connect/preflight/torque/write/disconnect).
  3. Mock reader returns 9 joint positions.
  4. Joint names match expected 9 DoF layout.
  5. BotclawFollower accepts a Reachy Mini mock writer.
"""
from __future__ import annotations

import sys
from pathlib import Path

REALTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REALTIME_ROOT))


def test_registry() -> None:
    from runtimes import list_runtimes, get_runtime_class

    assert "reachy_mini" in list_runtimes(), "reachy_mini not registered"
    cls = get_runtime_class("reachy_mini")
    assert cls.info.runtime_id == "reachy_mini"
    assert cls.info.joint_count == 9
    assert cls.info.robot_type == "reachy_mini"
    assert len(cls.info.joint_names) == 9
    assert cls.info.joint_names[0] == "body_rotation"
    assert cls.info.joint_names[-1] == "left_antenna"
    print(f"[1] registry OK — {cls.info.display_name}")


def test_mock_writer() -> None:
    from runtimes import get_runtime_class

    cls = get_runtime_class("reachy_mini")
    w = cls.create_mock_writer(name="smoke_reachy")

    assert not w.is_connected
    w.connect()
    assert w.is_connected

    ok, msg = w.preflight()
    assert ok, f"preflight failed: {msg}"

    w.enable_torque()
    assert w.torque_enabled

    joints = {name: 0.1 * i for i, name in enumerate(cls.info.joint_names)}
    n = w.write_positions(joints)
    assert n == 9, f"expected 9 writes, got {n}"
    assert len(w.write_log) == 1

    w.disable_torque()
    assert not w.torque_enabled

    w.disconnect()
    assert not w.is_connected
    print(f"[2] mock writer lifecycle OK (events={w.events})")


def test_mock_reader() -> None:
    from runtimes import get_runtime_class

    cls = get_runtime_class("reachy_mini")
    r = cls.create_mock_reader()

    assert not r.is_connected
    r.connect()
    assert r.is_connected

    positions = r.read_positions()
    assert positions is not None
    assert len(positions) == 9, f"expected 9 positions, got {len(positions)}"

    telemetry = r.read_telemetry()
    assert isinstance(telemetry, dict)

    r.disconnect()
    assert not r.is_connected
    print(f"[3] mock reader OK — 9 positions returned")


def test_follower_accepts_reachy_writer() -> None:
    from runtimes import get_runtime_class
    from sender.follower import BotclawFollower

    cls = get_runtime_class("reachy_mini")
    w = cls.create_mock_writer(name="follower_reachy")

    follower = BotclawFollower(
        writer=w,
        arm_id="reachy_smoke",
        max_delta_rad=0.15,
        heartbeat_timeout_s=0.5,
        torque_on_start=False,
    )
    assert follower.writer is w
    print("[4] BotclawFollower accepts Reachy Mini mock writer OK")


def test_cli_shows_reachy() -> None:
    from runtimes import list_runtimes
    rts = list_runtimes()
    assert "reachy_mini" in rts
    assert "so101" in rts
    print(f"[5] CLI would show --runtime choices: {rts}")


def main() -> None:
    print("=" * 60)
    print("M6.3 Reachy Mini Runtime — Dry Smoke")
    print("=" * 60)

    test_registry()
    test_mock_writer()
    test_mock_reader()
    test_follower_accepts_reachy_writer()
    test_cli_shows_reachy()

    print()
    print("=" * 60)
    print("ALL 5 CHECKS PASSED — M6.3 Reachy Mini dry smoke OK")
    print("=" * 60)


if __name__ == "__main__":
    main()
