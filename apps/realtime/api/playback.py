"""Dataset 回放 (M2.5 + M14).

读两类目录下的 parquet，按 BotClaw JointUpdate 形状推出：

1) **Legacy** ``apps/realtime/datasets/<recording_*>/``（botclaw.json）
2) **LeRobot v3 cache** ``$HF_HOME/lerobot/<owner>/<name>/``（meta/info.json），
   与 Step4 ``lerobot-record`` 产物一致；``dataset_id`` 为 ``owner/name``。

端点:
- GET  /api/playback/{dataset_id:path}/meta
- WS   /ws/playback/{dataset_id:path}?fps=64&loop=false
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

router = APIRouter()


def _datasets_root() -> Path:
    # apps/realtime/api/playback.py -> apps/realtime -> datasets
    return Path(__file__).resolve().parents[1] / "datasets"


def _lerobot_cache_root() -> Path:
    base = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    return base / "lerobot"


def _resolve_dataset_dir(dataset_id: str) -> Path | None:
    """``recording_*`` -> realtime/datasets; ``owner/name`` -> HF lerobot cache."""
    if "/" in dataset_id:
        p = _lerobot_cache_root() / dataset_id
        return p if p.is_dir() else None
    p = _datasets_root() / dataset_id
    return p if p.is_dir() else None


def _find_parquets(dataset_id: str) -> tuple[Path, list[Path]]:
    """返回 (dataset_dir, 轨迹 parquet 路径列表).

    LeRobot v3 会在 ``meta/`` 下放 ``tasks.parquet`` 等非帧数据；只扫
    ``data/**/*.parquet``。Legacy 录制没有 ``data/`` 子目录则整树 rglob。
    """
    dataset_dir = _resolve_dataset_dir(dataset_id)
    if dataset_dir is None:
        raise HTTPException(
            404,
            f"dataset '{dataset_id}' not found "
            f"(checked {_datasets_root()} and {_lerobot_cache_root()})",
        )
    data_dir = dataset_dir / "data"
    if data_dir.is_dir():
        parquets = sorted(data_dir.rglob("*.parquet"))
    else:
        parquets = sorted(dataset_dir.rglob("*.parquet"))
    if not parquets:
        raise HTTPException(404, f"no parquet under {dataset_dir}")
    return dataset_dir, parquets


def _parquet_row_count(parquets: list[Path]) -> int:
    import pyarrow.parquet as pq

    n = 0
    for p in parquets:
        try:
            n += pq.ParquetFile(p).metadata.num_rows
        except Exception:
            pass
    return n


def _read_meta(dataset_dir: Path) -> dict[str, Any]:
    p = dataset_dir / "botclaw.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    info = dataset_dir / "meta" / "info.json"
    if info.exists():
        try:
            raw = json.loads(info.read_text(encoding="utf-8"))
            fps = raw.get("fps")
            tf = raw.get("total_frames")
            dur = None
            if isinstance(tf, int) and isinstance(fps, (int, float)) and fps > 0:
                dur = round(tf / float(fps), 3)
            return {
                "fps_nominal": float(fps) if isinstance(fps, (int, float)) else None,
                "frame_count": tf if isinstance(tf, int) else None,
                "duration_s": dur,
                "robot_id": raw.get("robot_type"),
                "source": "lerobot_hf_cache",
            }
        except Exception:
            pass
    return {}


def _load_frames_df(df: Any) -> list[dict[str, Any]]:
    """Single pandas dataframe -> frames."""
    joint_cols = [f"joint_{k}" for k in ("1", "2", "3", "4", "5", "6")]
    have_joint_cols = all(c in df.columns for c in joint_cols)
    has_state = "observation.state" in df.columns

    ts_col = None
    for c in ("timestamp", "ts", "observation.timestamp"):
        if c in df.columns:
            ts_col = c
            break

    frames: list[dict[str, Any]] = []
    for idx in range(len(df)):
        row = df.iloc[idx]
        if have_joint_cols:
            joints = {k: float(row[f"joint_{k}"]) for k in ("1", "2", "3", "4", "5", "6")}
        elif has_state:
            state = row["observation.state"]
            joints = {str(i + 1): float(state[i]) for i in range(min(6, len(state)))}
        else:
            continue
        ts = float(row[ts_col]) if ts_col else idx
        frames.append({"joints": joints, "timestamp": ts})
    return frames


def _load_frames(parquet_paths: list[Path]) -> list[dict[str, Any]]:
    """读一个或多个 parquet（LeRobot 多 chunk）按文件顺序拼成一条轨迹."""
    import pyarrow.parquet as pq

    out: list[dict[str, Any]] = []
    for parquet_path in parquet_paths:
        table = pq.read_table(parquet_path)
        df = table.to_pandas()
        out.extend(_load_frames_df(df))
    return out


@router.get("/api/playback/{dataset_id:path}/meta")
async def playback_meta(dataset_id: str) -> dict[str, Any]:
    dataset_dir, parquets = _find_parquets(dataset_id)
    meta = _read_meta(dataset_dir)
    # 只读第一个 chunk 采样算 fps，避免 meta 请求扫遍全部 parquet
    frames_sample = _load_frames(parquets[:1])[:200]
    duration = 0.0
    fps_obs = meta.get("fps_nominal")
    if len(frames_sample) >= 2:
        ts0, tsN = frames_sample[0]["timestamp"], frames_sample[-1]["timestamp"]
        if tsN > ts0:
            duration = tsN - ts0
            if not fps_obs:
                fps_obs = (len(frames_sample) - 1) / duration
    fc = meta.get("frame_count")
    if not isinstance(fc, int):
        fc = _parquet_row_count(parquets) or None

    return {
        "dataset_id": dataset_id,
        "frame_count": fc,
        "fps_nominal": fps_obs,
        "duration_s": meta.get("duration_s")
        if meta.get("duration_s") is not None
        else duration,
        "robot_id": meta.get("robot_id"),
        "joints": ["1", "2", "3", "4", "5", "6"],
        "meta": meta,
    }


@router.websocket("/ws/playback/{dataset_id:path}")
async def playback_ws(
    websocket: WebSocket,
    dataset_id: str,
    fps: float = Query(0),
    loop: bool = Query(False),
):
    await websocket.accept()
    try:
        dataset_dir, parquets = _find_parquets(dataset_id)
    except HTTPException as e:
        await websocket.send_json({"type": "error", "message": e.detail})
        await websocket.close()
        return

    meta = _read_meta(dataset_dir)
    frames = _load_frames(parquets)
    if not frames:
        await websocket.send_json({"type": "error", "message": "no frames"})
        await websocket.close()
        return

    target_fps = fps if fps > 0 else (meta.get("fps_nominal") or 30.0)
    target_fps = max(1.0, float(target_fps))
    period = 1.0 / target_fps

    robot_id = meta.get("robot_id") or "so101-playback"

    # 发送首帧 meta
    await websocket.send_json({
        "type": "playback_meta",
        "dataset_id": dataset_id,
        "robot_id": robot_id,
        "fps": target_fps,
        "frame_count": len(frames),
    })

    try:
        while True:
            start = time.time()
            for i, f in enumerate(frames):
                await websocket.send_json({
                    "type": "joint_update",
                    "robot_id": robot_id,
                    "timestamp": time.time(),
                    "joints": f["joints"],
                    "meta": {
                        "source": "playback",
                        "dataset_id": dataset_id,
                        "frame_index": i,
                        "fps": target_fps,
                    },
                })
                # 节流
                target_time = start + (i + 1) * period
                delay = target_time - time.time()
                if delay > 0:
                    await asyncio.sleep(delay)
            if not loop:
                break
        await websocket.send_json({"type": "playback_done", "dataset_id": dataset_id})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
