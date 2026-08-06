"""M1.2 冒烟脚本 — 仅开发期手工跑.

同时起一个 sender (/ws/teleop) 和 ui (/ws/ui), 验证:
1. 旧格式 {joint_positions} 可被兼容为 BotClaw JointUpdate
2. 新格式 {type/robot_id/timestamp/joints/meta} 可被 Pydantic 通过
3. UI 端收到的广播帧符合 BotClaw JointUpdate shape
"""

import asyncio
import json
import time

import websockets


async def fake_ui(got: list[dict]) -> None:
    async with websockets.connect("ws://localhost:8002/ws/ui") as ws:
        for _ in range(4):
            msg = json.loads(await ws.recv())
            got.append(msg)


async def fake_sender() -> None:
    async with websockets.connect("ws://localhost:8002/ws/teleop") as ws:
        # 1) V2 旧 payload
        await ws.send(json.dumps({
            "joint_positions": {"1": 1.0, "2": 2.0, "3": 3.0, "4": 4.0, "5": 5.0, "6": 6.0},
            "servo_values": {"1": 2048, "2": 2048, "3": 2048, "4": 2048, "5": 2048, "6": 2048},
        }))
        await asyncio.sleep(0.1)
        # 2) BotClaw 新 payload
        await ws.send(json.dumps({
            "type": "joint_update",
            "robot_id": "so101-smoke",
            "timestamp": time.time(),
            "joints": {"1": 10, "2": 20, "3": 30, "4": 40, "5": 50, "6": 60},
            "servo_values": {"1": 2100, "2": 2100, "3": 2100, "4": 2100, "5": 2100, "6": 2100},
            "meta": {"fps": 30.0, "source": "smoke"},
        }))
        await asyncio.sleep(0.3)


async def main() -> None:
    got: list[dict] = []
    ui_task = asyncio.create_task(fake_ui(got))
    await asyncio.sleep(0.2)  # 让 ui 先连上
    await fake_sender()
    try:
        await asyncio.wait_for(ui_task, timeout=2.0)
    except asyncio.TimeoutError:
        pass

    print(f"UI received {len(got)} frames")
    for i, m in enumerate(got):
        print(f"--- frame {i} ---")
        print(json.dumps(m, indent=2, ensure_ascii=False))

    # assertions
    assert any(m.get("type") == "joint_update" for m in got), "no joint_update frame"
    j1 = next((m for m in got if m.get("joints", {}).get("1") == 1.0), None)
    assert j1 is not None, "old V2 payload was not normalized"
    assert "robot_id" in j1 and "timestamp" in j1, f"missing BotClaw fields: {j1}"
    j2 = next((m for m in got if m.get("robot_id") == "so101-smoke"), None)
    assert j2 is not None, "new BotClaw payload not received"
    assert j2["joints"]["1"] == 10
    assert j2.get("meta", {}).get("source") == "smoke"
    print("\nOK: /ws/teleop 兼容层 + /ws/ui 广播 shape 对齐 BotClaw v0.1")


if __name__ == "__main__":
    asyncio.run(main())
