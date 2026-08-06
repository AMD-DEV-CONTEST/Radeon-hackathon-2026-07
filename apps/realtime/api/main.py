"""
Botclaw API 服务
FastAPI + WebSocket 后端
"""

import asyncio
import os
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel, ValidationError

from .websocket import manager, JointData
from .playback import router as playback_router
from .datasets import router as datasets_router
from .inference import router as inference_router
from .robotstate import router as robotstate_router
from .camera import router as camera_router
from .vision_inference import router as vision_inference_router
from .setup import router as setup_router
from .teleop_control import router as teleop_control_router
from .record_control import router as record_control_router
from .hf import router as hf_router
from .calibrate_control import router as calibrate_control_router
from .reachy_proxy import router as reachy_proxy_router, ws_router as reachy_ws_router
from .reachy_conversation import router as reachy_conversation_router
from .reachy_seeed_conversation import router as reachy_seeed_conversation_router
from .reachy_chat import router as reachy_chat_router
from .reachy_camera import router as reachy_camera_router, ws_router as reachy_camera_ws_router
from .reachy_realtime_voice import router as reachy_voice_router, ws_router as reachy_voice_ws_router
from .robots import router as robots_router, ws_router as robots_ws_router
from .b601 import router as b601_router
from .remote_compute import router as remote_compute_router
from .quest_teleop import router as quest_teleop_router
from .lekiwi import router as lekiwi_router

# BotClaw 契约 (v0.1). 由 run_api.py 把 packages/botclaw-spec/python 塞进 sys.path.
try:
    from botclaw_spec import JointUpdate, BOTCLAW_SPEC_VERSION  # type: ignore
except ImportError:  # pragma: no cover - dev-only guard
    JointUpdate = None  # type: ignore
    BOTCLAW_SPEC_VERSION = "unknown"

DEFAULT_ROBOT_ID = os.environ.get("BOTVERSEX_ROBOT_ID", "so101-001")

# apps/realtime/ 根目录 (main.py 在 apps/realtime/api/main.py)
REALTIME_ROOT = Path(__file__).parent.parent.resolve()
DEMOS_DIR = REALTIME_ROOT / "demos"


from fastapi.middleware.cors import CORSMiddleware

# 创建 FastAPI 应用
app = FastAPI(title="BotverseX API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://botversex.feispace.me",
        "https://botversex.feispace.me",
        "http://botversex.achao.xin",
        "https://botversex.achao.xin",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(playback_router)
app.include_router(datasets_router)
app.include_router(inference_router)
app.include_router(robotstate_router)
app.include_router(camera_router)
app.include_router(vision_inference_router)
app.include_router(setup_router)
app.include_router(teleop_control_router)
app.include_router(record_control_router)
app.include_router(hf_router)
app.include_router(calibrate_control_router)
app.include_router(robots_router)
app.include_router(robots_ws_router)
app.include_router(reachy_proxy_router)
app.include_router(reachy_ws_router)
app.include_router(reachy_conversation_router)
app.include_router(reachy_seeed_conversation_router)
app.include_router(reachy_chat_router)
app.include_router(reachy_camera_router)
app.include_router(reachy_camera_ws_router)
app.include_router(reachy_voice_router)
app.include_router(reachy_voice_ws_router)
app.include_router(b601_router)
app.include_router(remote_compute_router)
app.include_router(quest_teleop_router)
app.include_router(lekiwi_router)


@app.on_event("startup")
async def _cap_default_thread_pool():
    """Limit the default executor to 8 threads.

    Camera probes (cv2.VideoCapture) and serial checks run via
    run_in_executor(None, ...). Without a cap, concurrent health checks
    can spawn dozens of threads all blocking on V4L2 open(), starving the
    event loop.
    """
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=8))


# 静态文件目录
STATIC_DIR = Path(__file__).parent.parent / "static"


# ============== WebSocket 端点 ==============

