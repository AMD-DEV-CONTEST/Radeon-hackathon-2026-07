"""M4.2 smoke: arm_id URL 参数存活, /api/arms 列出正确 arm 槽."""

import asyncio
import json
import time

import httpx
import websockets


async def open_teleop(arm_id: str, hold: float = 0.8) -> None:
    url = f"ws://localhost:8002/ws/teleop?arm_id={arm_id}"
    async with websockets.connect(url, open_timeout=10) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "joint_update",
                    "robot_id": f"so101-{arm_id}",
                    "timestamp": time.time(),
                    "joints": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6": 0},
                }
            )
        )
        await asyncio.sleep(hold)


async def open_ui(arm_id: str, hold: float = 0.8) -> None:
    url = f"ws://localhost:8002/ws/ui?arm_id={arm_id}"
    async with websockets.connect(url, open_timeout=10) as ws:
        # receive initial snapshot (or nothing if no teleop data yet)
        try:
            await asyncio.wait_for(ws.recv(), timeout=0.5)
        except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
            pass
        await asyncio.sleep(hold)


async def main() -> None:
    async with httpx.AsyncClient() as c:
        # 并发开 3 个连接: left 有 teleop + ui, right 只有 ui
        tasks = [
            asyncio.create_task(open_teleop("left")),
            asyncio.create_task(open_ui("left")),
            asyncio.create_task(open_ui("right")),
        ]
        await asyncio.sleep(0.3)
        r = await c.get("http://localhost:8002/api/arms", timeout=10)
        r.raise_for_status()
        body = r.json()
        arms_by_id = {a["arm_id"]: a for a in body["items"]}
        print(f"  /api/arms -> {body}")
        assert "left" in arms_by_id, body
        assert arms_by_id["left"]["teleop"] == 1, arms_by_id["left"]
        assert arms_by_id["left"]["ui"] == 1, arms_by_id["left"]
        assert arms_by_id["right"]["teleop"] == 0
        assert arms_by_id["right"]["ui"] == 1
        await asyncio.gather(*tasks)

        # 连接关闭后应该清空 (或只剩 arm_0 stub)
        await asyncio.sleep(0.5)
        r2 = await c.get("http://localhost:8002/api/arms", timeout=10)
        body2 = r2.json()
        print(f"  after disconnect /api/arms -> {body2}")
        assert body2["total"] >= 1, body2

    print("\nOK M4.2 arm_id multi-arm placeholder smoke")


if __name__ == "__main__":
    asyncio.run(main())
