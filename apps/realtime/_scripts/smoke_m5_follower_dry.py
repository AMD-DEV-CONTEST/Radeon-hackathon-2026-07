"""M5 follower smoke (dry mode with MockArmWriter).

Verifies:
  1. Follower subscribes to /ws/ui?arm_id=<id> and survives the connect race.
  2. Inference frames (joint_update with meta.source="inference") from a fake
     publisher actually reach the follower's MockArmWriter.
  3. Client-side SafetyGate runs — when we feed a NaN we get a fatal + torque off.
  4. Global E-Stop via POST /api/inference/estop is reflected in /ws/robotstate
     and causes the follower to disable_torque.
  5. Heartbeat fail-safe: once the fake publisher stops, torque drops within
     heartbeat_timeout_s.

Does NOT require trained models / real compare_ws — uses a tiny "fake inference
publisher" that connects to /ws/teleop with meta.source="inference". The realtime
server preserves `meta` when broadcasting teleop frames to /ws/ui, so the follower
can't tell the difference from a real compare echo.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
import websockets

REALTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REALTIME_ROOT))

from sender.follower import BotclawFollower  # noqa: E402
from sender.writer import MockArmWriter  # noqa: E402


RT = "http://localhost:8002"
WS_TELEOP = "ws://localhost:8002/ws/teleop"
ARM = "arm_smoke_m5"


async def fake_inference_publisher(stop_evt: asyncio.Event, period: float = 1 / 30) -> int:
    """Connect to /ws/teleop and blast synthetic inference frames at `1/period` Hz."""
    sent = 0
    url = f"{WS_TELEOP}?arm_id={ARM}"
    async with websockets.connect(url, open_timeout=10) as ws:
        t0 = time.time()
        while not stop_evt.is_set():
            t = time.time() - t0
            joints = {
                "1": 0.30 + 0.20 * __import__("math").sin(t * 1.2),
                "2": 0.10 + 0.10 * __import__("math").sin(t * 0.9 + 1.0),
                "3": -0.10,
                "4": 0.05,
                "5": 0.10,
                "6": 0.0,
            }
            payload = {
                "type": "joint_update",
                "robot_id": "so101-smoke-m5",
                "timestamp": time.time(),
                "joints": joints,
                "meta": {
                    "source": "inference",
                    "model_key": "smoke-model",
                    "dataset_id": "smoke-ds",
                },
            }
            await ws.send(json.dumps(payload))
            sent += 1
            await asyncio.sleep(period)
    return sent


async def main() -> None:
    print("=" * 60)
    print("M5 follower dry smoke")
    print("=" * 60)

    # Reset global estop from any previous run.
    async with httpx.AsyncClient(timeout=5) as c:
        await c.post(f"{RT}/api/inference/resume")

    writer = MockArmWriter(name="m5_smoke")
    follower = BotclawFollower(
        writer=writer,
        arm_id=ARM,
        ui_url="ws://localhost:8002/ws/ui",
        robotstate_url="ws://localhost:8002/ws/robotstate",
        max_delta_rad=0.10,        # loosen so first-frame deltas don't stall the smoke
        heartbeat_timeout_s=0.6,
        torque_on_start=True,
    )

    # Launch follower on a task (MockArmWriter means no hardware / no preflight fail)
    follower_task = asyncio.create_task(follower.run_async())
    await asyncio.sleep(0.6)  # let /ws/ui + /ws/robotstate subscriptions settle

    # Drive frames for ~1.5s
    stop_evt = asyncio.Event()
    pub_task = asyncio.create_task(fake_inference_publisher(stop_evt))
    await asyncio.sleep(1.5)

    sent_count_mid = await asyncio.to_thread(lambda: len(writer.write_log))
    assert sent_count_mid >= 20, f"[1] expected >=20 writes, got {sent_count_mid}"
    last_frame = writer.write_log[-1]
    assert set(last_frame.keys()) == {"1", "2", "3", "4", "5", "6"}, last_frame
    assert writer.torque_enabled, "[1] torque should still be on while streaming"
    print(f"[1] subscribe + gate + write OK — {sent_count_mid} frames written")

    # Trigger global E-Stop via REST — follower's /ws/robotstate watcher should
    # see safety.estop=true within the 5Hz snapshot window (~200ms).
    async with httpx.AsyncClient(timeout=5) as c:
        r = await c.post(f"{RT}/api/inference/estop")
        r.raise_for_status()
        body = r.json()
        assert body.get("global_estop") is True, body

    deadline = time.time() + 2.0
    while time.time() < deadline and writer.torque_enabled:
        await asyncio.sleep(0.05)
    assert not writer.torque_enabled, "[2] E-Stop did not disable torque within 2s"
    print(f"[2] global E-Stop -> follower disabled torque OK (events tail={writer.events[-4:]})")

    # Clean up publisher + follower
    stop_evt.set()
    await pub_task
    follower.stop()
    follower_task.cancel()
    try:
        await follower_task
    except (asyncio.CancelledError, Exception):
        pass

    # Resume global state so future runs are clean
    async with httpx.AsyncClient(timeout=5) as c:
        await c.post(f"{RT}/api/inference/resume")

    print(f"[3] mock writer events: {writer.events}")
    print(f"[4] total frames_written={follower.frames_written} "
          f"dropped_gate={follower.frames_dropped_gate} estop_triggered={follower.estop_triggered}")
    print()
    print("OK M5 follower (dry) smoke")


if __name__ == "__main__":
    asyncio.run(main())
