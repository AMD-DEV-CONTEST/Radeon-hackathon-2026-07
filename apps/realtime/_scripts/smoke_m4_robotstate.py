"""M4.3 smoke: /ws/robotstate + /api/robotstate 基本字段齐."""

import asyncio
import json
import time

import httpx
import websockets


async def test_rest() -> dict:
    async with httpx.AsyncClient() as c:
        r = await c.get("http://localhost:8002/api/robotstate", timeout=10)
        r.raise_for_status()
        body = r.json()
        assert body["type"] == "robot_state", body
        assert "teleop_connected" in body
        assert "ui_clients" in body
        assert "limits_rad" in body and set(body["limits_rad"].keys()) == {"1", "2", "3", "4", "5", "6"}
        assert "safety" in body and "estop" in body["safety"]
        return body


async def test_ws() -> None:
    url = "ws://localhost:8002/ws/robotstate?hz=5"
    async with websockets.connect(url, open_timeout=15) as ws:
        start = time.time()
        snapshots: list[dict] = []
        while len(snapshots) < 6 and time.time() - start < 5.0:
            raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
            msg = json.loads(raw)
            assert msg["type"] == "robot_state"
            snapshots.append(msg)
        assert len(snapshots) >= 5, f"expected >=5 snapshots at 5Hz in 5s, got {len(snapshots)}"

        # 间隔应 ~200ms
        dts = [snapshots[i + 1]["timestamp"] - snapshots[i]["timestamp"] for i in range(len(snapshots) - 1)]
        print(f"  got {len(snapshots)} snapshots, dt samples: {dts[:4]}")


async def test_teleop_effect() -> None:
    """连一个 teleop 进去, 确认 RobotState 里 teleop_connected 反映真相."""
    async with websockets.connect("ws://localhost:8002/ws/teleop", open_timeout=10) as teleop:
        await teleop.send(json.dumps({
            "type": "joint_update",
            "robot_id": "so101-smoke",
            "timestamp": time.time(),
            "joints": {"1": 0.1, "2": 0.2, "3": 0.3, "4": 0.4, "5": 0.5, "6": 0.6},
            "servo_values": {"1": 100, "2": 200, "3": 300, "4": 400, "5": 500, "6": 600},
            "temperatures_c": {"1": 35.0, "2": 36.0, "3": 34.0, "4": 35.5, "5": 33.0, "6": 37.0},
            "currents_a": {"1": 0.1, "2": 0.12, "3": 0.11, "4": 0.13, "5": 0.09, "6": 0.14},
        }))
        await asyncio.sleep(0.3)
        async with httpx.AsyncClient() as c:
            r = await c.get("http://localhost:8002/api/robotstate", timeout=10)
            body = r.json()
            assert body["teleop_connected"] is True, body
            assert body["robot_id"] == "so101-smoke", body
            assert body["joints"]["3"] == 0.3, body
            assert body["servo_values"]["3"] == 300, body
            assert body["temperatures_c"]["3"] == 34.0, body
            assert body["currents_a"]["3"] == 0.11, body
        print("  teleop -> RobotState round-trip OK (joints + servo + temp + current)")


async def main() -> None:
    snap = await test_rest()
    print(f"[1] REST snapshot: teleop={snap['teleop_connected']}, ui_clients={snap['ui_clients']}")

    await test_ws()
    print("[2] WS 5Hz streaming OK")

    await test_teleop_effect()
    print("[3] teleop telemetry reflected OK")

    print("\nOK M4.3 RobotState smoke")


if __name__ == "__main__":
    asyncio.run(main())
