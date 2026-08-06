"""M2 冒烟: 录一条 -> /api/v1/datasets 列表 -> 详情 + stats -> 评分 > 0."""

import asyncio
import json
import math
import time
import uuid

import httpx
import websockets

API = "http://localhost:8000"


async def sender(stop_at: float, robot_id: str) -> int:
    n = 0
    async with websockets.connect("ws://localhost:8002/ws/teleop") as ws:
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
                "meta": {"fps": 100.0, "source": "m2-smoke"},
            }
            await ws.send(json.dumps(payload))
            n += 1
            await asyncio.sleep(0)
    return n


async def main() -> None:
    async with httpx.AsyncClient(timeout=15.0) as http:
        u = f"m2_{uuid.uuid4().hex[:6]}"
        pw = "m2_smoke_pw_1"
        r = await http.post(
            f"{API}/api/v1/auth/register",
            json={"username": u, "email": f"{u}@example.com", "password": pw, "full_name": "M2"},
        )
        assert r.status_code in (200, 201), r.text
        r = await http.post(
            f"{API}/api/v1/auth/login",
            json={"email": f"{u}@example.com", "password": pw},
        )
        assert r.status_code == 200
        auth = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # 1) 开始录制
        r = await http.post(f"{API}/api/v1/record/start", headers=auth)
        assert r.status_code == 200

        # 2) 推 3s 帧
        sent = await sender(time.time() + 3.0, robot_id="so101-m2")
        print(f"sender pushed {sent} frames")

        # 3) 停止录制
        r = await http.post(f"{API}/api/v1/record/stop", headers=auth)
        stop = r.json()
        print(f"[stop] {r.status_code} frames={stop.get('frames')} dataset_id={stop.get('dataset_id')}")
        assert r.status_code == 200
        dsid = stop.get("dataset_id")
        assert dsid, f"no dataset_id in stop response: {stop}"

        # 4) 列表
        r = await http.get(f"{API}/api/v1/datasets", headers=auth)
        print(f"[list] {r.status_code} total={r.json().get('total')} storage_root={r.json().get('storage_root')}")
        assert r.status_code == 200
        listed_ids = [x["dataset_id"] for x in r.json()["items"]]
        assert dsid in listed_ids, f"{dsid} not in {listed_ids[:5]}"

        # 5) 详情
        r = await http.get(f"{API}/api/v1/datasets/{dsid}", headers=auth)
        assert r.status_code == 200
        detail = r.json()
        print(f"[detail] frames={detail['frame_count']} duration={detail['duration_s']:.2f} q={detail['quality_score']} flags={detail['flags']}")
        assert detail["frame_count"] > 0
        assert detail["quality_score"] is not None

        # 6) stats
        r = await http.get(f"{API}/api/v1/datasets/{dsid}/stats", headers=auth)
        assert r.status_code == 200
        s = r.json()
        joints = s["stats"].get("joints", {})
        print(f"[stats] q={s['quality_score']} joint_keys={list(joints.keys())}")
        assert joints, f"no joint stats: {s}"

        # 7) recompute
        r = await http.get(f"{API}/api/v1/datasets/{dsid}/stats?recompute=true", headers=auth)
        assert r.status_code == 200

        print(f"\nOK M2.4: dataset {dsid} registered with quality_score={detail['quality_score']}")


if __name__ == "__main__":
    asyncio.run(main())
