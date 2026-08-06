"""Dataset 扫描 / 统计 / 评分 (M2).

- 磁盘是 single source of truth, DB 只是索引 + 缓存的 stats/quality.
- scan_storage_root(db) 扫描 settings.DATASETS_STORAGE_ROOT 下的 episode 目录:
    recording_YYYYMMDD_HHMMSS/
      botclaw.json                 <-- 由 realtime 写
      episode_0/
        data/chunk-000/file-000.parquet

  找到任何一个带 parquet 的子目录都尝试登记. parquet 的统计 + 评分由
  compute_stats() 完成 (懒加载 pyarrow).
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.dataset import Dataset

JOINT_KEYS = ["1", "2", "3", "4", "5", "6"]


# ---------- helpers ----------


def get_storage_root() -> Path:
    """返回 parquet 根目录, 空配置时推导 apps/realtime/datasets/."""
    raw = settings.DATASETS_STORAGE_ROOT
    if raw:
        return Path(raw).expanduser().resolve()
    # apps/api/app/services/dataset_service.py -> apps/api -> apps -> apps/realtime/datasets
    here = Path(__file__).resolve()
    realtime_datasets = here.parents[3] / "realtime" / "datasets"
    return realtime_datasets


def get_lerobot_cache_root() -> Path:
    """``$HF_HOME/lerobot``, 第二类数据集根目录 (M13).

    Step4 的 ``lerobot-record`` 会把数据集写到 ``<cache>/<owner>/<name>/``，
    ``owner/name`` 即 ``dataset_id``。
    """
    base = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    return base / "lerobot"


def resolve_dataset_dir(dataset_id: str) -> Path | None:
    """Locate the on-disk dir for a ``dataset_id`` across both storage roots.

    Two shapes supported:
      1. ``recording_YYYYMMDD_HHMMSS`` → ``apps/realtime/datasets/<id>``
         (the legacy M2 recording pipeline)
      2. ``owner/name`` (e.g. ``botversex/so101-20260422_0302``) →
         ``$HF_HOME/lerobot/<owner>/<name>`` (the M13 ``lerobot-record``
         pipeline wired in Step 4)

    Returns ``None`` if neither location has a matching directory.
    """
    if "/" in dataset_id:
        p = get_lerobot_cache_root() / dataset_id
        return p if p.is_dir() else None
    p = get_storage_root() / dataset_id
    return p if p.is_dir() else None


def _find_episode_dirs(root: Path) -> Iterable[Path]:
    """在 root 下寻找 'recording_*' 级别目录 (一个 dataset = 一个目录)."""
    if not root.exists():
        return []
    out: list[Path] = []
    for child in root.iterdir():
        if child.is_dir() and child.name.startswith("recording_"):
            out.append(child)
    return out


def _read_botclaw_meta(dataset_dir: Path) -> dict[str, Any] | None:
    meta_path = dataset_dir / "botclaw.json"
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_lerobot_info(dataset_dir: Path) -> dict[str, Any] | None:
    """Read LeRobot dataset metadata when parquet payload is missing locally."""
    info_path = dataset_dir / "meta" / "info.json"
    if not info_path.exists():
        return None
    try:
        return json.loads(info_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _find_parquet(dataset_dir: Path) -> Path | None:
    parquets = list(dataset_dir.rglob("*.parquet"))
    if not parquets:
        return None
    # LeRobot cache may contain meta/tasks.parquet with 0 rows; stats should
    # prefer real frame payload files under data/.
    payload = [p for p in parquets if "meta" not in p.parts]
    if payload:
        return payload[0]
    return None


def _stats_from_botclaw_meta(meta: dict[str, Any]) -> dict[str, Any] | None:
    """Use Teleop ``botclaw.json`` when parquet stats are unavailable."""
    if not meta:
        return None
    frame_count = meta.get("frame_count")
    if frame_count is None:
        return None
    fc = int(frame_count)
    duration_s = float(meta.get("duration_s") or 0.0)
    nominal = meta.get("fps_nominal")
    if nominal is None and duration_s > 0 and fc > 1:
        nominal = (fc - 1) / duration_s
    fps_obs = float(nominal) if nominal else (fc / duration_s if duration_s > 0 else 0.0)
    return {
        "frame_count": fc,
        "duration_s": duration_s,
        "fps_nominal": nominal,
        "fps_observed_mean": fps_obs,
        "fps_observed_std": 0.0,
        "joints": {},
        "source": "botclaw_fallback",
        "has_images": bool(meta.get("has_images")),
    }


def _stats_from_hf_dataset(repo_id: str) -> dict[str, Any] | None:
    """Fetch frame/fps summary from HF ``meta/info.json`` (remote-only datasets)."""
    try:
        import httpx

        url = f"https://huggingface.co/datasets/{repo_id}/resolve/main/meta/info.json"
        with httpx.Client(trust_env=False, timeout=8.0, follow_redirects=True) as c:
            r = c.get(url)
        if r.status_code == 200:
            return _stats_from_lerobot_info(r.json())
    except Exception as exc:
        logger.debug("HF dataset stats failed for %s: %s", repo_id, exc)
    return None


def _stats_from_lerobot_info(info: dict[str, Any], meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a minimal stats object from meta/info.json."""
    frame_count = int(info.get("total_frames") or 0)
    fps = float((info.get("fps") or 0) or 0)
    duration_s = float(frame_count / fps) if frame_count > 0 and fps > 0 else 0.0
    nominal = (meta or {}).get("fps_nominal") or (fps if fps > 0 else None)
    return {
        "frame_count": frame_count,
        "duration_s": duration_s,
        "fps_nominal": nominal,
        "fps_observed_mean": fps if fps > 0 else 0.0,
        "fps_observed_std": 0.0,
        "joints": {},
        "source": "lerobot_info_fallback",
    }


