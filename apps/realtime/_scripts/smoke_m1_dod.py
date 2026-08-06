"""M1 DoD 冒烟: realtime 在 :8002 已起来, 模拟 sender 以 ~50Hz 发 3s BotClaw
payload, 同时调用 /api/record start/stop, 验证 parquet 文件产出.
"""

import asyncio
import json
import math
import time
from pathlib import Path

import httpx
import websockets


async def sender(stop_at: float) -> int:
    n = 0
    async with websockets.connect("ws://localhost:8002/ws/teleop") as ws:
        t0 = time.time()
        while time.time() < stop_at:
            t = time.time() - t0
            payload = {
                "type": "joint_update",
                "robot_id": "so101-m1dod",
                "timestamp": time.time(),
                "joints": {
                    "1": math.sin(t) * 0.5,
                    "2": math.sin(t + 1) * 0.3,
                    "3": math.sin(t + 2) * 0.4,
                    "4": math.cos(t) * 0.2,
                    "5": math.cos(t + 1) * 0.6,
                    "6": math.cos(t + 2) * 0.4,
                },
                "servo_values": {"1": 2048, "2": 2048, "3": 2048, "4": 2048, "5": 2048, "6": 2048},
                "meta": {"fps": 50.0, "source": "m1dod-smoke"},
            }
            await ws.send(json.dumps(payload))
            n += 1
            # 让出事件循环, 不做显式 sleep (Windows asyncio.sleep 最小粒度 ~15ms
            # 会把 fps 压到 ~60Hz 以下); 服务端背压会天然节流.
            await asyncio.sleep(0)
    return n


async def ui_frame_counter(stop_at: float, out: list[int]) -> None:
    async with websockets.connect("ws://localhost:8002/ws/ui") as ws:
        n = 0
        while time.time() < stop_at:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            msg = json.loads(raw)
            if msg.get("type") == "joint_update":
                n += 1
        out.append(n)


async def main() -> None:
    # 1. UI 先连 + 计数
    stop_at = time.time() + 4.0
    ui_out: list[int] = []
    ui_task = asyncio.create_task(ui_frame_counter(stop_at, ui_out))

    await asyncio.sleep(0.3)

    # 2. 调 /api/record start
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.post("http://localhost:8002/api/record", json={"action": "start"})
        print(f"[start] {r.status_code} {r.json()}")
        assert r.status_code == 200

        # 3. sender 推 3s
        sent = await sender(stop_at - 1.0)
        print(f"sender pushed {sent} frames")

        # 4. /api/record stop
        r = await client.post("http://localhost:8002/api/record", json={"action": "stop"})
        stop_data = r.json()
        print(f"[stop] {r.status_code} {stop_data}")
        assert r.status_code == 200
        assert stop_data.get("success")
        assert stop_data.get("frames", 0) > 0

    await ui_task
    ui_frames = ui_out[0] if ui_out else 0
    print(f"UI received {ui_frames} frames in ~3.5s")

    # 5. 验 parquet
    filename = stop_data.get("filename")
    assert filename, f"no filename returned: {stop_data}"
    json_path = Path(__file__).resolve().parents[1] / "demos" / filename
    assert json_path.exists(), f"json not found: {json_path}"

    datasets_root = Path(__file__).resolve().parents[1] / "datasets"
    parquets: list[Path] = list(datasets_root.rglob("*.parquet")) if datasets_root.exists() else []
    # 只关心本次 session 的 parquet (按 mtime > 5s 内的保留)
    now = time.time()
    fresh = [p for p in parquets if (now - p.stat().st_mtime) < 30]
    print(f"fresh parquet under {datasets_root}: {[str(p.relative_to(datasets_root)) for p in fresh]}")
    parquets = fresh

    fps = ui_frames / 3.0
    assert fps > 30, f"fps {fps:.1f} < 30"
    assert parquets, f"no parquet produced under {datasets_root}"

    print(f"\nOK M1 DoD: UI fps ~{fps:.1f} Hz, {len(parquets)} parquet(s) under {datasets_root}")


if __name__ == "__main__":
    asyncio.run(main())
