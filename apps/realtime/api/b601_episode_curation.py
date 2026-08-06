"""B601 episode marks + delete helpers (soft quality tags + LeRobot delete_episodes)."""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Literal, Optional

logger = logging.getLogger("botversex.b601.episode_curation")

MARKS_FILENAME = "botversex_episode_marks.json"
Verdict = Literal["ok", "bad", "clear"]


def marks_path(dataset_root: Path) -> Path:
    return dataset_root / "meta" / MARKS_FILENAME


def load_marks(dataset_root: Path) -> dict[str, Any]:
    path = marks_path(dataset_root)
    if not path.is_file():
        return {"episodes": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"episodes": {}}
        eps = data.get("episodes")
        if not isinstance(eps, dict):
            data["episodes"] = {}
        return data
    except Exception:
        return {"episodes": {}}


def save_marks(dataset_root: Path, data: dict[str, Any]) -> None:
    meta = dataset_root / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    path = marks_path(dataset_root)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def set_verdict(dataset_root: Path, episode_index: int, verdict: Verdict) -> dict[str, Any]:
    if episode_index < 0:
        raise ValueError("episode_index must be >= 0")
    data = load_marks(dataset_root)
    eps: dict[str, Any] = dict(data.get("episodes") or {})
    key = str(int(episode_index))
    if verdict == "clear":
        eps.pop(key, None)
    else:
        eps[key] = {"verdict": verdict, "ts": time.time()}
    data["episodes"] = eps
    save_marks(dataset_root, data)
    return data


def remap_marks_after_delete(data: dict[str, Any], deleted: list[int]) -> dict[str, Any]:
    deleted_set = set(int(i) for i in deleted)
    eps_in = dict(data.get("episodes") or {})
    eps_out: dict[str, Any] = {}
    for k, v in eps_in.items():
        try:
            old = int(k)
        except (TypeError, ValueError):
            continue
        if old in deleted_set:
            continue
        new_idx = old - sum(1 for d in deleted_set if d < old)
        eps_out[str(new_idx)] = v
    data["episodes"] = eps_out
    return data


def bad_episode_indices(dataset_root: Path, total_episodes: int) -> list[int]:
    data = load_marks(dataset_root)
    out: list[int] = []
    for k, v in (data.get("episodes") or {}).items():
        try:
            idx = int(k)
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= total_episodes:
            continue
        if isinstance(v, dict) and v.get("verdict") == "bad":
            out.append(idx)
    return sorted(out)


def total_episodes_from_info(dataset_root: Path) -> int:
    info = dataset_root / "meta" / "info.json"
    if not info.is_file():
        return 0
    try:
        meta = json.loads(info.read_text(encoding="utf-8"))
        raw = meta.get("total_episodes")
        return int(raw) if isinstance(raw, int) else 0
    except Exception:
        return 0


def list_episodes(dataset_root: Path, repo_id: str) -> list[dict[str, Any]]:
    """List episodes with marks + optional video timestamp windows."""
    from urllib.parse import quote

    total = total_episodes_from_info(dataset_root)
    marks = load_marks(dataset_root)
    mark_eps = marks.get("episodes") or {}

    # Prefer LeRobot metadata for length + video windows.
    ep_meta: list[dict[str, Any]] = []
    try:
        from lerobot.datasets.lerobot_dataset import LeRobotDataset

        ds = LeRobotDataset(repo_id, root=dataset_root)
        total = int(ds.meta.total_episodes)
        for i in range(total):
            row = ds.meta.episodes[i]
            entry: dict[str, Any] = {
                "episode_index": i,
                "length": int(row.get("length") or 0),
                "videos": [],
            }
            for key, val in row.items():
                if not isinstance(key, str):
                    continue
                if key.startswith("videos/") and key.endswith("/from_timestamp"):
                    cam = key[len("videos/") : -len("/from_timestamp")]
                    to_key = f"videos/{cam}/to_timestamp"
                    file_key = f"videos/{cam}/file_index"
                    chunk_key = f"videos/{cam}/chunk_index"
                    from_ts = float(val)
                    to_ts = float(row.get(to_key) or from_ts)
                    chunk_idx = int(row.get(chunk_key) or 0)
                    file_idx = int(row.get(file_key) or 0)
                    short = cam.replace("observation.images.", "")
                    rel = (
                        f"videos/{cam}/chunk-{chunk_idx:03d}/file-{file_idx:03d}.mp4"
                    )
                    mp4 = dataset_root / rel
                    if mp4.is_file():
                        entry["videos"].append(
                            {
                                "key": short,
                                "file": mp4.name,
                                "from_timestamp": from_ts,
                                "to_timestamp": to_ts,
                                "url": (
                                    f"/api/b601/dataset_video?repo_id={quote(repo_id, safe='')}"
                                    f"&rel={quote(rel, safe='')}"
                                ),
                            }
                        )
            ep_meta.append(entry)
    except Exception as exc:
        logger.debug("list_episodes via LeRobot failed (%s); falling back to info.json", exc)
        ep_meta = [{"episode_index": i, "length": 0, "videos": []} for i in range(total)]

    out: list[dict[str, Any]] = []
    for entry in ep_meta:
        i = int(entry["episode_index"])
        raw = mark_eps.get(str(i))
        verdict = None
        if isinstance(raw, dict) and raw.get("verdict") in ("ok", "bad"):
            verdict = raw["verdict"]
        out.append(
            {
                **entry,
                "verdict": verdict,
                "marked_at": (raw.get("ts") if isinstance(raw, dict) else None),
            }
        )
    return out


def delete_episodes_inplace(dataset_root: Path, repo_id: str, episode_indices: list[int]) -> dict[str, Any]:
    """Delete episodes and replace the dataset folder in place."""
    from lerobot.datasets.dataset_tools import delete_episodes
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    indices = sorted({int(i) for i in episode_indices})
    if not indices:
        raise ValueError("没有要删除的 episode")

    marks_before = load_marks(dataset_root)
    ds = LeRobotDataset(repo_id, root=dataset_root)
    total = int(ds.meta.total_episodes)
    invalid = [i for i in indices if i < 0 or i >= total]
    if invalid:
        raise ValueError(f"无效 episode 索引: {invalid}")
    if len(indices) >= total:
        raise ValueError("不能删光全部 episode，请至少保留 1 条")

    parent = dataset_root.parent
    tmp = parent / f".{dataset_root.name}_edit_{os.getpid()}"
    bak = parent / f".{dataset_root.name}_bak_{os.getpid()}"
    if tmp.exists():
        shutil.rmtree(tmp)
    if bak.exists():
        shutil.rmtree(bak)

    try:
        delete_episodes(ds, indices, output_dir=tmp, repo_id=repo_id)
        dataset_root.rename(bak)
        tmp.rename(dataset_root)
        shutil.rmtree(bak, ignore_errors=True)
    except Exception:
        # Best-effort rollback if swap failed mid-way.
        if not dataset_root.exists() and bak.exists():
            bak.rename(dataset_root)
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        raise

    remapped = remap_marks_after_delete(marks_before, indices)
    save_marks(dataset_root, remapped)
    new_total = total_episodes_from_info(dataset_root)
    return {
        "ok": True,
        "deleted": indices,
        "num_episodes": new_total,
        "marks": remapped,
    }
