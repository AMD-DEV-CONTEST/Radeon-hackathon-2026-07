"""M3.5 inference smoke.

1. /api/inference/models 能列出至少一个模型
2. /ws/compare/<key>?dataset_id=... 发回 compare_frame + compare_done + total_rmse 合理
"""

import asyncio
import json
import time

import httpx
import websockets


async def main() -> None:
    async with httpx.AsyncClient(timeout=10.0) as http:
        r = await http.get("http://localhost:8002/api/inference/models")
        assert r.status_code == 200, r.text
        models = r.json()["items"]
        assert models, "no local models; run smoke_m3_train first"
        m = models[0]
        key = m["model_key"]
        dsid = m["dataset_id"]
        assert dsid, f"model missing dataset_id: {m}"
        print(f"[1] model={key} dataset={dsid} rmse_train={m['metrics'].get('final_val_rmse_delta')}")

        r = await http.get(f"http://localhost:8002/api/inference/{key}/meta")
        assert r.status_code == 200
        print(f"[2] meta ok, algo={r.json()['algo']}")

    url = f"ws://localhost:8002/ws/compare/{key}?dataset_id={dsid}&fps=60"
    async with websockets.connect(url) as ws:
        meta = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        assert meta["type"] == "compare_meta", meta
        print(f"[3] compare_meta frame_count={meta['frame_count']}")

        frames = 0
        total_rmse = None
        start = time.time()
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=15)
            except asyncio.TimeoutError:
                break
            msg = json.loads(raw)
            if msg["type"] == "compare_frame":
                assert set(msg["gt"].keys()) == {"1", "2", "3", "4", "5", "6"}
                assert set(msg["pred"].keys()) == {"1", "2", "3", "4", "5", "6"}
                assert isinstance(msg["step_rmse"], float)
                frames += 1
                if frames >= 300:  # 够了不用等整个 dataset
                    break
            elif msg["type"] == "compare_done":
                total_rmse = msg["total_rmse"]
                print(f"[4] done total_rmse={total_rmse:.6f}")
                break
            elif msg["type"] == "error":
                raise RuntimeError(msg["message"])

        dt = time.time() - start
        print(f"[5] received {frames} compare_frame in {dt:.2f}s (~{frames/dt:.1f} Hz)")
        assert frames >= 50

    print("\nOK M3.5 inference smoke")


if __name__ == "__main__":
    asyncio.run(main())