@app.websocket("/ws/teleop")
async def websocket_teleop(websocket: WebSocket):
    """接收遥操作数据 (sender.py 连接到此端点).

    Payload 遵循 BotClaw v0.1 JointUpdate. 为了平滑升级, 同时兼容 V2 旧字段
    `joint_positions` + 缺少 `type/robot_id/timestamp` 的 payload.

    M4.2: URL 参数 `arm_id=<str>` 用于多臂场景占位.
      - M4 阶段: 所有 arm_id 共享同一个 manager 槽 (单臂). arm_id 只作标记, 不做路由隔离.
      - M5+: 预期 manager 会按 arm_id 分槽, /ws/ui 通过 arm_id 筛选广播.
    客户端应稳定传 `arm_id` (如 `arm_0`), 以便将来切多臂时不需要再改 URL.
    """
    arm_id = websocket.query_params.get("arm_id", "arm_0")
    client_id = f"teleop_{arm_id}_{int(time.time() * 1000)}"
    await manager.connect_teleop(websocket, client_id)
    # 记录 arm_id 便于诊断 / 未来多臂路由
    if client_id in manager.clients:
        manager.clients[client_id]["arm_id"] = arm_id

    try:
        while True:
            data = await websocket.receive_text()

            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                print(f"[ERR] Invalid JSON: {data[:200]}")
                continue

            # --- 兼容层: V2 旧 payload -> BotClaw JointUpdate ---
            normalized = dict(payload)
            if "type" not in normalized:
                normalized["type"] = "joint_update"
            if "robot_id" not in normalized:
                normalized["robot_id"] = DEFAULT_ROBOT_ID
            if "timestamp" not in normalized:
                normalized["timestamp"] = time.time()
            if "joints" not in normalized and "joint_positions" in normalized:
                normalized["joints"] = normalized.pop("joint_positions")

            # --- Pydantic 校验 (开发期帮助捕获字段错) ---
            msg = None
            if JointUpdate is not None:
                try:
                    msg = JointUpdate.model_validate(normalized)
                except ValidationError as ve:
                    print(f"[ERR] JointUpdate validation failed: {ve.errors()[:3]}")
                    continue

            joints = normalized.get("joints") or {}
            servo_values = normalized.get("servo_values") or {}

            joint_data = JointData(
                j1=float(joints.get("1", 0.0)),
                j2=float(joints.get("2", 0.0)),
                j3=float(joints.get("3", 0.0)),
                j4=float(joints.get("4", 0.0)),
                j5=float(joints.get("5", 0.0)),
                j6=float(joints.get("6", 0.0)),
                timestamp=float(normalized["timestamp"]),
            )
            manager.update_data(joint_data)
            manager.last_robot_id = normalized["robot_id"]
            manager.last_meta = normalized.get("meta")
            # v0.4: 透传可选硬件遥测. 没有的设备可以完全忽略这些字段.
            if "servo_values" in normalized and normalized["servo_values"]:
                manager.last_servo_values = normalized["servo_values"]
            if "temperatures_c" in normalized:
                manager.last_temperatures = normalized["temperatures_c"]
            if "currents_a" in normalized:
                manager.last_currents = normalized["currents_a"]
            if "voltages_v" in normalized:
                manager.last_voltages = normalized["voltages_v"]

            # 广播 BotClaw JointUpdate 给 UI
            broadcast_payload = {
                "type": "joint_update",
                "robot_id": normalized["robot_id"],
                "timestamp": joint_data.timestamp,
                "joints": {
                    "1": joint_data.j1, "2": joint_data.j2, "3": joint_data.j3,
                    "4": joint_data.j4, "5": joint_data.j5, "6": joint_data.j6,
                },
            }
            if servo_values:
                broadcast_payload["servo_values"] = servo_values
            if normalized.get("meta"):
                broadcast_payload["meta"] = normalized["meta"]

            await manager.broadcast(broadcast_payload)

    except WebSocketDisconnect:
        manager.disconnect(websocket, client_id)
    except Exception as e:
        print(f"[ERR] WebSocket error: {e}")
        manager.disconnect(websocket, client_id)


