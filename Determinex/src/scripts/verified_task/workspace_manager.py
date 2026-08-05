"""T-backed workspace leases for benchmark tasks."""

from __future__ import annotations

import os
import shutil
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .paths import default_verified_root, ensure_on_staging_root
from .task_spec import TaskSpec

SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "target",
    "dist",
    "build",
}


@dataclass(slots=True)
class WorkspaceLease:
    task_id: str
    root: Path
    workspace: Path
    temp: Path
    logs: Path
    corpus: Path


class WorkspaceManager:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_verified_root()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, spec: TaskSpec, *, copy_source: bool = True) -> WorkspaceLease:
        safe_id = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in spec.id)
        run_root = self.root / spec.benchmark / f"{safe_id}_{int(time.time())}"
        workspace = run_root / "workspace"
        temp = run_root / "tmp"
        logs = run_root / "logs"
        corpus = run_root / "corpus"
        for path in (workspace, temp, logs, corpus):
            path.mkdir(parents=True, exist_ok=True)
            ensure_on_staging_root(path)

        if copy_source and spec.repo_or_workspace:
            src = Path(spec.repo_or_workspace).resolve()
            if src.is_file():
                shutil.copy2(src, workspace / src.name)
            else:
                self._copy_tree(src, workspace)

        return WorkspaceLease(
            task_id=spec.id,
            root=run_root,
            workspace=workspace,
            temp=temp,
            logs=logs,
            corpus=corpus,
        )

    def archive(self, lease: WorkspaceLease, *, delete_original: bool = False) -> Path:
        archive_path = lease.root.with_suffix(".zip")
        ensure_on_staging_root(archive_path.parent)
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in lease.root.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(lease.root.parent))
        if delete_original:
            shutil.rmtree(lease.root)
        return archive_path

    def _copy_tree(self, src: Path, dst: Path) -> None:
        for root, dirs, files in os.walk(src):
            root_path = Path(root)
            dirs[:] = [d for d in dirs if d not in SKIP_DIR_NAMES]
            rel = root_path.relative_to(src)
            out_dir = dst / rel
            out_dir.mkdir(parents=True, exist_ok=True)
            for name in files:
                src_file = root_path / name
                out_file = out_dir / name
                try:
                    shutil.copy2(src_file, out_file)
                except OSError:
                    continue
