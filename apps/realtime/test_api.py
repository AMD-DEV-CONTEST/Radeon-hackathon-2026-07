#!/usr/bin/env python3
"""
测试 Botclaw API
模拟发送关节数据到 WebSocket
"""

import asyncio
import json
import time
import websockets
import random


async def test_api():
    """测试 WebSocket 连接和 API"""
    ws_url = "ws://localhost:8001/ws/teleop"

    print("=" * 50)
    print("Testing Botclaw API")
    print("=" * 50)
    print(f"Connecting to: {ws_url}")

    try:
        async with websockets.connect(ws_url) as ws:
            print("[OK] Connected!")

            # 发送测试数据
            for i in range(30):
                data = {
                    "joint_positions": {
                        "shoulder_pan": random.uniform(-0.5, 0.5),
                        "shoulder_lift": random.uniform(-1.0, 1.0),
                        "elbow_flex": random.uniform(-1.0, 1.0),
                        "wrist_flex": random.uniform(-0.5, 0.5),
                        "wrist_roll": random.uniform(-0.5, 0.5),
                        "gripper": random.uniform(-0.2, 0.2),
                    },
                    "servo_values": {
                        "shoulder_pan": int(random.uniform(1800, 2200)),
                        "shoulder_lift": int(random.uniform(1800, 2200)),
                        "elbow_flex": int(random.uniform(1800, 2200)),
                        "wrist_flex": int(random.uniform(1800, 2200)),
                        "wrist_roll": int(random.uniform(1800, 2200)),
                        "gripper": int(random.uniform(2000, 2100)),
                    }
                }

                await ws.send(json.dumps(data))
                print(f"[{i+1}] Sent: shoulder_pan={data['joint_positions']['shoulder_pan']:.2f}")
                await asyncio.sleep(0.1)

            print("[OK] Test completed!")

    except Exception as e:
        print(f"[ERR] {e}")


if __name__ == "__main__":
    asyncio.run(test_api())
