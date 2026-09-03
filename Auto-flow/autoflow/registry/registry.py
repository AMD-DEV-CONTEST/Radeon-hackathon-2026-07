"""Skill Registry 实现。

基于本地 JSON 文件存储 Bundle，支持：
- 注册 (register)：保存 Bundle 到 bundles 目录
- 检索 (find)：关键词 + 可选 embedding 语义检索
- 版本管理 (get_versions / update)：v1 -> v2 ...
- 统计 (stats)：执行次数 / 成功率 / 成本对比

MVP 阶段使用 JSON 文件索引，避免引入 SQLite 依赖。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autoflow.config import get_settings
from autoflow.models import Bundle


class SkillRegistry:
    """Bundle 技能仓库。"""

    def __init__(self, index_path: Path | None = None) -> None:
        self.settings = get_settings()
        self.index_path = index_path or self.settings.registry_db
        self._index: dict[str, dict[str, Any]] = {}
        self._load()

    # ------------------------------------------------------------------ #
    # 注册 / 读取
    # ------------------------------------------------------------------ #

    def register(self, bundle: Bundle, tags: list[str] | None = None) -> str:
        """注册 Bundle，返回 task_id。"""
        self._save_bundle(bundle)
        entry = self._index.setdefault(
            bundle.task_id,
            {
                "task_id": bundle.task_id,
                "goal": bundle.goal,
                "tags": [],
                "versions": [],
                "latest_version": 0,
                "executions": {"count": 0, "success": 0, "halted": 0},
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        if tags:
            entry["tags"] = list(set(entry.get("tags", [])) | set(tags))
        entry["goal"] = bundle.goal
        self._touch_version(entry, bundle)
        self._save_index()
        return bundle.task_id

    def get(self, task_id: str, version: int | None = None) -> Bundle | None:
        """读取指定版本的 Bundle。version 为空返回最新。"""
        entry = self._index.get(task_id)
        if not entry:
            return None
        v = version or entry.get("latest_version", 1)
        path = self.settings.bundles_dir / task_id / f"v{v}" / "bundle.json"
        if not path.exists():
            return None
        return Bundle.model_validate_json(path.read_text(encoding="utf-8"))

    def list_all(self) -> list[dict[str, Any]]:
        """列出所有已注册任务摘要。"""
        return list(self._index.values())

    def get_versions(self, task_id: str) -> list[dict[str, Any]]:
        entry = self._index.get(task_id, {})
        return entry.get("versions", [])

    # ------------------------------------------------------------------ #
    # 检索
    # ------------------------------------------------------------------ #

    def find(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """检索匹配的 Bundle。

        MVP 使用关键词评分，未来可替换为 embedding 语义检索。
        """
        query_terms = set(self._tokenize(query))
        scored = []
        for entry in self._index.values():
            haystack = self._tokenize(entry.get("goal", "")) | set(entry.get("tags", []))
            overlap = query_terms & haystack
            score = len(overlap)
            if score > 0:
                scored.append({"task_id": entry["task_id"], "goal": entry["goal"], "score": score})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    # ------------------------------------------------------------------ #
    # 统计 / 更新
    # ------------------------------------------------------------------ #

    def record_run(self, task_id: str, status: str) -> None:
        entry = self._index.get(task_id)
        if not entry:
            return
        stats = entry.setdefault("executions", {"count": 0, "success": 0, "halted": 0})
        stats["count"] += 1
        if status == "success":
            stats["success"] += 1
        elif status in ("halted", "effect_failed"):
            stats["halted"] += 1
        self._save_index()

    def stats(self, task_id: str) -> dict[str, Any]:
        entry = self._index.get(task_id, {})
        stats = entry.get("executions", {})
        count = stats.get("count", 0) or 1
        success_rate = stats.get("success", 0) / count
        return {
            **stats,
            "success_rate": round(success_rate, 3),
            "estimated_ai_cost_per_run": 0.45,  # 对比基准
            "replay_cost_per_run": 0.0,
            "total_saved": round(stats.get("count", 0) * 0.45, 2),
        }

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #

    def _touch_version(self, entry: dict[str, Any], bundle: Bundle) -> None:
        v = bundle.version
        entry["latest_version"] = max(entry.get("latest_version", 0), v)
        versions = entry.get("versions", [])
        if not any(item.get("version") == v for item in versions):
            versions.append(
                {
                    "version": v,
                    "created_at": bundle.created_at,
                    "steps": len(bundle.steps),
                    "goal": bundle.goal,
                }
            )
        entry["versions"] = versions

    def _save_bundle(self, bundle: Bundle) -> None:
        vdir = self.settings.bundles_dir / bundle.task_id / f"v{bundle.version}"
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / "bundle.json").write_text(
            bundle.model_dump_json(indent=2), encoding="utf-8"
        )

    def _load(self) -> None:
        if self.index_path.exists():
            try:
                self._index = json.loads(self.index_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self._index = {}

    def _save_index(self) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps(self._index, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """简单中文/英文分词，用于关键词检索。

        中文片段同时生成 2-gram 双字 token，增强匹配能力。
        如 "表单提交" -> {"表单", "单提", "提交"}，可与长句共享 token。
        """
        tokens: set[str] = set()
        for m in re.findall(r"[a-zA-Z][a-zA-Z0-9_]{1,}", text):
            tokens.add(m.lower())
        for seg in re.findall(r"[\u4e00-\u9fff]{2,}", text):
            if len(seg) <= 4:
                tokens.add(seg)
            for i in range(len(seg) - 1):
                tokens.add(seg[i : i + 2])
        return tokens
