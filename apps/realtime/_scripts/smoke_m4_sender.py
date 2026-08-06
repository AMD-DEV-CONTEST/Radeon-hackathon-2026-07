"""M4.1 smoke: new apps.realtime.sender package in dry mode.

Starts sender subprocess (dry_run, no hardware needed), then:
1. /ws/ui receives joint_update with meta.source=leader_arm
2. /api/robotstate reflects temperatures_c / currents_a / voltages_v
3. /api/arms lists the sender's arm_id
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


async def ui_grab(frames_target: int = 30) -> list[dict]:
    collected: list[dict] = []
    async with websockets.connect("ws://localhost:8002/ws/ui", open_timeout=15) as ws:
        deadline = time.time() + 15
        while len(collected) < frames_target and time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
            except asyncio.TimeoutError:
                break
            msg = json.loads(raw)
            if msg.get("type") == "joint_update":
                collected.append(msg)
    return collected


async def main() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REALTIME_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [PY, "-u", "-m", "sender", "--dry_run", "--arm_id", "arm_smoke", "--send_hz", "30", "--robot_id", "so101-smoke-m41"]
    print(f"[0] launching sender: {' '.join(cmd)}")
    log_path = Path(os.environ.get("TEMP", "C:/Windows/Temp")) / "m41_sender.log"
    log_f = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(cmd, cwd=str(REALTIME_ROOT), env=env, stdout=log_f, stderr=subprocess.STDOUT)
    try:
        await asyncio.sleep(3.0)  # let sender connect + send a few frames
        if proc.poll() is not None:
            log_f.flush()
            log_f.close()
            tail = Path(log_path).read_text(encoding="utf-8", errors="replace")[-2000:]
            raise RuntimeError(f"sender exited early: {tail}")

        frames = await ui_grab(frames_target=20)
        print(f"[1] UI received {len(frames)} joint_update frames")
        if len(frames) < 5:
            log_f.flush()
            print("--- sender.log tail ---")
            print(Path(log_path).read_text(encoding="utf-8", errors="replace")[-2000:])
            print("--- end ---")
        assert len(frames) >= 5, f"too few frames: {len(frames)}"

        f = frames[-1]
        assert f["robot_id"] == "so101-smoke-m41", f
        assert (f.get("meta") or {}).get("source") == "leader_arm", f
        assert set(f["joints"].keys()) == {"1", "2", "3", "4", "5", "6"}
        print(f"    sample joint 1 = {f['joints']['1']:.3f} rad, servo = {f['servo_values']['1']}")

        async with httpx.AsyncClient() as c:
            rs = (await c.get("http://localhost:8002/api/robotstate", timeout=10)).json()
            assert rs["teleop_connected"] is True
            assert rs["robot_id"] == "so101-smoke-m41", rs
            assert rs["temperatures_c"] is not None, rs
            assert rs["currents_a"] is not None, rs
            assert rs["voltages_v"] is not None, rs
            print(f"[2] RobotState telemetry: temp[1]={rs['temperatures_c']['1']:.1f}C, "
                  f"current[1]={rs['currents_a']['1']:.3f}A, volt[1]={rs['voltages_v']['1']:.1f}V")

            arms = (await c.get("http://localhost:8002/api/arms", timeout=10)).json()
            arm_ids = {a["arm_id"] for a in arms["items"]}
            assert "arm_smoke" in arm_ids, arms
            smoke_arm = next(a for a in arms["items"] if a["arm_id"] == "arm_smoke")
            assert smoke_arm["teleop"] >= 1, arms
            print(f"[3] /api/arms lists arm_smoke with teleop={smoke_arm['teleop']}")

        print("\nOK M4.1 new sender package (dry mode) smoke")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        try:
            log_f.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