@app.websocket("/ws/ui")
async def websocket_ui(websocket: WebSocket):
    """UI 客户端连接, 接收实时关节数据更新.

    M4.2: URL 参数 `arm_id=<str>` 与 /ws/teleop 对齐. M4 阶段所有 ui 客户端收到全量广播,
    M5+ 会按 arm_id 过滤.
    """
    arm_id = websocket.query_params.get("arm_id", "arm_0")
    client_id = f"ui_{arm_id}_{int(time.time() * 1000)}"
    await manager.connect_ui(websocket, client_id)
    if client_id in manager.clients:
        manager.clients[client_id]["arm_id"] = arm_id

    try:
        # 首帧: 发送当前快照 (BotClaw JointUpdate)
        if manager.latest_data:
            await websocket.send_json({
                "type": "joint_update",
                "robot_id": getattr(manager, "last_robot_id", DEFAULT_ROBOT_ID),
                "timestamp": manager.latest_data.timestamp,
                "joints": {
                    "1": manager.latest_data.j1,
                    "2": manager.latest_data.j2,
                    "3": manager.latest_data.j3,
                    "4": manager.latest_data.j4,
                    "5": manager.latest_data.j5,
                    "6": manager.latest_data.j6,
                },
            })

        # 保持连接 - 浏览器不会主动发消息给服务器, receive_text 会一直 block
        # 直到浏览器断开时抛 WebSocketDisconnect. 底层 WS 协议 ping/pong 由 uvicorn 自动处理,
        # 应用层不需要手动 ping (Starlette WebSocket 也没有 .ping() 方法).
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        manager.disconnect(websocket, client_id)
    except Exception as e:
        print(f"[ERR] UI WebSocket error: {e}")
        manager.disconnect(websocket, client_id)


# ============== 录制 API ==============

class RecordRequest(BaseModel):
    action: str  # "start" or "stop"
    camera_device: str | None = None  # M8.2: "0", "1", etc. None = no camera

class RecordResponse(BaseModel):
    success: bool
    message: str
    frames: int = 0
    image_frames: int = 0
    filename: str | None = None
    dataset_id: str | None = None
    dataset_path: str | None = None


