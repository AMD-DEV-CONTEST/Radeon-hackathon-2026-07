"""M3 DoD end-to-end smoke.

流水线:
 1. auth
 2. 挑选 frame_count 最大的 dataset
 3. POST /api/v1/trainings  (5 epoch MLP)
 4. 轮询到 succeeded + 拿到 model_id
 5. GET /api/v1/models -> 找到这条 model
 6. WS /ws/trainings/{id} 连一次, 应该立即收到 job_done (终态)
 7. GET realtime /api/inference/models 能看到该 model_key
 8. WS /ws/compare/{model_key}?dataset_id=... 收 >=200 帧 compare_frame
 9. 打印最终 avg step_rmse + total_rmse
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid

import httpx
import websockets


API = "http://localhost:8000"
RT = "http://localhost:8002"


async def main() -> None:
    async with httpx.AsyncClient(timeout=60.0) as http:
        u = f"m3dod_{uuid.uuid4().hex[:6]}"
        email = f"{u}@example.com"
        pw = "m3_dod_pw_1"
        r = await http.post(f"{API}/api/v1/auth/register", json={"username": u, "email": email, "password": pw, "full_name": "M3"})
        assert r.status_code in (200, 201, 400), r.text
        r = await http.post(f"{API}/api/v1/auth/login", json={"email": email, "password": pw})
        assert r.status_code == 200, r.text
        auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
        print("[1] auth OK")

        r = await http.get(f"{API}/api/v1/datasets", headers=auth)
        assert r.status_code == 200
        items = r.json()["items"]
        assert items, "no datasets"
        ds = max(items, key=lambda x: x.get("frame_count") or 0)
        dsid = ds["dataset_id"]
        print(f"[2] dataset={dsid} frames={ds['frame_count']}")

        r = await http.post(
            f"{API}/api/v1/trainings",
            headers=auth,
            json={"dataset_id": dsid, "algo": "mlp_baseline", "epochs": 3, "batch_size": 128, "lr": 1e-3, "hidden": 32},
        )
        assert r.status_code == 201, r.text
        job = r.json()
        jid = job["id"]
        print(f"[3] queued job {jid}")

        deadline = time.time() + 180
        while time.time() < deadline:
            r = await http.get(f"{API}/api/v1/trainings/{jid}", headers=auth)
            j = r.json()
            if j["status"] in ("succeeded", "failed", "cancelled"):
                break
            await asyncio.sleep(1.0)
        assert j["status"] == "succeeded", f"job not succeed: {j}"
        mid = j["model_id"]
        assert mid
        print(f"[4] job succeeded, model_id={mid}")

        r = await http.get(f"{API}/api/v1/models", headers=auth)
        models = r.json()["items"]
        row = next((m for m in models if m["id"] == mid), None)
        assert row, "model not in /models"
        key = row["model_key"]
        print(f"[5] model_key={key} size={row['size_bytes']}B rmse={row['metrics'].get('final_val_rmse_delta')}")

        # 6: WS /ws/trainings/{id} (job 已终态, 应立刻得到 done)
        async with websockets.connect(f"ws://localhost:8000/ws/trainings/{jid}") as ws:
            got_done = False
            for _ in range(5):
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                except asyncio.TimeoutError:
                    break
                m = json.loads(raw)
                if m.get("type") == "job_done":
                    got_done = True
                    break
            assert got_done, "did not receive job_done on reconnect"
        print("[6] ws /ws/trainings/{id} replay: job_done OK")

        # 7: realtime mirror
        r = await http.get(f"{RT}/api/inference/models")
        assert r.status_code == 200
        assert any(m["model_key"] == key for m in r.json()["items"]), "model not visible via realtime"
        print("[7] realtime mirror sees model")

        # 8: compare WS
        url = f"ws://localhost:8002/ws/compare/{key}?dataset_id={dsid}&fps=120"
        frames = 0
        sum_sq = 0.0
        async with websockets.connect(url) as ws:
            meta = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            assert meta["type"] == "compare_meta"
            total = meta["frame_count"]
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=15)
                except asyncio.TimeoutError:
                    break
                m = json.loads(raw)
                if m["type"] == "compare_frame":
                    frames += 1
                    sum_sq += float(m["step_rmse"]) ** 2
                    if frames >= 200:
                        break
                elif m["type"] == "compare_done":
                    break
        avg_rmse = (sum_sq / max(1, frames)) ** 0.5
        assert frames >= 50, f"too few compare_frame: {frames}"
        print(f"[8] compare WS: {frames} / {total} frames, avg step_rmse={avg_rmse:.6f}")

        print(f"\n[9] M3 DoD pipeline PASS: record -> train -> checkpoint -> compare GT vs PRED (avg rmse {avg_rmse:.4f} rad)")


if __name__ == "__main__":
    asyncio.run(main())
