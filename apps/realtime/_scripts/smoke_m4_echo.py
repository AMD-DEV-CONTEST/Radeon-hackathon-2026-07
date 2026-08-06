"""M4.4 smoke: compare WS echo=true 时广播到 /ws/ui, 安全闸正常, E-stop 可用.

步骤:
1. 连 /ws/ui 当订阅者
2. 并行开 /ws/compare/{key}?echo=true&robot_id=inference:x
3. 断言 UI 至少收到一帧 joint_update, meta.source='inference', meta.model_key 对
4. 断言 compare_frame 有 safe_pred + clamped 字段
5. 打印 clamped 次数作观察 (不强校验, 因为 baseline 模型训好了一般不触发 clamp)
"""

import asyncio
import json

import websockets

from pathlib import Path
import sys

# 靠本地 disk 拿一个 model_key. 避免依赖 API 鉴权.
def pick_local_model() -> tuple[str, str]:
    models_dir = Path(__file__).resolve().parents[1] / "models"
    candidates = sorted(models_dir.glob("*/model.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise SystemExit("no local model; run smoke_m3_train first")
    meta = json.loads(candidates[0].read_text(encoding="utf-8"))
    return meta["model_key"], meta["dataset_id"]


async def ui_listener(recv_queue: asyncio.Queue, stop_event: asyncio.Event) -> None:
    async with websockets.connect("ws://localhost:8002/ws/ui", open_timeout=30) as ws:
        while not stop_event.is_set():
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=15)
            except asyncio.TimeoutError:
                return
            msg = json.loads(raw)
            await recv_queue.put(msg)


async def compare_echo(model_key: str, dataset_id: str, frames_target: int) -> list[dict]:
    url = (
        f"ws://localhost:8002/ws/compare/{model_key}"
        f"?dataset_id={dataset_id}&fps=60&echo=true&robot_id=inference:{model_key}"
    )
    collected: list[dict] = []
    async with websockets.connect(url, open_timeout=30) as ws:
        meta = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
        assert meta["type"] == "compare_meta", meta
        assert meta["echo"] is True, meta
        while len(collected) < frames_target:
            raw = await asyncio.wait_for(ws.recv(), timeout=15)
            m = json.loads(raw)
            if m["type"] == "compare_frame":
                collected.append(m)
            elif m["type"] == "error":
                raise RuntimeError(m["message"])
    return collected


async def estop_test(model_key: str, dataset_id: str) -> None:
    import httpx

    async def client():
        url = (
            f"ws://localhost:8002/ws/compare/{model_key}"
            f"?dataset_id={dataset_id}&fps=30&echo=true&robot_id=inference:estop-test"
        )
        async with websockets.connect(url, open_timeout=30) as ws:
            _ = await ws.recv()  # meta
            got_fatal = False
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                    return got_fatal
                m = json.loads(raw)
                if m.get("gate_fatal"):
                    got_fatal = True
                if m.get("type") == "error":
                    return got_fatal

    task = asyncio.create_task(client())
    await asyncio.sleep(0.5)
    async with httpx.AsyncClient() as http:
        r = await http.post("http://localhost:8002/api/inference/estop")
        assert r.status_code == 200, r.text
        body = r.json()
        print(f"  E-stop rest returned: {body}")
        assert body["stopped_sessions"] >= 1
    got_fatal = await asyncio.wait_for(task, timeout=5.0)
    assert got_fatal, "expected gate_fatal=True after rest E-stop"
    print("[3] E-stop OK, gate_fatal received in frontend")


async def main() -> None:
    model_key, dataset_id = pick_local_model()
    print(f"[0] model={model_key} dataset={dataset_id}")

    # 1+2 并行: UI 订阅 + compare echo
    recv_q: asyncio.Queue = asyncio.Queue()
    stop_ev = asyncio.Event()
    ui_task = asyncio.create_task(ui_listener(recv_q, stop_ev))

    await asyncio.sleep(0.3)  # 先让 ui 连上
    compare_task = asyncio.create_task(compare_echo(model_key, dataset_id, frames_target=80))
    frames = await compare_task
    print(f"[1] compare WS echo=true got {len(frames)} frames")

    # 拿 UI 上第一个 inference 源的 joint_update
    got_inference = 0
    clamp_count = 0
    inference_msg = None
    try:
        while True:
            m = await asyncio.wait_for(recv_q.get(), timeout=2.0)
            if m.get("type") != "joint_update":
                continue
            src = (m.get("meta") or {}).get("source")
            if src == "inference":
                got_inference += 1
                inference_msg = m
                clamp = (m.get("meta") or {}).get("clamped") or []
                clamp_count += len(clamp)
    except asyncio.TimeoutError:
        pass
    stop_ev.set()
    ui_task.cancel()

    assert got_inference > 0, "UI did not receive any inference joint_update"
    print(f"[2] UI got {got_inference} inference joint_update (clamped total {clamp_count})")
    assert inference_msg is not None
    assert inference_msg["meta"]["model_key"] == model_key
    assert set(inference_msg["joints"].keys()) == {"1", "2", "3", "4", "5", "6"}

    # 校验 compare_frame 额外字段
    assert "safe_pred" in frames[0], frames[0]
    assert "clamped" in frames[0], frames[0]

    # 3. E-stop
    await estop_test(model_key, dataset_id)

    print("\nOK M4.4 echo + safety gate + E-stop smoke")


if __name__ == "__main__":
    asyncio.run(main())