@app.post("/api/record")
async def control_recording(request: RecordRequest) -> RecordResponse:
    """
    控制录制
    POST /api/record {"action": "start"}
    POST /api/record {"action": "start", "camera_device": "0"}
    POST /api/record {"action": "stop"}
    """
    if request.action == "start":
        manager.start_recording(camera_device=request.camera_device)
        cam_msg = f" with camera {request.camera_device}" if request.camera_device else ""
        return RecordResponse(
            success=True,
            message=f"Recording started{cam_msg}"
        )

    elif request.action == "stop":
        data = manager.stop_recording()

        if data:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            ds_name = f"recording_{timestamp}"
            filename = f"{ds_name}.json"
            filepath = DEMOS_DIR / filename
            filepath.parent.mkdir(exist_ok=True)

            # M8.2: separate image bytes from JSON-serialisable data
            has_images = any(f.get("image_jpeg") for f in data)
            image_frames_count = 0

            # Prepare image output dir alongside the dataset
            dataset_root = REALTIME_ROOT / "datasets" / ds_name
            images_dir: Path | None = None
            if has_images:
                images_dir = dataset_root / "images" / "cam_main"
                images_dir.mkdir(parents=True, exist_ok=True)

            json_frames = []
            for idx, frame in enumerate(data):
                jpeg_bytes = frame.pop("image_jpeg", None)
                if jpeg_bytes and images_dir is not None:
                    img_name = f"frame_{idx:06d}.jpg"
                    (images_dir / img_name).write_bytes(jpeg_bytes)
                    frame["image_path"] = f"images/cam_main/{img_name}"
                    image_frames_count += 1
                json_frames.append(frame)

            with open(filepath, "w") as f:
                json.dump({
                    "recorded_at": datetime.now().isoformat(),
                    "frame_count": len(json_frames),
                    "has_images": has_images,
                    "frames": json_frames,
                }, f, indent=2)

            # -- 推断 fps / duration (用录制帧 timestamp 前后差)
            try:
                ts_first = float(data[0].get("timestamp", 0))
                ts_last = float(data[-1].get("timestamp", 0))
                duration_s = max(0.0, ts_last - ts_first)
            except Exception:
                duration_s = 0.0
            fps_nominal = None
            if isinstance(manager.last_meta, dict):
                fps_nominal = manager.last_meta.get("fps")
            if not fps_nominal and duration_s > 0:
                fps_nominal = (len(data) - 1) / duration_s
            conv_fps = int(round(fps_nominal)) if fps_nominal and fps_nominal > 0 else 64

            # -- 自动转换为 LeRobot Dataset
            dataset_info = ""
            dataset_id = None
            dataset_dir_str = None
            try:
                from convert_to_lerobot import convert_to_lerobot  # type: ignore
                dataset_path = convert_to_lerobot(
                    json_path=str(filepath),
                    output_dir=str(dataset_root),
                    fps=conv_fps,
                )
                if dataset_path:
                    dataset_info = f", parquet at {dataset_path.name}"
                    dataset_id = ds_name
                    dataset_dir_str = str(dataset_root)

                    botclaw_meta = {
                        "spec_version": BOTCLAW_SPEC_VERSION,
                        "dataset_id": dataset_id,
                        "name": dataset_id,
                        "source": "realtime_record",
                        "robot_id": manager.last_robot_id,
                        "frame_count": len(data),
                        "duration_s": duration_s,
                        "fps_nominal": fps_nominal,
                        "has_images": has_images,
                        "image_frames": image_frames_count,
                        "recorded_at": datetime.now().isoformat(),
                        "episode_dir": dataset_path.name,
                        "meta": manager.last_meta or {},
                    }
                    with open(dataset_root / "botclaw.json", "w", encoding="utf-8") as f:
                        json.dump(botclaw_meta, f, indent=2, ensure_ascii=False)
            except Exception as e:
                dataset_info = f" (parquet failed: {e})"

            img_msg = f", {image_frames_count} images" if has_images else ""
            return RecordResponse(
                success=True,
                message=f"Recording stopped, {len(data)} frames{img_msg}{dataset_info}",
                frames=len(data),
                image_frames=image_frames_count,
                filename=filename,
                dataset_id=dataset_id,
                dataset_path=dataset_dir_str,
            )
        else:
            return RecordResponse(
                success=True,
                message="No data recorded",
                frames=0
            )

    return RecordResponse(
        success=False,
        message="Invalid action. Use 'start' or 'stop'"
    )


# ============== 状态 API ==============

@app.get("/api/status")
async def get_status():
    """获取当前状态 (BotClaw v0.1 RobotState shape).

    字段对齐 packages/botclaw-spec/schemas/robot_state.schema.json, 额外给出
    `spec_version` 方便客户端做版本协商.
    """
    d = manager.latest_data
    joints = None
    if d:
        joints = {"1": d.j1, "2": d.j2, "3": d.j3, "4": d.j4, "5": d.j5, "6": d.j6}

    return {
        "spec_version": BOTCLAW_SPEC_VERSION,
        "robot_id": getattr(manager, "last_robot_id", DEFAULT_ROBOT_ID),
        "timestamp": d.timestamp if d else time.time(),
        "teleop_connected": len(manager.teleop_connections) > 0,
        "ui_clients": len(manager.ui_connections),
        "is_recording": manager.is_recording,
        "buffer_size": len(manager.record_buffer),
        "joints": joints,
    }


# ============== 前端页面 ==============

@app.get("/")
async def get_index():
    """返回前端页面"""
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"), status_code=200)
    raise HTTPException(status_code=404, detail="index.html not found")


