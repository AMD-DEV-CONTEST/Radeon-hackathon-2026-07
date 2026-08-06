"""
Agent 群聊系统 - 工作区事务管理器

职责：
1. 为每个 run 创建独立 staging 目录（从当前 revision 全量复制）
2. Run 结束时检测变更（manifest 差分）
3. 三方合并：检测冲突（文本/二进制）
4. 提交成功：生成新 revision

策略：可移植全量复制 + manifest 差分（文档 §11.2 推荐）
- 每次从 committed 全量复制到 staging（跨平台兼容）
- 用 file_sha256 生成 manifest
- 文本冲突用 difflib 三方合并
- 二进制/同区域冲突生成结构化冲突记录
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any

from agent_factory.agent_group_system.store import AgentGroupStore
from agent_factory.file_utils import file_sha256


_GROUP_COMMIT_LOCKS: dict[str, threading.RLock] = defaultdict(threading.RLock)


class WorkspaceTransactionManager:
    """工作区事务管理器"""

    def __init__(self, store: AgentGroupStore, logger: logging.Logger | None = None):
        self.store = store
        self.logger = logger or logging.getLogger(__name__)

    def initialize_workspace(self, group_id: str) -> None:
        """Capture the selected shared directory as immutable revision zero."""
        with _GROUP_COMMIT_LOCKS[group_id]:
            workdir = self.store.group_workdir(group_id)
            revision_root = self.store.group_workspace_revision_root(group_id, 0)
            if revision_root.exists():
                shutil.rmtree(revision_root)
            revision_root.mkdir(parents=True, exist_ok=True)
            if workdir.exists() and any(workdir.iterdir()):
                self._copy_tree(workdir, revision_root)
            self.store.replace_initial_workspace_manifest(
                group_id,
                self._build_manifest(revision_root),
            )

    def prepare_staging(self, group_id: str, group_run_id: str, base_revision: int) -> Path:
        """
        为 run 准备 staging 目录（全量复制）

        返回：staging 根路径
        """
        staging_root = self.store.group_staging_root(group_id, group_run_id)
        committed_root = self.store.group_workdir(group_id)
        base_root = self.store.group_workspace_revision_root(group_id, base_revision)

        self.logger.info(f"Preparing staging for run {group_run_id[:8]}, base revision {base_revision}")

        # 清理旧 staging（如果存在）
        if staging_root.exists():
            shutil.rmtree(staging_root)

        staging_root.mkdir(parents=True, exist_ok=True)

        # Staging must start from the run's immutable base revision, not whichever run committed last.
        source_root = base_root if base_root.exists() else committed_root
        if source_root.exists() and any(source_root.iterdir()):
            self._copy_tree(source_root, staging_root)
            self.logger.info(f"Copied workspace: {source_root} -> {staging_root}")
        else:
            self.logger.info("Base workspace empty, staging starts clean")

        return staging_root

    def commit_staging(
        self, group_id: str, group_run_id: str, base_revision: int
    ) -> dict[str, Any]:
        with _GROUP_COMMIT_LOCKS[group_id]:
            return self._commit_staging(group_id, group_run_id, base_revision)

    def recover_pending_commits(self) -> list[dict[str, Any]]:
        """Resume durable commit journals left by a process interruption."""
        recovered: list[dict[str, Any]] = []
        for journal in self.store.list_pending_workspace_commits():
            group_id = str(journal["group_id"])
            group_run_id = str(journal["group_run_id"])
            staging_root = self.store.group_staging_root(group_id, group_run_id)
            with _GROUP_COMMIT_LOCKS[group_id]:
                if not staging_root.exists():
                    self.store.update_workspace_commit(str(journal["commit_id"]), {"status": "aborted"})
                    recovered.append({"commit_id": journal["commit_id"], "status": "aborted"})
                    continue
                result = self._commit_staging(
                    group_id,
                    group_run_id,
                    int(journal["source_revision"]),
                    commit_id=str(journal["commit_id"]),
                )
                recovered.append({"commit_id": journal["commit_id"], **result})
        return recovered

    def _commit_staging(
        self, group_id: str, group_run_id: str, base_revision: int, *, commit_id: str | None = None
    ) -> dict[str, Any]:
        """
        提交 staging 变更（三方合并 + 冲突检测）

        返回：
        {
            "success": bool,
            "target_revision": int | None,
            "conflicts": [{"path": str, "type": "content"|"binary"}]
        }
        """
        self.logger.info(f"Committing staging for run {group_run_id[:8]}")

        staging_root = self.store.group_staging_root(group_id, group_run_id)
        committed_root = self.store.group_workdir(group_id)
        base_root = self.store.group_workspace_revision_root(group_id, base_revision)

        commit_id = commit_id or self.store.create_workspace_commit(group_id, group_run_id, base_revision)

        # 1. 生成 staging manifest
        staging_manifest = self._build_manifest(staging_root)

        # 2. 获取 base 和 current manifests
        base_revision_record = self.store.get_workspace_revision(group_id, base_revision)
        base_manifest = base_revision_record["file_manifest"] if base_revision_record else {}

        # 获取当前最新 revision
        with self.store._connect() as conn:
            current_revision = self.store._current_workspace_revision(conn, group_id)

        current_revision_record = self.store.get_workspace_revision(group_id, current_revision)
        current_manifest = (
            current_revision_record["file_manifest"] if current_revision_record else {}
        )

        # 3. 检测变更
        staging_changes = self._detect_changes(base_manifest, staging_manifest)
        concurrent_changes = self._detect_changes(base_manifest, current_manifest)

        self.logger.info(
            f"Changes: staging={len(staging_changes)}, concurrent={len(concurrent_changes)}"
        )

        # 4. 冲突检测
        conflicts = self._detect_conflicts(
            staging_changes, concurrent_changes, staging_root, base_root, committed_root
        )

        if conflicts:
            self.logger.warning(f"Conflicts detected: {len(conflicts)}")
            self.store.update_workspace_commit(
                commit_id,
                {"status": "conflict", "conflict_files_json": json.dumps(conflicts, ensure_ascii=False)},
            )
            return {"success": False, "target_revision": None, "conflicts": conflicts}

        # 5. 无冲突，应用变更
        self._apply_changes(staging_changes, staging_root, committed_root)
        self.store.update_workspace_commit(commit_id, {"status": "files_committed"})

        # 6. 生成新 revision
        new_manifest = self._build_manifest(committed_root)
        new_revision = self.store.add_workspace_revision(
            group_id, new_manifest, parent_revision=base_revision
        )
        snapshot_root = self.store.group_workspace_revision_root(group_id, new_revision)
        if snapshot_root.exists():
            shutil.rmtree(snapshot_root)
        self._copy_tree(committed_root, snapshot_root)
        self.store.update_workspace_commit(
            commit_id,
            {"status": "context_committed", "target_revision": new_revision},
        )
        self.store.update_workspace_commit(
            commit_id,
            {"status": "completed", "target_revision": new_revision},
        )

        self.logger.info(f"Committed successfully: revision {new_revision}")

        # 7. 清理 staging
        if staging_root.exists():
            shutil.rmtree(staging_root)

        return {"success": True, "target_revision": new_revision, "conflicts": []}

    def _build_manifest(self, root: Path) -> dict[str, str]:
        """构建文件清单 {path: sha256}"""
        manifest = {}
        if not root.exists():
            return manifest

        for file_path in root.rglob("*"):
            if file_path.is_file():
                rel_path = str(file_path.relative_to(root))
                try:
                    manifest[rel_path] = file_sha256(file_path)
                except Exception as e:
                    self.logger.warning(f"Failed to hash {rel_path}: {e}")

        return manifest

    def _detect_changes(
        self, base_manifest: dict[str, str], target_manifest: dict[str, str]
    ) -> dict[str, str]:
        """
        检测变更

        返回：{"path": "add"|"modify"|"delete"}
        """
        changes = {}

        # 新增和修改
        for path, sha in target_manifest.items():
            if path not in base_manifest:
                changes[path] = "add"
            elif base_manifest[path] != sha:
                changes[path] = "modify"

        # 删除
        for path in base_manifest:
            if path not in target_manifest:
                changes[path] = "delete"

        return changes

    def _detect_conflicts(
        self,
        staging_changes: dict[str, str],
        concurrent_changes: dict[str, str],
        staging_root: Path,
        base_root: Path,
        committed_root: Path,
    ) -> list[dict[str, Any]]:
        """
        检测冲突

        冲突类型：
        - 同一文件被双方修改（需要三方合并）
        - 二进制文件冲突（无法自动合并）
        """
        conflicts = []
        conflicting_paths = set(staging_changes.keys()) & set(concurrent_changes.keys())

        for path in conflicting_paths:
            staging_action = staging_changes[path]
            concurrent_action = concurrent_changes[path]

            # 同类操作（都删除）不算冲突
            if staging_action == "delete" and concurrent_action == "delete":
                continue

            # 尝试三方合并（仅文本文件）
            if staging_action == "modify" and concurrent_action == "modify":
                staging_file = staging_root / path
                base_file = base_root / path
                committed_file = committed_root / path

                if base_file.exists() and self._is_text_file(staging_file) and self._is_text_file(committed_file):
                    merge_result = self._three_way_merge(staging_file, base_file, committed_file)
                    if merge_result["success"]:
                        staging_file.write_text(str(merge_result["merged_content"]), encoding="utf-8")
                        continue

            # 其他情况视为冲突
            conflicts.append({"path": path, "type": "content"})

        return conflicts

    def _three_way_merge(self, incoming_file: Path, base_file: Path, current_file: Path) -> dict[str, Any]:
        """Use Git's proven diff3 implementation against the immutable base snapshot."""
        try:
            result = subprocess.run(
                ["git", "merge-file", "-p", str(incoming_file), str(base_file), str(current_file)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if result.returncode == 0:
                return {"success": True, "merged_content": result.stdout}
            return {"success": False, "merged_content": None}
        except OSError as exc:
            self.logger.warning("Merge failed: %s", exc)
            return {"success": False, "merged_content": None}

    def _is_text_file(self, file_path: Path) -> bool:
        """判断是否为文本文件（简化实现）"""
        text_extensions = {".txt", ".md", ".py", ".js", ".json", ".yaml", ".yml", ".toml", ".xml", ".html", ".css", ".sh"}
        return file_path.suffix.lower() in text_extensions

    def _apply_changes(
        self, changes: dict[str, str], staging_root: Path, committed_root: Path
    ) -> None:
        """应用变更到 committed"""
        committed_root.mkdir(parents=True, exist_ok=True)

        for path, action in changes.items():
            staging_file = staging_root / path
            committed_file = committed_root / path

            if action == "delete":
                if committed_file.exists():
                    committed_file.unlink()
                    self.logger.debug(f"Deleted: {path}")

            elif action in ("add", "modify"):
                committed_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(staging_file, committed_file)
                self.logger.debug(f"{action.capitalize()}: {path}")

    def _copy_tree(self, src: Path, dst: Path) -> None:
        """递归复制目录树"""
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.rglob("*"):
            if item.is_file():
                rel_path = item.relative_to(src)
                dst_file = dst / rel_path
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dst_file)
