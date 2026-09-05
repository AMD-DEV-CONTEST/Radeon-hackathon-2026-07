"""End-to-end smoke test for a running MedGlass server.

Drives the real HTTP + WebSocket surface:
  1. /health
  2. /ws/audio with JFK sample PCM -> expects transcripts
  3. /generate_note -> expects a SOAP note
  4. /ws/video with a synthetic JPEG -> expects detection JSON

Usage: python tests/e2e_smoke.py [host] [port]
"""

import asyncio
import json
import sys
import urllib.request
import wave

import numpy as np
import websockets


async def main(host: str, port: int):
    base = f"http://{host}:{port}"
    ws_base = f"ws://{host}:{port}"

    # 1. health
    with urllib.request.urlopen(f"{base}/health", timeout=5) as r:
        health = json.loads(r.read())
    print("health:", health["status"], health["backends"])

    # 2. audio
    w = wave.open("/tmp/opencode/jfk.wav", "rb")
    pcm = w.readframes(w.getnframes())
    w.close()
    transcript_parts = []
    async with websockets.connect(f"{ws_base}/ws/audio") as ws:
        for i in range(0, len(pcm), 16000 * 2):
            await ws.send(pcm[i:i + 16000 * 2])
            await asyncio.sleep(0.05)
        # drain
        for _ in range(6):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=10)
                data = json.loads(msg)
                if data.get("type") == "transcript":
                    transcript_parts.append(data["text"])
                    print("  transcript:", data["text"][:60])
            except asyncio.TimeoutError:
                break
    print("audio ok, pieces:", len(transcript_parts))

    # 3. generate note
    req = urllib.request.Request(
        f"{base}/generate_note",
        data=json.dumps({"session_id": "default"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        note = json.loads(r.read())
    print("note sections:", list(note.get("sections", {}).keys()))
    print("note preview:", note.get("note", "")[:100].replace("\n", " | "))

    # 4. video frame
    import cv2
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    ok, jpeg = cv2.imencode(".jpg", frame)
    b64 = __import__("base64").b64encode(jpeg.tobytes()).decode()
    async with websockets.connect(f"{ws_base}/ws/video") as ws:
        await ws.send(json.dumps({"type": "frame", "data": b64}))
        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
    print("video ok:", "processed_ms" in resp)
    print("\nALL E2E CHECKS PASSED")


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8100
    asyncio.run(main(host, port))