# 挂载静态文件，禁用浏览器缓存（开发期避免旧 JS/CSS 被缓存）
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    """Cache policy: dev static no-cache; URDF catalog assets are immutable on disk."""
    response = await call_next(request)
    path = request.url.path

    if path.startswith("/static") or path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    if path.startswith("/api/urdf"):
        if response.status_code >= 400:
            response.headers["Cache-Control"] = "no-store"
            return response
        if path.endswith(".urdf"):
            response.headers["Cache-Control"] = "public, max-age=86400"
        elif "/assets/" in path:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "public, max-age=86400"
        return response

    if path in ("/api/runtimes", "/api/robots"):
        response.headers["Cache-Control"] = "public, max-age=60"
        return response

    return response


# ============== Runtime 端点 (M6.2) ==============

@app.get("/api/runtimes")
async def get_runtimes():
    """List available hardware runtimes and their metadata."""
    from runtimes import list_runtimes, get_runtime_class

    result = []
    for rid in list_runtimes():
        cls = get_runtime_class(rid)
        info = cls.info
        entry = {
            "runtime_id": info.runtime_id,
            "robot_type": info.robot_type,
            "display_name": info.display_name,
            "joint_count": info.joint_count,
            "joint_names": info.joint_names,
            "urdf_url": info.urdf_url,
            "supports_telemetry": info.supports_telemetry,
        }
        if info.camera_sources:
            entry["camera_sources"] = [
                {
                    "camera_id": c.camera_id,
                    "display_name": c.display_name,
                    "device_type": c.device_type,
                    "width": c.width,
                    "height": c.height,
                    "fps": c.fps,
                }
                for c in info.camera_sources
            ]
        result.append(entry)
    return {"runtimes": result}


# ============== URDF / Mesh 资源端点 ==============

# dora-bambot URDF 根目录（包含 so101.urdf 和 assets/*.stl）
URDF_ROOT = Path(__file__).parent.parent / "dora-bambot" / "URDF"

# 允许通过 /api/urdf/{name} 访问的 URDF 文件（扁平路径，主要给 SO-101 用）
ALLOWED_URDFS = {
    "so101.urdf": URDF_ROOT / "so101.urdf",
}

# 允许通过 /api/urdf/{ns}/{name}.urdf 访问的带命名空间 URDF 包
# 每个命名空间下的 mesh 会通过 /api/urdf/{ns}/assets/{mesh} 路由
ALLOWED_URDF_NAMESPACES: dict[str, Path] = {
    "reachy_mini": URDF_ROOT / "reachy_mini",
    "b601_rs": Path(__file__).parent.parent / "static" / "urdf" / "b601_rs",
    "lekiwi": Path(__file__).parent.parent / "static" / "urdf" / "lekiwi",
    "amazing_hand": Path(__file__).parent.parent / "static" / "urdf" / "amazing_hand",
    "unitree_g1": Path(__file__).parent.parent / "static" / "urdf" / "unitree_g1",
}

_MESH_MEDIA_TYPES = {
    ".stl": "model/stl",
    ".STL": "model/stl",
    ".obj": "text/plain",
    ".dae": "model/vnd.collada+xml",
}


def _safe_filename(name: str) -> bool:
    """拒绝包含路径分隔符 / 父目录的文件名，防止目录穿越。"""
    return not ("/" in name or "\\" in name or ".." in name)


@app.get("/api/urdf/{urdf_name}")
async def get_urdf(urdf_name: str):
    """返回扁平布局下 (apps/realtime/dora-bambot/URDF/) 的 URDF XML 文件。"""
    urdf_file = ALLOWED_URDFS.get(urdf_name)
    if urdf_file is None:
        raise HTTPException(status_code=404, detail="URDF not in allow-list")
    if not urdf_file.exists():
        raise HTTPException(status_code=404, detail=f"URDF file not found: {urdf_file}")

    return FileResponse(
        path=str(urdf_file),
        media_type="application/xml",
        filename=urdf_name,
    )