# ---------- stats & quality ----------


@dataclass
class JointStats:
    min: float
    max: float
    mean: float
    std: float
    range: float
    jitter: float  # 相邻帧差的标准差


def _compute_joint_stats(values: list[float]) -> JointStats:
    if not values:
        return JointStats(0, 0, 0, 0, 0, 0)
    n = len(values)
    mn = min(values)
    mx = max(values)
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / max(1, n - 1)
    std = math.sqrt(var)
    diffs = [values[i + 1] - values[i] for i in range(n - 1)]
    if diffs:
        d_mean = sum(diffs) / len(diffs)
        d_var = sum((d - d_mean) ** 2 for d in diffs) / max(1, len(diffs) - 1)
        jitter = math.sqrt(d_var)
    else:
        jitter = 0.0
    return JointStats(mn, mx, mean, std, mx - mn, jitter)


def compute_stats(parquet_path: Path, meta: dict[str, Any] | None) -> dict[str, Any]:
    """读 parquet 算 6 关节 stats + fps 稳定性. 不依赖 lerobot."""
    import pyarrow.parquet as pq  # lazy

    table = pq.read_table(parquet_path)
    df = table.to_pandas()

    frame_count = int(len(df))
    # 关节列名 (LeRobot 导出时会用 observation.state / action, 不确定, 两种都尝试)
    joint_series: dict[str, list[float]] = {}
    for key in JOINT_KEYS:
        col_candidates = [f"joint_{key}", f"joints_{key}", key]
        for c in col_candidates:
            if c in df.columns:
                joint_series[key] = df[c].astype(float).tolist()
                break

    if not joint_series:
        # fallback: observation.state 是个 list-like, 按下标 0..5 取
        if "observation.state" in df.columns:
            for i, key in enumerate(JOINT_KEYS):
                joint_series[key] = [float(row[i]) for row in df["observation.state"] if row is not None and len(row) > i]

    joint_stats = {k: _compute_joint_stats(v).__dict__ for k, v in joint_series.items()}

    # 时间 / fps
    ts_col = None
    for c in ("timestamp", "ts", "observation.timestamp"):
        if c in df.columns:
            ts_col = c
            break
    if ts_col:
        ts = df[ts_col].astype(float).tolist()
    else:
        ts = []

    duration_s = 0.0
    fps_mean = 0.0
    fps_std = 0.0
    if len(ts) >= 2:
        duration_s = float(ts[-1] - ts[0])
        dt = [ts[i + 1] - ts[i] for i in range(len(ts) - 1) if ts[i + 1] > ts[i]]
        if dt:
            fps = [1.0 / d for d in dt if d > 0]
            if fps:
                fps_mean = sum(fps) / len(fps)
                m = fps_mean
                var = sum((f - m) ** 2 for f in fps) / max(1, len(fps) - 1)
                fps_std = math.sqrt(var)

    nominal = (meta or {}).get("fps_nominal") if meta else None
    if not nominal and duration_s > 0 and frame_count > 1:
        nominal = (frame_count - 1) / duration_s

    return {
        "frame_count": frame_count,
        "duration_s": duration_s,
        "fps_nominal": nominal,
        "fps_observed_mean": fps_mean,
        "fps_observed_std": fps_std,
        "joints": joint_stats,
    }


