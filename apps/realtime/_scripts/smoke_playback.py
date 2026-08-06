"""M2.5 playback 冒烟: 取一个 dataset, GET meta + WS 收 30Hz 回放 1s."""

import asyncio
import json
import time

import httpx
import websockets


async def main() -> None:
    async with httpx.AsyncClient(timeout=10.0) as http:
        # 随便挑一个 realtime 磁盘上的数据集
        from pathlib import Path
        ds_root = Path(__file__).resolve().parents[1] / "datasets"
        candidates = [d.name for d in ds_root.iterdir() if d.is_dir() and d.name.startswith("recording_")]
        assert candidates, f"no datasets under {ds_root}"
        dsid = sorted(candidates)[-1]
        print(f"Using dataset: {dsid}")

        r = await http.get(f"http://localhost:8002/api/playback/{dsid}/meta")
        print(f"[meta] {r.status_code} {r.json()}")
        assert r.status_code == 200

    async with websockets.connect(f"ws://localhost:8002/ws/playback/{dsid}?fps=30") as ws:
        n = 0
        got_meta = False
        start = time.time()
        while time.time() - start < 1.5:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                break
            msg = json.loads(raw)
            if msg["type"] == "playback_meta":
                got_meta = True
                continue
            if msg["type"] == "joint_update":
                assert set(msg["joints"].keys()) == {"1", "2", "3", "4", "5", "6"}
                n += 1
            if msg["type"] == "playback_done":
                break
        assert got_meta
        assert n >= 15, f"expected ~30 frames in 1s, got {n}"
        print(f"OK playback: got {n} joint_update frames @30fps in 1s")


if __name__ == "__main__":
    asyncio.run(main())
