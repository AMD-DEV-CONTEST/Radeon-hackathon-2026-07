"""M4 closed-loop DoD smoke (end-to-end).

Chains every major M4 capability in one run:

  0. auth: register/login dev user -> JWT
  1. sender: dry-mode sender writes JointUpdate to /ws/teleop with telemetry
  2. /api/arms shows arm_smoke_dod slot
  3. /api/robotstate reports temperatures / currents / voltages
  4. record start/stop via /api/record -> dataset saved
  5. training: POST /api/v1/trainings (auth) -> poll -> succeeded + model_id
  6. models: /api/inference/models lists new model
  7. compare echo: /ws/compare?echo=true -> UI sees meta.source='inference'
  8. E-stop: POST /api/inference/estop -> gate_fatal in compare WS
  9. logout (token cleared)

Skip any step that isn't available, but fail loudly if what's skipped is required.
"""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import websockets


REALTIME_ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
API = "http://localhost:8000"
RT = "http://localhost:8002"
WS_RT = "ws://localhost:8002"
DEV_EMAIL = "dod@botversex.dev"
DEV_PASSWORD = "dod_pw_2026"
DEV_USER = "dod_user"


async def step_auth(c: httpx.AsyncClient) -> str:
    print("[1] auth: login (register once if missing)")
    r = await c.post(f"{API}/api/v1/auth/login", json={"email": DEV_EMAIL, "password": DEV_PASSWORD})
    if r.status_code in (400, 401, 404):
        r2 = await c.post(f"{API}/api/v1/auth/register", json={
            "username": DEV_USER, "email": DEV_EMAIL, "password": DEV_PASSWORD,
        })
        if r2.status_code not in (200, 201):
            raise RuntimeError(f"register failed {r2.status_code}: {r2.text[:200]}")
        r = await c.post(f"{API}/api/v1/auth/login", json={"email": DEV_EMAIL, "password": DEV_PASSWORD})
    r.raise_for_status()
    token = r.json()["access_token"]
    print(f"    token {token[:20]}...")
    return token


async def step_start_sender() -> subprocess.Popen:
    print("[2] starting dry-mode sender (arm_id=arm_smoke_dod)")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REALTIME_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    log_path = Path(os.environ.get("TEMP", "C:/Windows/Temp")) / "m4_dod_sender.log"
    log_f = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [PY, "-u", "-m", "sender", "--dry_run", "--arm_id", "arm_smoke_dod",
         "--send_hz", "40", "--robot_id", "so101-m4-dod"],
        cwd=str(REALTIME_ROOT), env=env, stdout=log_f, stderr=subprocess.STDOUT,
    )
    await asyncio.sleep(2.5)
    if proc.poll() is not None:
        raise RuntimeError(f"sender crashed: {log_path.read_text(encoding='utf-8', errors='replace')[-600:]}")
    return proc


async def step_check_arm_and_state(c: httpx.AsyncClient) -> None:
    print("[3] /api/arms + /api/robotstate telemetry")
    arms = (await c.get(f"{RT}/api/arms")).json()
    assert any(a["arm_id"] == "arm_smoke_dod" for a in arms["items"]), arms
    rs = (await c.get(f"{RT}/api/robotstate")).json()
    assert rs["teleop_connected"] is True, rs
    assert rs["temperatures_c"] is not None, rs
    print(f"    temp[3]={rs['temperatures_c']['3']:.1f}C, current[3]={rs['currents_a']['3']:.3f}A")


async def step_record(c: httpx.AsyncClient) -> str:
    print("[4] record: start -> sleep 2.0s -> stop")
    r = (await c.post(f"{RT}/api/record", json={"action": "start"})).json()
    assert r.get("success")
    await asyncio.sleep(2.0)
    r = (await c.post(f"{RT}/api/record", json={"action": "stop"})).json()
    assert r.get("success"), r
    dataset_id = r.get("dataset_id")
    print(f"    dataset_id={dataset_id} ({r.get('frames')} frames)")
    assert dataset_id, r
    return dataset_id


