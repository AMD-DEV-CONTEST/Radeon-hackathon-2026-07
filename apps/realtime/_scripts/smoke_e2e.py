"""完整 E2E 冒烟 (M1 验证):

realtime :8002 + api :8000 + (模拟 sender) 同时在跑, 走 api 的 auth + record
代理, sender 推 BotClaw payload, 停止后验证 parquet.
"""

import asyncio
import json
import math
import time
import uuid
from pathlib import Path

import httpx
import websockets

API = "http://localhost:8000"
RT = "http://localhost:8002"


async def sender(stop_at: float, robot_id: str) -> int:
    n = 0
    async with websockets.connect(f"ws://localhost:8002/ws/teleop") as ws:
        t0 = time.time()
        while time.time() < stop_at:
            t = time.time() - t0
            payload = {
                "type": "joint_update",
                "robot_id": robot_id,
                "timestamp": time.time(),
                "joints": {
                    "1": math.sin(t) * 0.5,
                    "2": math.sin(t + 1) * 0.3,
                    "3": math.sin(t + 2) * 0.4,
                    "4": math.cos(t) * 0.2,
                    "5": math.cos(t + 1) * 0.6,
                    "6": math.cos(t + 2) * 0.4,
                },
                "meta": {"fps": 100.0, "source": "e2e"},
            }
            await ws.send(json.dumps(payload))
            n += 1
            await asyncio.sleep(0)
    return n


async def main() -> None:
    async with httpx.AsyncClient(timeout=10.0) as http:
        # 1) register + login 以拿 token
        # username 不能有 "-", email 不能用 reserved TLD
        username = f"e2e_{uuid.uuid4().hex[:6]}"
        password = "e2e_smoke_pw_1"
        r = await http.post(
            f"{API}/api/v1/auth/register",
            json={"username": username, "email": f"{username}@example.com", "password": password, "full_name": "E2E"},
        )
        print(f"[register] {r.status_code}")
        assert r.status_code in (200, 201), r.text

        r = await http.post(
            f"{API}/api/v1/auth/login",
            json={"email": f"{username}@example.com", "password": password},
        )
        print(f"[login] {r.status_code}")
        assert r.status_code == 200, r.text
        token = r.json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}

        # 2) api /api/v1/record/start (透传到 realtime)
        r = await http.post(f"{API}/api/v1/record/start", headers=auth)
        print(f"[api record start] {r.status_code} {r.text[:120]}")
        assert r.status_code == 200, r.text

        # 3) sender 推 3s
        sent = await sender(time.time() + 3.0, robot_id="so101-e2e")
        print(f"sender pushed {sent} frames")

        # 4) stop
        r = await http.post(f"{API}/api/v1/record/stop", headers=auth)
        stop_data = r.json()
        print(f"[api record stop] {r.status_code} {stop_data}")
        assert r.status_code == 200
        assert stop_data.get("frames", 0) > 0

    # 5) parquet 验证
    filename = stop_data.get("filename")
    json_path = Path(__file__).resolve().parents[1] / "demos" / filename
    assert json_path.exists(), f"json missing: {json_path}"
    datasets_root = Path(__file__).resolve().parents[1] / "datasets"
    now = time.time()
    fresh = [p for p in datasets_root.rglob("*.parquet") if (now - p.stat().st_mtime) < 30]
    assert fresh, f"no fresh parquet under {datasets_root}"
    fps = sent / 3.0
    print(f"\nOK E2E: sender {sent} frames (~{fps:.0f} Hz), {len(fresh)} parquet(s):")
    for p in fresh:
        print(f"  - {p.relative_to(datasets_root)}")


if __name__ == "__main__":
    asyncio.run(main())
