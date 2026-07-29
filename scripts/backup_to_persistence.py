#!/usr/bin/env python3
"""Backup mutable project artifacts into /workspace/persistence before maintenance.

Official notice: save important data under /workspace/persistence before
Friday 2026-07-31 18:00 (platform release / maintenance window).

Also prints a reminder to `git push` — code must not live only on the instance.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import DEFAULT_CLOUD_DATA_ROOT, DEFAULT_PERSISTENCE_BASE  # noqa: E402

# Deadline from AMD DevMaster Hackathon ops notice (UTC+8).
BACKUP_DEADLINE_NOTE = "2026-07-31 18:00 (UTC+8) — platform release/maintenance window"

MIGRATE_DIRS = [
    "vector_store",
    "memory",
    "uploads",
    "generated_projects",
    "workflows",
    "app_configs",
    "exports",
]


def _copy_tree(src: Path, dst: Path) -> int:
    if not src.exists():
        return 0
    n = 0
    dst.mkdir(parents=True, exist_ok=True)
    if src.is_file():
        shutil.copy2(src, dst)
        return 1
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        n += 1
    return n


def _git_snapshot(out: Path) -> None:
    info: dict[str, str] = {
        "backed_up_at": datetime.now(timezone.utc).isoformat(),
        "deadline_note": BACKUP_DEADLINE_NOTE,
        "cwd": str(ROOT),
    }
    try:
        def g(*args: str) -> str:
            return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()

        info["git_head"] = g("rev-parse", "HEAD")
        info["git_branch"] = g("rev-parse", "--abbrev-ref", "HEAD")
        info["git_status_short"] = g("status", "-sb")
        info["git_remote"] = g("remote", "-v")
    except Exception as exc:  # noqa: BLE001
        info["git_error"] = str(exc)
    out.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    print("=== PrivateLocalAgent · backup to persistence ===")
    print(f"Deadline: {BACKUP_DEADLINE_NOTE}")

    if not DEFAULT_PERSISTENCE_BASE.is_dir():
        print(f"[warn] {DEFAULT_PERSISTENCE_BASE} missing — not on Radeon Cloud PVC?")
        print("[hint] Still push code to GitHub; copy data/ elsewhere manually.")
        _git_snapshot(ROOT / "data" / "memory" / "last_backup_meta.json")
        print("[local] wrote data/memory/last_backup_meta.json (best-effort)")
        return

    dest = Path(os.getenv("PLA_DATA_ROOT", str(DEFAULT_CLOUD_DATA_ROOT))).expanduser()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snap = dest / "backups" / stamp
    live = dest / "data"
    snap.mkdir(parents=True, exist_ok=True)
    live.mkdir(parents=True, exist_ok=True)

    print(f"[dest] live={live}")
    print(f"[dest] snapshot={snap}")

    sources = [
        ROOT / "data",
        Path("/workspace/Radeon-hackathon-2026-07/data"),
        live,  # refresh snapshot from current persistence live tree too
    ]

    total = 0
    for src_data in sources:
        if not src_data.is_dir():
            continue
        print(f"[scan] {src_data}")
        for name in MIGRATE_DIRS:
            src = src_data / name
            if not src.exists():
                continue
            total += _copy_tree(src, live / name)
            total += _copy_tree(src, snap / name)

    # lightweight config copies (no secrets printed)
    for rel in ("configs/default.yaml", "configs/radeon_cloud.yaml", ".env.example"):
        src = ROOT / rel
        if src.exists():
            dst = snap / "repo_meta" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    # HF cache stays in place; only record path
    hf = Path(os.getenv("HF_HOME", str(DEFAULT_PERSISTENCE_BASE / "huggingface")))
    hf.mkdir(parents=True, exist_ok=True)
    meta = {
        "hf_home": str(hf),
        "pla_data_root": str(dest),
        "files_copied_approx": total,
    }
    (snap / "backup_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    _git_snapshot(snap / "git_snapshot.json")
    _git_snapshot(live / "memory" / "last_backup_meta.json")

    print(f"[ok] copied≈{total} files into persistence")
    print("[must] git push your branch to GitHub (do not keep code only on the instance)")
    print("       git add -A && git commit -m 'chore: pre-maintenance backup' && git push")
    print(f"[path] {snap}")


if __name__ == "__main__":
    main()
