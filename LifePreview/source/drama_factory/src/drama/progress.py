"""实时进度跟踪：被各 agent 调用 start/update/finish，落盘 `<project>/progress.json`，
供命令行监视器(tools/progress_monitor.py)与 Web 控制台读取——显示"进行到哪个镜头、
这个镜头生成到哪一步/帧"。

数据来源：
- 镜头级步进度来自 ComfyUI WebSocket 的 `progress` 事件(KSampler/采样器的 step/total)，
  由 comfy_client 在生成期间回调进来；
- 整体计数从 `<project>/shots/*_shot_list.json` 的 status 实时汇总。

线程安全：关键帧/视频 agent 在线程池里并行处理不同镜头，全部共享同一个 tracker。
写盘用临时文件 + os.replace 原子替换，读取方不会读到半个文件。
"""
from __future__ import annotations

import json
import threading
import time
from collections import Counter
from pathlib import Path

from .runtime import atomic_write_json

# 镜头完成度权重(与 watchdog 的 score 一致)：用于算整体百分比
_WEIGHT = {"keyframe_ok": 1, "clip_ok": 2, "voice_ok": 3, "done": 4}


class ProgressTracker:
    def __init__(self, project_root, min_interval: float = 0.7):
        self.root = Path(project_root)
        self.path = self.root / "progress.json"
        self.shots_dir = self.root / "shots"
        self._lock = threading.Lock()
        self._active: dict[str, dict] = {}   # shot_id -> 活跃镜头快照
        self._stage = ""
        self._episode = ""
        self._min_interval = float(min_interval)
        self._last_write = 0.0

    # ---------- agent 调用的三个钩子 ----------
    def set_stage(self, stage: str) -> None:
        with self._lock:
            self._stage = stage or self._stage
        self._flush(force=True)

    def start_shot(self, shot_id: str, stage: str, shard: int = 0,
                   instance: str = "", episode: str = "") -> None:
        with self._lock:
            self._stage = stage or self._stage
            if episode:
                self._episode = episode
            self._active[shot_id] = {
                "shot_id": shot_id, "stage": stage, "shard": int(shard),
                "instance": instance, "node": "", "step": 0, "total": 0,
                "pct": 0.0, "ts": time.time()}
        self._flush(force=True)

    def update_step(self, shot_id: str, node, step, total) -> None:
        """ComfyUI WS progress 回调：value=step, max=total, node=当前节点。"""
        with self._lock:
            a = self._active.get(shot_id)
            if a is None:
                return
            a["node"] = "" if node is None else str(node)
            a["step"] = int(step or 0)
            a["total"] = int(total or 0)
            a["pct"] = round(100.0 * a["step"] / a["total"], 1) if a["total"] else 0.0
        self._flush(force=False)

    def finish_shot(self, shot_id: str) -> None:
        with self._lock:
            self._active.pop(shot_id, None)
        self._flush(force=True)

    # ---------- 落盘 ----------
    def _overall(self) -> dict:
        c: Counter = Counter()
        try:
            for fp in sorted(self.shots_dir.glob("*_shot_list.json")):
                try:
                    d = json.loads(fp.read_text(encoding="utf-8"))
                    for s in d.get("shots", []):
                        c[s.get("status", "pending")] += 1
                except Exception:  # noqa: BLE001 — 文件可能正在被写, 跳过
                    pass
        except Exception:  # noqa: BLE001
            pass
        total = sum(c.values())
        wsum = sum(_WEIGHT.get(k, 0) * v for k, v in c.items())
        return {
            "total": total,
            "pending": c.get("pending", 0), "keyframe_ok": c.get("keyframe_ok", 0),
            "clip_ok": c.get("clip_ok", 0), "voice_ok": c.get("voice_ok", 0),
            "done": c.get("done", 0), "failed": c.get("failed", 0),
            "pct": round(100.0 * wsum / (total * 4), 1) if total else 0.0,
        }

    def _flush(self, force: bool = False) -> None:
        now = time.time()
        with self._lock:
            if not force and (now - self._last_write) < self._min_interval:
                return
            self._last_write = now
            active = [dict(a) for a in sorted(self._active.values(),
                                              key=lambda x: x["shard"])]
            stage, episode = self._stage, self._episode
        data = {"updated": now, "project": self.root.name, "episode": episode,
                "stage": stage, "overall": self._overall(), "active": active}
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self.path, data)
        except Exception:  # noqa: BLE001 — 进度写盘失败绝不拖垮流水线
            pass