def compute_quality(stats: dict[str, Any]) -> tuple[int, list[str]]:
    """规则式 0-100 评分 + flags.

    规则:
      - base 100
      - frame_count < 30    -> -40, flag=low_frame_count
      - duration_s < 1.0    -> -20, flag=too_short
      - fps_std / fps_mean > 0.3 -> -20, flag=fps_unstable
      - 所有 joint.range < 0.01 (一帧没动过) -> -30, flag=no_motion
      - 任一 joint.jitter > 0.5 rad/帧      -> -15, flag=joint_jitter
    """
    score = 100
    flags: list[str] = []

    fc = stats.get("frame_count", 0)
    if fc < 30:
        score -= 40
        flags.append("low_frame_count")

    dur = stats.get("duration_s", 0.0)
    if dur < 1.0:
        score -= 20
        flags.append("too_short")

    fps_m = stats.get("fps_observed_mean", 0.0)
    fps_s = stats.get("fps_observed_std", 0.0)
    if fps_m > 0 and (fps_s / fps_m) > 0.3:
        score -= 20
        flags.append("fps_unstable")

    joints = stats.get("joints") or {}
    ranges = [j.get("range", 0.0) for j in joints.values()]
    if ranges and all(r < 0.01 for r in ranges):
        score -= 30
        flags.append("no_motion")

    jitters = [j.get("jitter", 0.0) for j in joints.values()]
    if any(j > 0.5 for j in jitters):
        score -= 15
        flags.append("joint_jitter")

    score = max(0, min(100, score))
    return score, flags


# ---------- registry ----------


