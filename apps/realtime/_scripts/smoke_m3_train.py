"""M3.2 冒烟: 挑一个已有数据集 -> POST /trainings -> 轮询到 succeeded -> 看 /models 里出现新模型."""

import asyncio
import time
import uuid
from pathlib import Path

import httpx


API = "http://localhost:8000"


async def main() -> None:
    async with httpx.AsyncClient(timeout=30.0) as http:
        u = f"m3_{uuid.uuid4().hex[:6]}"
        pw = "m3_train_pw_1"
        r = await http.post(f"{API}/api/v1/auth/register", json={"username": u, "email": f"{u}@example.com", "password": pw, "full_name": "M3"})
        assert r.status_code in (200, 201), r.text
        r = await http.post(f"{API}/api/v1/auth/login", json={"email": f"{u}@example.com", "password": pw})
        assert r.status_code == 200
        auth = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # 拿一个数据集
        r = await http.get(f"{API}/api/v1/datasets", headers=auth)
        assert r.status_code == 200
        items = r.json()["items"]
        assert items, "no datasets; run smoke_m2_dod first"
        # 挑 frame_count 最大那个
        ds = max(items, key=lambda x: x.get("frame_count") or 0)
        dsid = ds["dataset_id"]
        print(f"[1] using dataset {dsid} frames={ds['frame_count']}")

        # 发任务
        r = await http.post(
            f"{API}/api/v1/trainings",
            headers=auth,
            json={"dataset_id": dsid, "algo": "mlp_baseline", "epochs": 5, "batch_size": 64, "lr": 1e-3, "hidden": 32},
        )
        assert r.status_code == 201, r.text
        job = r.json()
        jid = job["id"]
        print(f"[2] queued job {jid} status={job['status']} pid={job['pid']}")

        # 轮询最多 120s
        deadline = time.time() + 120
        last_status = None
        while time.time() < deadline:
            r = await http.get(f"{API}/api/v1/trainings/{jid}", headers=auth)
            assert r.status_code == 200
            j = r.json()
            if j["status"] != last_status or (j["epoch"] and j["epoch"] != (job.get("epoch") if job else 0)):
                print(f"  status={j['status']} epoch={j['epoch']}/{j['total_epochs']} progress={j['progress_pct']:.1f}% loss={j['loss']}")
                last_status = j["status"]
                job = j
            if j["status"] in ("succeeded", "failed", "cancelled"):
                break
            await asyncio.sleep(1.5)

        assert j["status"] == "succeeded", f"job did not succeed: {j}"
        assert j["model_id"], "no model_id attached"
        print(f"[3] job succeeded, model_id={j['model_id']}")

        # 模型列表
        r = await http.get(f"{API}/api/v1/models", headers=auth)
        assert r.status_code == 200
        models = r.json()["items"]
        found = [m for m in models if m["id"] == j["model_id"]]
        assert found, f"model {j['model_id']} not in /models"
        m = found[0]
        print(f"[4] model {m['model_key']} algo={m['algo']} size={m['size_bytes']} rmse={m['metrics'].get('final_val_rmse_delta')}")

        # checkpoint 落地
        ckpt = Path(m["checkpoint_path"])
        assert ckpt.exists(), f"checkpoint missing: {ckpt}"
        print(f"[5] checkpoint {ckpt.name} on disk, {ckpt.stat().st_size} bytes")

        print("\n========== M3.2 trainer smoke OK ==========")


if __name__ == "__main__":
    asyncio.run(main())