@app.get("/api/urdf/assets/{mesh_name}")
async def get_urdf_mesh(mesh_name: str):
    """
    返回扁平布局 URDF 的 mesh 资源 (STL/OBJ)
    URDF 中 mesh filename="assets/xxx.stl" 会解析到此端点
    """
    if not _safe_filename(mesh_name):
        raise HTTPException(status_code=400, detail="Invalid mesh name")

    mesh_file = URDF_ROOT / "assets" / mesh_name
    if not mesh_file.exists() or not mesh_file.is_file():
        raise HTTPException(status_code=404, detail=f"Mesh not found: {mesh_name}")

    suffix = mesh_file.suffix.lower()
    media_type = _MESH_MEDIA_TYPES.get(suffix, "application/octet-stream")

    return FileResponse(
        path=str(mesh_file),
        media_type=media_type,
        filename=mesh_name,
    )


@app.get("/api/urdf/{namespace}/{urdf_name}")
async def get_urdf_ns(namespace: str, urdf_name: str):
    """返回命名空间下的 URDF（如 /api/urdf/reachy_mini/reachy_mini.urdf）。"""
    if not _safe_filename(namespace) or not _safe_filename(urdf_name):
        raise HTTPException(status_code=400, detail="Invalid path")

    ns_root = ALLOWED_URDF_NAMESPACES.get(namespace)
    if ns_root is None:
        raise HTTPException(status_code=404, detail="URDF namespace not allowed")

    if not urdf_name.endswith(".urdf"):
        raise HTTPException(status_code=400, detail="Must end in .urdf")

    urdf_file = ns_root / urdf_name
    if not urdf_file.exists() or not urdf_file.is_file():
        raise HTTPException(status_code=404, detail=f"URDF not found: {urdf_name}")

    return FileResponse(
        path=str(urdf_file),
        media_type="application/xml",
        filename=urdf_name,
    )


@app.get("/api/urdf/{namespace}/assets/{mesh_name}")
async def get_urdf_mesh_ns(namespace: str, mesh_name: str):
    """返回命名空间下的 mesh 资源（URDF 内 package://assets/xxx.stl 由前端 loader 解析到此）。"""
    return _serve_urdf_mesh(namespace, "assets", mesh_name)


@app.get("/api/urdf/{namespace}/assets_preview/{mesh_name}")
async def get_urdf_mesh_ns_preview(namespace: str, mesh_name: str):
    """Lightweight preview meshes for catalog cards (B601-RS)."""
    return _serve_urdf_mesh(namespace, "assets_preview", mesh_name)


@app.get("/api/urdf/{namespace}/assets_catalog/{mesh_name}")
async def get_urdf_mesh_ns_catalog(namespace: str, mesh_name: str):
    """Catalog-card LOD meshes (B601-RS robots list)."""
    return _serve_urdf_mesh(namespace, "assets_catalog", mesh_name)


def _serve_urdf_mesh(namespace: str, asset_dir: str, mesh_name: str):
    if not _safe_filename(namespace) or not _safe_filename(mesh_name) or asset_dir not in (
        "assets",
        "assets_preview",
        "assets_catalog",
    ):
        raise HTTPException(status_code=400, detail="Invalid path")

    ns_root = ALLOWED_URDF_NAMESPACES.get(namespace)
    if ns_root is None:
        raise HTTPException(status_code=404, detail="URDF namespace not allowed")

    mesh_file = ns_root / asset_dir / mesh_name
    if not mesh_file.exists() or not mesh_file.is_file():
        raise HTTPException(status_code=404, detail=f"Mesh not found: {mesh_name}")

    suffix = mesh_file.suffix.lower()
    media_type = _MESH_MEDIA_TYPES.get(suffix, "application/octet-stream")

    return FileResponse(
        path=str(mesh_file),
        media_type=media_type,
        filename=mesh_name,
    )