def upsert_from_dir(db: Session, dataset_dir: Path) -> Dataset | None:
    """把磁盘上的一个 episode 目录 upsert 进 DB (含 stats + quality)."""
    parquet = _find_parquet(dataset_dir)
    meta = _read_botclaw_meta(dataset_dir) or {}
    lerobot_info = _read_lerobot_info(dataset_dir) or {}
    # ``dataset_id`` 优先取 botclaw.json 里记的值；否则看该目录是否位于
    # HF cache 下 (``$HF_HOME/lerobot/<owner>/<name>/``)，此时 id 是
    # ``owner/name`` 这种两段式；最后才回落到目录名本身 (legacy
    # ``recording_*``)。
    dataset_id = meta.get("dataset_id")
    if not dataset_id:
        try:
            cache_root = get_lerobot_cache_root().resolve()
            resolved = dataset_dir.resolve()
            rel = resolved.relative_to(cache_root)
            parts = rel.parts
            if len(parts) >= 2:
                dataset_id = f"{parts[0]}/{parts[1]}"
        except Exception:
            dataset_id = None
    if not dataset_id:
        dataset_id = dataset_dir.name

    if parquet is not None:
        try:
            stats = compute_stats(parquet, meta)
        except Exception as e:
            if lerobot_info:
                stats = _stats_from_lerobot_info(lerobot_info, meta)
                stats["warning"] = f"parquet_stats_failed: {e}"
            elif meta.get("frame_count") is not None:
                stats = _stats_from_botclaw_meta(meta) or {"error": str(e)}
                if "error" not in stats:
                    stats["warning"] = f"parquet_stats_failed: {e}"
            else:
                stats = {"error": str(e)}
    elif lerobot_info:
        stats = _stats_from_lerobot_info(lerobot_info, meta)
    elif meta.get("frame_count") is not None:
        stats = _stats_from_botclaw_meta(meta)
        if not stats:
            return None
    else:
        return None
    score, flags = compute_quality(stats if "error" not in stats else {})

    existing = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if existing:
        existing.path = str(dataset_dir)
        existing.frame_count = int(stats.get("frame_count", 0) or 0)
        existing.duration_s = float(stats.get("duration_s", 0.0) or 0.0)
        existing.fps_nominal = stats.get("fps_nominal")
        existing.stats_json = stats
        existing.flags_json = flags
        existing.quality_score = score
        existing.status = "error" if "error" in stats else "ok"
        merged_meta = dict(existing.meta_json or {})
        merged_meta.update(meta)
        if lerobot_info:
            merged_meta.setdefault("name", dataset_id)
            merged_meta["lerobot_info"] = {
                "total_frames": lerobot_info.get("total_frames"),
                "total_episodes": lerobot_info.get("total_episodes"),
                "fps": lerobot_info.get("fps"),
                "robot_type": lerobot_info.get("robot_type"),
            }
        existing.meta_json = merged_meta
        if meta.get("robot_id"):
            existing.robot_id = meta["robot_id"]
        db.commit()
        db.refresh(existing)
        return existing

    created_at = None
    if meta.get("recorded_at"):
        try:
            created_at = datetime.fromisoformat(meta["recorded_at"])
        except Exception:
            pass
    created_at = created_at or datetime.utcfromtimestamp(dataset_dir.stat().st_mtime)

    merged_meta = dict(meta)
    if lerobot_info:
        merged_meta.setdefault("name", dataset_id)
        merged_meta["lerobot_info"] = {
            "total_frames": lerobot_info.get("total_frames"),
            "total_episodes": lerobot_info.get("total_episodes"),
            "fps": lerobot_info.get("fps"),
            "robot_type": lerobot_info.get("robot_type"),
        }

    row = Dataset(
        dataset_id=dataset_id,
        name=meta.get("name") or dataset_id,
        path=str(dataset_dir),
        source=meta.get("source") or ("lerobot_cache" if lerobot_info else "realtime_record"),
        robot_id=meta.get("robot_id"),
        frame_count=int(stats.get("frame_count", 0) or 0),
        duration_s=float(stats.get("duration_s", 0.0) or 0.0),
        fps_nominal=stats.get("fps_nominal"),
        stats_json=stats,
        flags_json=flags,
        quality_score=score,
        status="error" if "error" in stats else "ok",
        meta_json=merged_meta,
        created_at=created_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def scan_storage_root(db: Session, root: Path | None = None) -> list[Dataset]:
    """扫一次 storage_root, 把所有未入库的 episode 目录加进来. 返回新增/更新列表."""
    root = root or get_storage_root()
    out: list[Dataset] = []
    for d in _find_episode_dirs(root):
        ds = upsert_from_dir(db, d)
        if ds:
            out.append(ds)
    # M13: also index HF cache datasets (<cache>/<owner>/<name>/meta/info.json)
    cache_root = get_lerobot_cache_root()
    if cache_root.exists():
        for owner_dir in cache_root.iterdir():
            if not owner_dir.is_dir():
                continue
            for name_dir in owner_dir.iterdir():
                if not name_dir.is_dir():
                    continue
                if not (name_dir / "meta" / "info.json").exists():
                    continue
                ds = upsert_from_dir(db, name_dir)
                if ds:
                    out.append(ds)
    return out


def dataset_to_dict(ds: Dataset) -> dict[str, Any]:
    frame_count = ds.frame_count
    duration_s = ds.duration_s
    fps_nominal = ds.fps_nominal
    has_images = (ds.meta_json or {}).get("has_images")
    hf_repo = (ds.meta_json or {}).get("hf_repo_id")
    if (frame_count or 0) <= 1 and hf_repo and "/" in str(hf_repo):
        hf_stats = _stats_from_hf_dataset(str(hf_repo))
        if hf_stats and int(hf_stats.get("frame_count") or 0) > (frame_count or 0):
            frame_count = hf_stats["frame_count"]
            duration_s = hf_stats.get("duration_s") or duration_s
            fps_nominal = hf_stats.get("fps_nominal") or fps_nominal

    # DB stats can be stale (e.g. pyarrow missing); refresh from on-disk botclaw.
    if (frame_count or 0) <= 0 or fps_nominal is None:
        p = resolve_dataset_dir(ds.dataset_id)
        if p is None and ds.path:
            from pathlib import Path
            pp = Path(ds.path)
            if pp.is_dir():
                p = pp
        if p is not None:
            bc = _read_botclaw_meta(p)
            if bc:
                if (frame_count or 0) <= 0 and bc.get("frame_count") is not None:
                    frame_count = int(bc["frame_count"])
                if (duration_s or 0) <= 0 and bc.get("duration_s") is not None:
                    duration_s = float(bc["duration_s"])
                if fps_nominal is None and bc.get("fps_nominal") is not None:
                    fps_nominal = float(bc["fps_nominal"])
                if has_images is None:
                    has_images = bc.get("has_images")
    return {
        "id": str(ds.id),
        "dataset_id": ds.dataset_id,
        "name": ds.name,
        "path": ds.path,
        "source": ds.source,
        "robot_id": ds.robot_id,
        "frame_count": frame_count,
        "duration_s": duration_s,
        "fps_nominal": fps_nominal,
        "has_images": has_images,
        "quality_score": ds.quality_score,
        "flags": ds.flags_json or [],
        "status": ds.status,
        "skill_id": ds.skill_id or "so101_generic_teleop",
        "robot_type": ds.robot_type or "so101",
        "hf_repo_id": (ds.meta_json or {}).get("hf_repo_id"),
        "hf_url": (ds.meta_json or {}).get("hf_url"),
        "hf_private": (ds.meta_json or {}).get("hf_private"),
        "created_at": ds.created_at.isoformat() if ds.created_at else None,
        "updated_at": ds.updated_at.isoformat() if ds.updated_at else None,
    }
