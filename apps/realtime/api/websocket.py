"""
WebSocket 处理模块

关键设计: teleop (sender) 和 ui (浏览器) 用**分离**的连接池。
广播只发给 UI 池，避免 sender 收到自己发出的数据的回声
（回声会填满 sender 的 socket buffer，导致 websockets 库 keepalive ping timeout,
 报 "1011 keepalive ping timeout"）。
"""

import json
import time
from typing import Dict, Set, Optional
from fastapi import WebSocket
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class JointData:
    """关节数据 (数字关节名)"""
    j1: float = 0.0  # shoulder_pan
    j2: float = 0.0  # shoulder_lift
    j3: float = 0.0  # elbow_flex
    j4: float = 0.0  # wrist_flex
    j5: float = 0.0  # wrist_roll
    j6: float = 0.0  # gripper
    timestamp: float = field(default_factory=time.time)


class ConnectionManager:
    """WebSocket 连接管理器

    teleop_connections: 上游数据源 (sender)，只接收，不广播给它们
    ui_connections:     下游消费者 (浏览器)，接收来自 teleop 的广播
    """

    def __init__(self):
        self.teleop_connections: Set[WebSocket] = set()
        self.ui_connections: Set[WebSocket] = set()
        self.latest_data: Optional[JointData] = None
        self.record_buffer: list = []
        self.is_recording: bool = False
        self.clients: Dict[str, dict] = {}
        # BotClaw v0.1 meta — 由 /ws/teleop 的入站帧更新
        self.last_robot_id: str = "so101-001"
        self.last_meta: Optional[dict] = None
        # v0.4 telemetry 透传: 只填拿得到的, 其他 None
        self.last_servo_values: Optional[dict] = None
        self.last_temperatures: Optional[dict] = None
        self.last_currents: Optional[dict] = None
        self.last_voltages: Optional[dict] = None
        # fps_observed 估计: 滑动窗口
        self._fps_samples: list[float] = []
        # M5: global emergency-stop flag. Set True by POST /api/inference/estop;
        # cleared only by POST /api/inference/resume. Reflected in /ws/robotstate
        # so external followers can react without waiting for a compare_ws frame.
        self.estop: bool = False
        self.estop_reason: Optional[str] = None
        # M8.2: camera capture during recording
        self._camera_capture = None       # cv2.VideoCapture or None
        self._camera_device: str = "0"
        self._record_with_camera: bool = False

    async def connect_teleop(self, websocket: WebSocket, client_id: str) -> None:
        await websocket.accept()
        self.teleop_connections.add(websocket)
        self.clients[client_id] = {
            "kind": "teleop",
            "connected_at": datetime.now().isoformat(),
        }
        print(f"[WS] Teleop connected: {client_id} (teleop={len(self.teleop_connections)}, ui={len(self.ui_connections)})")

    async def connect_ui(self, websocket: WebSocket, client_id: str) -> None:
        await websocket.accept()
        self.ui_connections.add(websocket)
        self.clients[client_id] = {
            "kind": "ui",
            "connected_at": datetime.now().isoformat(),
        }
        print(f"[WS] UI connected: {client_id} (teleop={len(self.teleop_connections)}, ui={len(self.ui_connections)})")

    def disconnect(self, websocket: WebSocket, client_id: Optional[str] = None) -> None:
        self.teleop_connections.discard(websocket)
        self.ui_connections.discard(websocket)
        if client_id:
            self.clients.pop(client_id, None)
        print(f"[WS] Disconnected: {client_id or 'anonymous'}")

    # ------ 兼容旧代码 (如果外部仍在调用 manager.connect / manager.broadcast) ------
    @property
    def active_connections(self) -> Set[WebSocket]:
        return self.teleop_connections | self.ui_connections

    async def broadcast(self, data: dict) -> None:
        """仅广播给 UI 连接池, 绝不回发给 teleop (避免 sender 收到回声)"""
        if not self.ui_connections:
            return

        message = json.dumps(data)
        disconnected = []
        for conn in self.ui_connections:
            try:
                await conn.send_text(message)
            except Exception:
                disconnected.append(conn)

        for conn in disconnected:
            self.ui_connections.discard(conn)

    def update_data(self, joint_data: JointData) -> None:
        """更新最新数据 + 处理录制缓冲 + 同步相机帧"""
        prev = self.latest_data
        self.latest_data = joint_data
        if prev is not None:
            dt = joint_data.timestamp - prev.timestamp
            if 0 < dt < 2.0:
                self._fps_samples.append(1.0 / dt)
                if len(self._fps_samples) > 60:
                    self._fps_samples = self._fps_samples[-60:]
        if self.is_recording:
            frame_entry: dict = {
                "joints": {
                    "1": joint_data.j1,
                    "2": joint_data.j2,
                    "3": joint_data.j3,
                    "4": joint_data.j4,
                    "5": joint_data.j5,
                    "6": joint_data.j6,
                },
                "timestamp": joint_data.timestamp,
            }
            if self._record_with_camera and self._camera_capture is not None:
                frame_entry["image_jpeg"] = self._grab_camera_frame()
            self.record_buffer.append(frame_entry)

    def _grab_camera_frame(self) -> Optional[bytes]:
        """Grab a single JPEG from the active camera capture (blocking, fast)."""
        if self._camera_capture is None:
            return None
        try:
            ok, frame = self._camera_capture.read()
            if not ok or frame is None:
                return None
            import cv2
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            return bytes(buf)
        except Exception:
            return None

    def start_recording(self, camera_device: Optional[str] = None) -> None:
        self.is_recording = True
        self.record_buffer = []
        self._record_with_camera = camera_device is not None
        if self._record_with_camera:
            self._camera_device = camera_device  # type: ignore[assignment]
            self._open_camera_for_recording()
        print(f"[REC] Recording started (camera={'ON' if self._record_with_camera else 'OFF'})")

    def _open_camera_for_recording(self) -> None:
        try:
            import cv2
            if isinstance(self._camera_device, str) and self._camera_device.isdigit():
                dev = f"/dev/video{int(self._camera_device)}"
            elif isinstance(self._camera_device, int):
                dev = f"/dev/video{self._camera_device}"
            else:
                dev = self._camera_device
            cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
            if not cap.isOpened():
                try:
                    cap.release()
                except Exception:
                    pass
                cap = cv2.VideoCapture(dev)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                self._camera_capture = cap
                print(f"[REC] Camera opened: {self._camera_device} ({dev})")
            else:
                print(f"[REC] WARNING: cannot open camera {self._camera_device} ({dev})")
                self._camera_capture = None
        except Exception as exc:
            print(f"[REC] Camera open error: {exc}")
            self._camera_capture = None

    def stop_recording(self) -> list:
        self.is_recording = False
        if self._camera_capture is not None:
            try:
                self._camera_capture.release()
            except Exception:
                pass
            self._camera_capture = None
        self._record_with_camera = False
        data = self.record_buffer
        self.record_buffer = []
        cam_count = sum(1 for f in data if f.get("image_jpeg"))
        print(f"[REC] Recording stopped, {len(data)} frames ({cam_count} with images)")
        return data

    def fps_observed(self) -> Optional[float]:
        if not self._fps_samples:
            return None
        return sum(self._fps_samples) / len(self._fps_samples)


# 全局单例
manager = ConnectionManager()