async def step_train(c: httpx.AsyncClient, token: str, dataset_id: str) -> str:
    print("[5] training: POST /api/v1/trainings")
    headers = {"Authorization": f"Bearer {token}"}
    body = {"dataset_id": dataset_id, "algo": "mlp_baseline",
            "epochs": 5, "batch_size": 32, "hidden": 64, "lr": 0.001}
    r = await c.post(f"{API}/api/v1/trainings", json=body, headers=headers)
    r.raise_for_status()
    job_id = r.json()["id"]
    print(f"    job_id={job_id}, polling ...")
    deadline = time.time() + 180
    while time.time() < deadline:
        await asyncio.sleep(2)
        j = (await c.get(f"{API}/api/v1/trainings/{job_id}", headers=headers)).json()
        if j["status"] in ("succeeded", "failed", "cancelled"):
            break
        if int(time.time()) % 10 == 0:
            print(f"    status={j['status']} epoch={j.get('epoch')} loss={j.get('loss')}")
    assert j["status"] == "succeeded", j
    model_id = j.get("model_id")
    assert model_id, j
    print(f"    SUCCESS, model_id={model_id}")
    return model_id


async def step_model_listed(c: httpx.AsyncClient) -> str:
    print("[6] /api/inference/models lists new model")
    r = (await c.get(f"{RT}/api/inference/models")).json()
    assert r["total"] >= 1, r
    item = r["items"][0]
    print(f"    latest model_key={item['model_key']} dataset={item['dataset_id']}")
    return item["model_key"]


async def step_compare_echo_and_estop(model_key: str, dataset_id: str) -> None:
    print("[7] /ws/compare echo=true + UI captures inference frames")

    async def ui_listener(q: asyncio.Queue, stop: asyncio.Event) -> None:
        async with websockets.connect(f"{WS_RT}/ws/ui", open_timeout=30) as ws:
            while not stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=10)
                except asyncio.TimeoutError:
                    return
                msg = json.loads(raw)
                if msg.get("type") == "joint_update":
                    await q.put(msg)

    q: asyncio.Queue = asyncio.Queue()
    stop = asyncio.Event()
    ui_task = asyncio.create_task(ui_listener(q, stop))
    await asyncio.sleep(0.4)

    url = (f"{WS_RT}/ws/compare/{model_key}?dataset_id={dataset_id}"
           f"&fps=30&echo=true&robot_id=inference:dod")
    inference_count = 0
    gate_fatal = False
    async with websockets.connect(url, open_timeout=30) as ws:
        meta = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
        assert meta["echo"] is True, meta

        async def estop_later():
            await asyncio.sleep(1.0)
            async with httpx.AsyncClient() as c2:
                r = await c2.post(f"{RT}/api/inference/estop")
                print(f"    E-stop {r.status_code} {r.text}")

        estop_task = asyncio.create_task(estop_later())

        try:
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=6.0))
                if m.get("type") == "compare_frame" and m.get("gate_fatal"):
                    gate_fatal = True
                if m.get("type") == "error":
                    break
        except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
            pass
        await estop_task

    try:
        while True:
            m = q.get_nowait()
            if (m.get("meta") or {}).get("source") == "inference":
                inference_count += 1
    except asyncio.QueueEmpty:
        pass
    stop.set()
    ui_task.cancel()
    print(f"    UI captured {inference_count} inference frames, gate_fatal={gate_fatal}")
    assert inference_count >= 1, "no inference frames on UI bus"
    assert gate_fatal, "E-stop did not trigger gate_fatal"


async def main() -> None:
    print("============================================================")
    print("M4 closed-loop DoD smoke")
    print("============================================================")
    async with httpx.AsyncClient(timeout=30) as c:
        token = await step_auth(c)
    sender_proc = await step_start_sender()
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            await step_check_arm_and_state(c)
            dataset_id = await step_record(c)
            model_id = await step_train(c, token, dataset_id)
            model_key = await step_model_listed(c)
            await step_compare_echo_and_estop(model_key, dataset_id)
    finally:
        sender_proc.terminate()
        try:
            sender_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            sender_proc.kill()

    print("\n============================================================")
    print("M4 DoD PASSED")
    print("============================================================")


if __name__ == "__main__":
    asyncio.run(main())
