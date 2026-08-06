"""MedGlass web/glasses SIMULATOR.

Fallback that mimics the Mentra glasses stream from a laptop: captures audio
and video from the webcam and drives the MedGlass WebSocket endpoints, and
prints HUD updates. This is the reliable demo path when physical glasses or
the Mentra SDK are unavailable.

Usage:
    python client/simulator.py --audio --video

Endpoints mirrored (from server.py):
    WS /ws/audio  -> send 16kHz PCM chunks, receive transcripts
    WS /ws/video  -> send base64 JPEG frames, receive detection/OCR status
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time

import numpy as np
import websockets

from src.config import CONFIG
from src.utils import setup_logging

setup_logging()
LOG = logging.getLogger("medglass.simulator")

WS_BASE = "ws://{host}:{port}"


def now() -> float:
    return time.time()


class Simulator:
    def __init__(self, cfg: dict, ws_base: str, device: int = 0) -> None:
        self.cfg = cfg
        self.ws_base = ws_base
        self.device = device
        self._cap = None
        self._cam_enabled = False

    def _ensure_camera(self):
        if self._cap is None and self._cam_enabled:
            import cv2
            self._cap = cv2.VideoCapture(self.device)
            if not self._cap.isOpened():
                raise RuntimeError("could not open webcam")

    async def run_audio(self) -> None:
        uri = f"{self.ws_base}/ws/audio"
        LOG.info("opening audio ws to %s", uri)
        mic = self._get_mic()
        async with websockets.connect(uri) as ws:
            print("Audio streaming. Press Ctrl+C to stop.")
            while True:
                chunk = await asyncio.to_thread(mic.read_chunk)
                await ws.send(chunk)
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=0.01)
                    data = json.loads(msg)
                    print(f"<< transcript: {data.get('text')}")
                except asyncio.TimeoutError:
                    pass
                await asyncio.sleep(0)

    def _get_mic(self):
        try:
            import sounddevice as sd
        except ImportError:
            LOG.error("pip install sounddevice to stream mic audio")
            raise
        LOG.info("opening mic at %s Hz", self.cfg["sample_rate"])
        return _MicStream(sd, self.cfg["sample_rate"])

    async def run_video(self, fps: int = 5) -> None:
        import cv2
        self._cam_enabled = True
        self._ensure_camera()
        uri = f"{self.ws_base}/ws/video"
        interval = 1.0 / fps
        LOG.info("video streaming to %s at %s fps", uri, fps)
        async with websockets.connect(uri) as ws:
            while True:
                ok, frame = self._cap.read()
                if not ok:
                    break
                ok, jpeg = cv2.imencode(".jpg", frame,
                                        [cv2.IMWRITE_JPEG_QUALITY, 70])
                if not ok:
                    continue
                b64 = base64.b64encode(jpeg.tobytes()).decode("ascii")
                await ws.send(json.dumps({"type": "frame", "data": b64}))
                try:
                    msg = json.loads(await asyncio.wait_for(ws.recv(),
                                                            timeout=0.05))
                    if msg.get("detections"):
                        print(f"<< frame detections: {msg['detections']}")
                except asyncio.TimeoutError:
                    pass
                await asyncio.sleep(interval)


class _MicStream:
    def __init__(self, sd, sample_rate: int):
        self.sd = sd
        self.sample_rate = sample_rate
        self.chunk_bytes = sample_rate * 2  # 1 second of 16-bit mono
        self.stream = sd.RawInputStream(
            samplerate=sample_rate, channels=1, dtype="int16",
            blocksize=1600,
        )
        self.stream.start()

    def read_chunk(self) -> bytes:
        raw = self.stream.read(self.chunk_bytes // 2)  # frames
        return raw[0].tobytes()


def main() -> None:
    import base64  # noqa: F401 (used inside run_video)
    parser = argparse.ArgumentParser(description="MedGlass simulator")
    parser.add_argument("--host", default=CONFIG["host"])
    parser.add_argument("--port", type=int, default=CONFIG["port"])
    parser.add_argument("--audio", action="store_true", help="stream mic")
    parser.add_argument("--video", action="store_true", help="stream camera")
    parser.add_argument("--fps", type=int, default=5)
    args = parser.parse_args()

    if not (args.audio or args.video):
        parser.error("choose --audio and/or --video")

    ws_base = WS_BASE.format(host=args.host, port=args.port)
    sim = Simulator(CONFIG, ws_base)

    async def main_loop():
        tasks = []
        if args.audio:
            tasks.append(asyncio.create_task(sim.run_audio()))
        if args.video:
            tasks.append(asyncio.create_task(sim.run_video(args.fps)))
        try:
            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            pass

    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        print("\nsimulator stopped")


if __name__ == "__main__":
    main()