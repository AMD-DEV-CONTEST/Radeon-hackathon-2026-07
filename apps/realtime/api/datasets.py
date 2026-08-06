"""Realtime 侧的 datasets 只读视图 (M2 + M13).

apps/api 的 /api/v1/datasets 是权威入口 (带 auth + DB). 这里的 /api/datasets
只做"从磁盘扫"的只读镜像, 供前端 dev 模式免 token 访问. 字段形状与 apps/api
的 dataset_to_dict 对齐.

两个数据源合并后对外输出:
  1) 旧路径 ``apps/realtime/datasets/recording_*``（botclaw.json + parquet）
  2) LeRobot v3 cache ``$HF_HOME/lerobot/<owner>/<name>/``（meta/info.json +
     data/**/*.parquet），由 Step4 的 ``lerobot-record`` 写入。``dataset_id``
     原样是 ``owner/name`` 的 HF repo id，Training 页面选到后直接能提交。

M8.2: /api/datasets/{id}/images/{path} 给 vision dataset 用。
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter()


def _datasets_root() -> Path:
    return Path(__file__).resolve().parents[1] / "datasets"


def _lerobot_cache_root() -> Path:
    """``$HF_HOME/lerobot``，Step4 的 ``lerobot-record`` 写在这里。"""
    base = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    return base / "lerobot"


def _read_botclaw(dir_: Path) -> dict[str, Any] | None:
    p = dir_ / "botclaw.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _summarize(dir_: Path) -> dict[str, Any] | None:
    parquets = list(dir_.rglob("*.parquet"))
    if not parquets:
        return None
    meta = _read_botclaw(dir_) or {}
    dataset_id = meta.get("dataset_id") or dir_.name
    images_dir = dir_ / "images" / "cam_main"
    has_images = images_dir.is_dir() and any(images_dir.iterdir())
    return {
        "dataset_id": dataset_id,
        "name": meta.get("name") or dataset_id,
        "path": str(dir_),
        "source": meta.get("source") or "realtime_record",
        "robot_id": meta.get("robot_id"),
        "frame_count": meta.get("frame_count"),
        "duration_s": meta.get("duration_s"),
        "fps_nominal": meta.get("fps_nominal"),
        "recorded_at": meta.get("recorded_at"),
        "has_images": has_images,
        "image_frames": meta.get("image_frames", 0) if has_images else 0,
        "parquet": str(parquets[0]),
        "meta": meta,
    }


def _summarize_lerobot(dir_: Path, repo_id: str) -> dict[str, Any] | None:
    """Summarize a LeRobot v3 dataset directory (Step4 output).

    Layout produced by ``lerobot-record``:
      <cache>/<owner>/<name>/
        meta/info.json            总帧数 / fps / features / total_episodes
        data/chunk-000/*.parquet  各 episode 的 parquet
        videos/<key>/chunk-***/*.mp4   有相机时
    """
    info_path = dir_ / "meta" / "info.json"
    if not info_path.is_file():
        return None
    parquets = list((dir_ / "data").rglob("*.parquet")) if (dir_ / "data").is_dir() else []
    if not parquets:
        parquets = list(dir_.rglob("*.parquet"))
    if not parquets:
        return None

    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except Exception:
        info = {}

    fps = info.get("fps")
    frame_count = info.get("total_frames")
    total_episodes = info.get("total_episodes")
    duration_s: float | None = None
    if isinstance(fps, (int, float)) and fps > 0 and isinstance(frame_count, int):
        duration_s = round(frame_count / float(fps), 3)

    # 视频/图像特征存在 (observation.images.* / observation.image*) 就算有相机。
    features = info.get("features") or {}
    has_images = any(
        k.startswith("observation.image") or k.startswith("observation.images")
        for k in features.keys()
    )

    try:
        recorded_at = dir_.stat().st_mtime
    except Exception:
        recorded_at = None

    return {
        "dataset_id": repo_id,
        "name": repo_id,
        "path": str(dir_),
        "source": "lerobot_hf_cache",
        "robot_id": info.get("robot_type"),
        "frame_count": frame_count if isinstance(frame_count, int) else None,
        "duration_s": duration_s,
        "fps_nominal": float(fps) if isinstance(fps, (int, float)) else None,
        "recorded_at": (
            __import__("datetime").datetime.utcfromtimestamp(recorded_at).isoformat()
            if recorded_at
            else None
        ),
        "has_images": has_images,
        "image_frames": 0,
        "parquet": str(parquets[0]),
        "total_episodes": total_episodes if isinstance(total_episodes, int) else None,
        "meta": info,
    }


def _iter_lerobot_datasets(root: Path):
    """遍历 ``$HF_HOME/lerobot`` 下的 ``<owner>/<name>`` 二级目录。

    跳过 ``calibration``（不是数据集）。
    """
    if not root.is_dir():
        return
    for owner_dir in sorted(
        root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True
    ):
        if not owner_dir.is_dir() or owner_dir.name == "calibration":
            continue
        for name_dir in sorted(
            owner_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True
        ):
            if not name_dir.is_dir():
                continue
            yield name_dir, f"{owner_dir.name}/{name_dir.name}"


@router.get("/api/datasets")
async def list_datasets() -> dict[str, Any]:
    out: list[dict[str, Any]] = []

    # 来源 1: 老的 apps/realtime/datasets/recording_*
    root = _datasets_root()
    if root.exists():
        for d in sorted(root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if not d.is_dir() or not d.name.startswith("recording_"):
                continue
            s = _summarize(d)
            if s:
                out.append(s)

    # 来源 2: LeRobot v3 cache (Step4 的 lerobot-record 写在这里)
    lerobot_root = _lerobot_cache_root()
    for name_dir, repo_id in _iter_lerobot_datasets(lerobot_root):
        s = _summarize_lerobot(name_dir, repo_id)
        if s:
            out.append(s)

    # 合并后按 recorded_at/mtime 近的在前
    out.sort(key=lambda s: s.get("recorded_at") or "", reverse=True)

    return {
        "total": len(out),
        "items": out,
        "storage_root": str(root),
        "lerobot_cache_root": str(lerobot_root),
    }


# ---------------------------------------------------------------------------
# WebSerial 首录（U3）：浏览器直连录制的关节轨迹落盘成第一条 dataset
# ---------------------------------------------------------------------------

class WebserialRecordFrame(BaseModel):
    """一帧：时间戳 + 各关节计数（key = 电机 ID "1".."6"）。"""

    timestamp: float
    joints: dict[str, int]


class WebserialRecordIn(BaseModel):
    dataset_id: str | None = None
    name: str = "我的第一条数据"
    robot_id: str = "so101"
    task: str | None = None
    fps: float = 20.0
    frames: list[WebserialRecordFrame]


def _safe_id(raw: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z_-]", "_", raw).strip("_")
    return cleaned or "record"


@router.post("/api/datasets/record")
async def record_webserial(body: WebserialRecordIn) -> dict[str, Any]:
    """浏览器 WebSerial 录制（U3 最小版）：关节轨迹 JSON → parquet + botclaw.json。

    - 目录: ``apps/realtime/datasets/recording_<id>/``（前缀必须 recording_ 才会被列表扫描到）
    - parquet: LeRobot 风格列（index/episode_index/frame_index/timestamp/
      observation.state/action）；完整对齐（相机/任务/多集）在 S5。
    - botclaw.json: DatasetEpisode v0.2 元数据（source=webserial_record）。
    """
    if not body.frames:
        raise HTTPException(400, "frames 为空，没有可入库的轨迹")

    ts = int(time.time())
    dataset_id = body.dataset_id or f"recording_ws_{ts}"
    if not dataset_id.startswith("recording_"):
        dataset_id = f"recording_{dataset_id}"
    dataset_id = _safe_id(dataset_id)

    root = _datasets_root()
    root.mkdir(parents=True, exist_ok=True)
    target = root / dataset_id
    if target.exists():
        raise HTTPException(409, f"dataset 已存在: {dataset_id}")
    target.mkdir(parents=True)

    # 关节顺序固定 1..6（SO-101）
    joint_ids = ["1", "2", "3", "4", "5", "6"]
    rows: list[dict[str, Any]] = []
    for i, f in enumerate(body.frames):
        state = [float(f.joints.get(j, 2048)) for j in joint_ids]
        rows.append(
            {
                "index": i,
                "episode_index": 0,
                "frame_index": i,
                "timestamp": f.timestamp,
                "observation.state": state,
                "action": state,  # 浏览器直录无主从动作差，action 以 state 记录（S5 前诚实标注）
            }
        )

    parquet_rel = "episode_000000.parquet"
    df = pd.DataFrame(rows)
    df.to_parquet(target / parquet_rel, index=False)

    recorded_at = datetime.now(timezone.utc).isoformat()
    duration_s = round(max(f.timestamp for f in body.frames), 3)
    botclaw = {
        "spec_version": "0.2.0",
        "dataset_id": dataset_id,
        "name": body.name,
        "robot_id": body.robot_id,
        "source": "webserial_record",
        "recorded_at": recorded_at,
        "duration_s": duration_s,
        "duration_sec": duration_s,
        "frame_count": len(rows),
        "fps": body.fps,
        "fps_nominal": body.fps,
        "task": body.task,
        "artifacts": {"parquet": parquet_rel},
    }
    (target / "botclaw.json").write_text(
        json.dumps(botclaw, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "dataset_id": dataset_id,
        "name": body.name,
        "path": str(target),
        "frame_count": len(rows),
        "duration_s": duration_s,
        "recorded_at": recorded_at,
        "source": "webserial_record",
    }


def _resolve_dataset_dir(dataset_id: str) -> Path | None:
    """把 dataset_id 解析回磁盘路径。

    - ``recording_*``：``apps/realtime/datasets/<id>``
    - ``owner/name``：``$HF_HOME/lerobot/<owner>/<name>``
    """
    if "/" in dataset_id:
        p = _lerobot_cache_root() / dataset_id
        return p if p.is_dir() else None
    p = _datasets_root() / dataset_id
    return p if p.is_dir() else None


# NOTE: the ``images`` route is declared BEFORE the catch-all ``{dataset_id:path}``
# route so FastAPI resolves image URLs first (the ``:path`` converter below would
# otherwise swallow ``/images/...`` as part of the dataset id).
@router.get("/api/datasets/{dataset_id}/images/{camera_id}/{filename}")
async def get_dataset_image(dataset_id: str, camera_id: str, filename: str):
    """Serve a recorded camera frame from a vision dataset."""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "invalid filename")
    if ".." in camera_id or "/" in camera_id:
        raise HTTPException(400, "invalid camera_id")
    img_path = _datasets_root() / dataset_id / "images" / camera_id / filename
    if not img_path.exists():
        raise HTTPException(404, "image not found")
    return FileResponse(str(img_path), media_type="image/jpeg")


@router.get("/api/datasets/{dataset_id:path}")
async def get_dataset(dataset_id: str) -> dict[str, Any]:
    # ``dataset_id`` 可能是 ``owner/name`` (HF 风格)，FastAPI 需要 ``:path`` 才能
    # 让斜杠不被当成分隔符。``images`` 子路由已经在上面优先注册。
    dir_ = _resolve_dataset_dir(dataset_id)
    if dir_ is None:
        raise HTTPException(404, f"dataset '{dataset_id}' not found")
    if "/" in dataset_id:
        s = _summarize_lerobot(dir_, dataset_id)
    else:
        s = _summarize(dir_)
    if s is None:
        raise HTTPException(404, f"no parquet under {dir_}")
    return s
