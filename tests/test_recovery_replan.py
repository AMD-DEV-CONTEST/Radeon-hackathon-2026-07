#!/usr/bin/env python3
"""
Unit test for recovery.py replan loop fix.
Verifies that replanned actions are actually executed (not skipped by pass).
No GPU needed — uses mock pipeline.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock
from src.planner.recovery import RecoveryManager


def make_pos_mock(values):
    """Create a mock that returns position values from .get_pos().cpu().numpy().tolist()."""
    pos = MagicMock()
    pos.cpu.return_value.numpy.return_value.tolist.return_value = values
    return pos


def make_scene_obj(initial_pos):
    """Create a mock scene object with a fixed position."""
    obj = MagicMock()
    obj.get_pos.return_value = make_pos_mock(initial_pos)
    return obj


def make_scene_obj_sequence(positions):
    """Create a mock scene object that returns different positions on each call."""
    obj = MagicMock()
    obj.get_pos.side_effect = [make_pos_mock(p) for p in positions]
    return obj


# ── Test 1: Successful pick — no replan needed ──────────────

def test_pick_success_no_replan():
    # Object starts at [0.65, 0, 0.02], after pick moves to [0.65, 0, 0.30]
    obj = make_scene_obj_sequence([
        [0.65, 0.0, 0.02],   # pre_pos
        [0.65, 0.0, 0.30],   # post_pos (lifted)
    ])
    pipe = MagicMock()
    pipe.suction_pick.return_value = True

    rm = RecoveryManager(MagicMock())
    result = rm.execute_with_recovery(
        pipe, {"action": "pick", "object": "red_cube"}, {"red_cube": obj})

    assert result["success"] is True, f"Expected success, got {result}"
    assert result["attempts"] == 1
    pipe.suction_pick.assert_called_once_with("red_cube")
    print("PASS: test_pick_success_no_replan")


# ── Test 2: Pick fails once (no movement), replan succeeds ──

def test_pick_fail_then_replan_succeeds():
    """Core test: replanned actions must be EXECUTED, not skipped."""
    # Mock that alternates: same position (fail) then different (success)
    pos_call_count = [0]
    def get_pos_side_effect():
        pos = MagicMock()
        pos_call_count[0] += 1
        # Odd calls: same position (pre), Even calls: same OR lifted (post)
        # Pattern: pre=fixed, post=fixed (fail), pre=fixed, post=lifted (success)
        if pos_call_count[0] % 2 == 1:
            # pre_pos: always ground level
            pos.cpu.return_value.numpy.return_value.tolist.return_value = [0.65, 0.0, 0.02]
        else:
            # post_pos: first time same (fail), after that lifted (success)
            if pos_call_count[0] <= 2:
                pos.cpu.return_value.numpy.return_value.tolist.return_value = [0.65, 0.0, 0.02]
            else:
                pos.cpu.return_value.numpy.return_value.tolist.return_value = [0.65, 0.0, 0.30]
        return pos

    obj = MagicMock()
    obj.get_pos.side_effect = get_pos_side_effect

    pipe = MagicMock()
    call_count = [0]
    def pick_side_effect(*args, **kw):
        call_count[0] += 1
        return call_count[0] > 1
    pipe.suction_pick.side_effect = pick_side_effect

    rm = RecoveryManager(MagicMock())
    result = rm.execute_with_recovery(
        pipe, {"action": "pick", "object": "red_cube"}, {"red_cube": obj})

    assert pipe.suction_pick.call_count >= 2, (
        f"Expected >=2 suction_pick calls (original + replan), "
        f"got {pipe.suction_pick.call_count}")
    assert result["success"] is True, f"Expected success, got {result}"
    assert result.get("replanned") is True, f"Expected replanned, got {result}"
    print("PASS: test_pick_fail_then_replan_succeeds")


# ── Test 3: Pick fails, replan also fails ───────────────────

def test_pick_fail_replan_also_fails():
    """Replan executes but the replanned action also fails."""
    # All positions same = always fails
    obj = make_scene_obj([0.65, 0.0, 0.02])
    pipe = MagicMock()
    pipe.suction_pick.return_value = False

    rm = RecoveryManager(MagicMock())
    result = rm.execute_with_recovery(
        pipe, {"action": "pick", "object": "red_cube"}, {"red_cube": obj})

    # Should have tried multiple times
    assert pipe.suction_pick.call_count >= 2, (
        f"Expected >=2 calls, got {pipe.suction_pick.call_count}")
    assert result["success"] is False
    print("PASS: test_pick_fail_replan_also_fails")


# ── Test 4: Place fails, replan re-picks then places ────────

def test_place_fail_replan_repicks():
    """Place failure triggers replan with [pick, place] sequence."""
    # Generous values for recursive calls - provide enough for multiple calls
    obj = make_scene_obj_sequence([
        [0.65, 0.0, 0.30],   # pre_pos for place attempt 1
        [0.65, 0.0, 0.02],   # post_pos (z dropped = drop failure)
        [0.65, 0.0, 0.02],   # pre_pos for replan pick
        [0.65, 0.0, 0.30],   # post_pos (lifted = pick ok)
        [0.65, 0.0, 0.30],   # pre_pos for replan place
        [0.40, 0.2, 0.02],   # post_pos (at target = place ok)
        [0.40, 0.2, 0.02],   # extra
        [0.40, 0.2, 0.02],   # extra
        [0.40, 0.2, 0.02],   # extra
        [0.40, 0.2, 0.02],   # extra
        [0.40, 0.2, 0.02],   # extra
        [0.40, 0.2, 0.02],   # extra
        [0.40, 0.2, 0.02],   # extra
        [0.40, 0.2, 0.02],   # extra
        [0.40, 0.2, 0.02],   # extra
        [0.40, 0.2, 0.02],   # extra
    ])
    pipe = MagicMock()
    pipe.suction_place.side_effect = [0.50, 0.05]  # first fails, second ok
    pipe.suction_pick.return_value = True

    rm = RecoveryManager(MagicMock())
    result = rm.execute_with_recovery(
        pipe, {"action": "place", "object": "red_cube"},
        {"red_cube": obj}, target_pos=[0.4, 0.2, 0.02])

    assert pipe.suction_place.call_count >= 2, (
        f"Expected >=2 place calls, got {pipe.suction_place.call_count}")
    assert pipe.suction_pick.call_count >= 1, (
        f"Expected >=1 pick call from replan, got {pipe.suction_pick.call_count}")
    print("PASS: test_place_fail_replan_repicks")


# ── Test 5: Abort after too many failures ────────────────────

def test_abort_after_max_failures():
    """Should abort after recording too many failures."""
    obj = make_scene_obj([0.65, 0.0, 0.02])
    pipe = MagicMock()
    pipe.suction_pick.return_value = False

    rm = RecoveryManager(MagicMock())
    rm.max_retries = 5

    result = rm.execute_with_recovery(
        pipe, {"action": "pick", "object": "red_cube"}, {"red_cube": obj})

    assert result["success"] is False
    reason = result.get("reason", "").lower()
    assert "too many" in reason or "max retries" in reason, (
        f"Expected abort reason, got: {result}")
    print("PASS: test_abort_after_max_failures")


# ── Run all tests ────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_pick_success_no_replan,
        test_pick_fail_then_replan_succeeds,
        test_pick_fail_replan_also_fails,
        test_place_fail_replan_repicks,
        test_abort_after_max_failures,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"FAIL: {t.__name__} -> {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"  Results: {passed} passed, {failed} failed")
    print(f"{'='*50}")
    sys.exit(0 if failed == 0 else 1)
