#!/usr/bin/env python3
"""虚拟 Client：测试 AMD 云上的 OpenPI Policy Server。

检查项:
  1. HTTP /healthz 可达
  2. WebSocket 连接 + 随机 G1D 观测推理成功
  3. 返回 action 形状正确 (action_horizon, 16)
  4. amd-smi 显示 GPU 显存占用（同机测试时，模型加载后通常 > 5GB）

用法:
  cd /workspace/openpi && source .venv/bin/activate
  python self_scripts/infer/test_amd_policy_client.py
  python self_scripts/infer/test_amd_policy_client.py --host localhost --port 8000 --num-infer 3
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

import numpy as np
import websockets.sync.client
from openpi_client import msgpack_numpy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenPI AMD Policy Server 虚拟测试 Client")
    parser.add_argument("--host", default="localhost", help="Server 主机名或 IP")
    parser.add_argument("--port", type=int, default=8000, help="Server 端口")
    parser.add_argument(
        "--wss-url",
        default="",
        help="公网 WebSocket 地址（rc-tunnel），例如 wss://rc-xxx.radeon.firstdg.ai",
    )
    parser.add_argument(
        "--instruction",
        default="Organize and tidy the items on the table.",
        help="发送给模型的 prompt",
    )
    parser.add_argument("--num-infer", type=int, default=3, help="推理次数（含 1 次 warmup）")
    parser.add_argument("--action-horizon", type=int, default=10, help="期望 action chunk 长度")
    parser.add_argument("--action-dim", type=int, default=16, help="期望关节维度")
    parser.add_argument(
        "--wait-server",
        type=int,
        default=600,
        help="启动前等待 healthz 就绪的最长时间（秒）",
    )
    parser.add_argument(
        "--infer-timeout",
        type=int,
        default=600,
        help="单次推理 WebSocket 超时（秒，首次推理可能较慢）",
    )
    parser.add_argument("--skip-gpu-check", action="store_true", help="跳过 amd-smi GPU 检查")
    return parser.parse_args()


def wait_for_healthz(host: str, port: int, max_wait: int) -> None:
    url = f"http://{host}:{port}/healthz"
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                body = resp.read().decode().strip()
                if resp.status == 200 and body == "OK":
                    print(f"[OK] healthz: {url}")
                    return
        except (urllib.error.URLError, TimeoutError):
            pass
        print("[INFO] 等待 Server 就绪（可能正在首次 torch compile）...")
        time.sleep(5)
    raise RuntimeError(f"等待 healthz 超时 ({max_wait}s): {url}")


def wait_for_healthz_from_url(base_url: str, max_wait: int) -> None:
    url = f"{base_url.rstrip('/')}/healthz"
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                body = resp.read().decode().strip()
                if resp.status == 200 and body == "OK":
                    print(f"[OK] healthz: {url}")
                    return
        except (urllib.error.URLError, TimeoutError):
            pass
        print("[INFO] 等待公网 Server 就绪...")
        time.sleep(5)
    raise RuntimeError(f"等待 healthz 超时 ({max_wait}s): {url}")


def read_amd_gpu_stats() -> dict[str, float] | None:
    try:
        out = subprocess.check_output(["amd-smi"], text=True, stderr=subprocess.DEVNULL)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    stats: dict[str, float] = {}
    vram_match = re.search(r"(\d+)\s*/\s*(\d+)\s*MB", out)
    gfx_match = re.search(r"\|\s*(\d+)\s*%\s*\|\s*[\d.]+\s*\|\s*(\d+)\s*/\s*(\d+)\s*MB\s*\|", out)
    if vram_match:
        stats["vram_used_mb"] = float(vram_match.group(1))
        stats["vram_total_mb"] = float(vram_match.group(2))
    if gfx_match:
        stats["gfx_util_pct"] = float(gfx_match.group(1))
        stats["vram_used_mb"] = float(gfx_match.group(2))
        stats["vram_total_mb"] = float(gfx_match.group(3))
    return stats or None


def connect_policy_client(host: str, port: int, infer_timeout: int, wss_url: str = ""):
    if wss_url:
        uri = wss_url
    elif host.startswith("ws"):
        uri = host
    else:
        uri = f"ws://{host}:{port}"
    print(f"[INFO] 连接 WebSocket: {uri} (infer_timeout={infer_timeout}s)")
    ws = websockets.sync.client.connect(
        uri,
        compression=None,
        max_size=None,
        open_timeout=30,
        ping_interval=30,
        ping_timeout=infer_timeout,
        close_timeout=10,
    )
    packer = msgpack_numpy.Packer()
    metadata = msgpack_numpy.unpackb(ws.recv())
    return ws, packer, metadata


def infer_once(ws, packer, obs: dict) -> dict:
    ws.send(packer.pack(obs))
    response = ws.recv()
    if isinstance(response, str):
        raise RuntimeError(f"Server 返回错误:\n{response}")
    return msgpack_numpy.unpackb(response)


def make_g1d_observation(instruction: str) -> dict:
    """构造与 client_g1d_joint.py 一致的 G1D 观测格式。"""
    h, w = 480, 640
    return {
        "state": np.zeros(16, dtype=np.float32),
        "images": {
            "cam_left_high": np.random.randint(0, 256, size=(h, w, 3), dtype=np.uint8),
            "cam_left_wrist": np.random.randint(0, 256, size=(h, w, 3), dtype=np.uint8),
            "cam_right_wrist": np.random.randint(0, 256, size=(h, w, 3), dtype=np.uint8),
        },
        "prompt": instruction,
    }


def validate_actions(
    actions: np.ndarray,
    *,
    action_horizon: int,
    action_dim: int,
) -> None:
    actions = np.asarray(actions)
    if actions.shape != (action_horizon, action_dim):
        raise RuntimeError(f"action 形状错误: 期望 ({action_horizon}, {action_dim}), 实际 {actions.shape}")
    if not np.isfinite(actions).all():
        raise RuntimeError("action 含 NaN/Inf")


def main() -> int:
    args = parse_args()
    print("=" * 60)
    print("  OpenPI AMD Policy Server 虚拟测试 Client")
    print("=" * 60)
    host = args.host
    port = args.port
    health_host = "127.0.0.1"
    if args.wss_url:
        health_host = args.wss_url.replace("wss://", "https://").replace("ws://", "http://").rstrip("/")
        if not health_host.startswith("http"):
            health_host = f"https://{health_host.lstrip('/')}"
    print(f"  Server       : {args.wss_url or f'{host}:{port}'}")
    print(f"  Instruction  : {args.instruction}")
    print(f"  Num infer    : {args.num_infer}")
    print("=" * 60)

    if args.wss_url:
        wait_for_healthz_url = health_host
        wait_for_healthz_from_url(wait_for_healthz_url, args.wait_server)
    else:
        wait_for_healthz(host, port, args.wait_server)

    gpu_before = None if args.skip_gpu_check else read_amd_gpu_stats()
    if gpu_before is not None:
        print(
            f"[INFO] 当前 GPU: VRAM={gpu_before.get('vram_used_mb', '?')} MB, "
            f"GFX={gpu_before.get('gfx_util_pct', '?')}%"
        )
    elif not args.skip_gpu_check:
        print("[WARN] 未找到 amd-smi，跳过 GPU 显存检查")

    ws, packer, metadata = connect_policy_client(host, port, args.infer_timeout, args.wss_url)
    print(f"[OK] 已连接，server metadata: {metadata}")

    infer_ms: list[float] = []
    policy_ms: list[float] = []
    last_actions = np.zeros((args.action_horizon, args.action_dim), dtype=np.float32)

    try:
        for i in range(args.num_infer):
            obs = make_g1d_observation(args.instruction)
            t0 = time.perf_counter()
            result = infer_once(ws, packer, obs)
            client_ms = (time.perf_counter() - t0) * 1000
            infer_ms.append(client_ms)

            actions = np.asarray(result["actions"])
            validate_actions(
                actions,
                action_horizon=args.action_horizon,
                action_dim=args.action_dim,
            )
            last_actions = actions

            server_timing = result.get("server_timing", {})
            policy_timing = result.get("policy_timing", {})
            if "infer_ms" in policy_timing:
                policy_ms.append(float(policy_timing["infer_ms"]))

            server_infer = server_timing.get("infer_ms")
            policy_infer = policy_timing.get("infer_ms")
            tag = "warmup" if i == 0 else f"infer-{i}"
            if isinstance(server_infer, (int, float)) and isinstance(policy_infer, (int, float)):
                print(
                    f"[OK] {tag}: actions={actions.shape}, client={client_ms:.0f}ms, "
                    f"server={server_infer:.0f}ms, policy={policy_infer:.0f}ms"
                )
            else:
                print(f"[OK] {tag}: actions={actions.shape}, client={client_ms:.0f}ms")
    finally:
        ws.close()

    gpu_after = None if args.skip_gpu_check else read_amd_gpu_stats()
    gpu_ok = True
    if gpu_after is not None:
        vram_after = float(gpu_after.get("vram_used_mb", 0))
        print(
            f"[INFO] 推理后 GPU: VRAM={vram_after} MB, "
            f"GFX={gpu_after.get('gfx_util_pct', '?')}%"
        )
        if vram_after < 512:
            gpu_ok = False
            print("[FAIL] GPU 显存占用过低，Server 可能未使用 AMD GPU")
        else:
            print(f"[OK] GPU 显存占用 {vram_after:.0f} MB（full π0.5 推理通常 > 5GB）")

    avg_client = sum(infer_ms[1:] or infer_ms) / max(len(infer_ms[1:] or infer_ms), 1)
    avg_policy = sum(policy_ms[1:] or policy_ms) / max(len(policy_ms[1:] or policy_ms), 1) if policy_ms else 0.0

    print("-" * 60)
    print(f"  平均 client 往返延迟 : {avg_client:.0f} ms")
    if policy_ms:
        print(f"  平均 policy 推理耗时 : {avg_policy:.0f} ms")
    print(f"  action 示例 (第 1 帧): {last_actions[0, :4]} ...")

    if not gpu_ok:
        print("[RESULT] FAIL — GPU 检查未通过")
        return 1

    print("[RESULT] PASS — Server 推理正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
