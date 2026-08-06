"""一次性清理历史会话中的 [stub-answer] 残留。

背景：早期 XAI.app 用系统 python 启动、未注入模型 Key，导致对话返回 [stub-answer] 假回答，
这些残条留在 sessions.db。本脚本扫描并删除含 [stub-answer] 的消息（默认仅删除，安全）。

用法：python3 scripts/cleanup_stub_residue.py [--dry-run]
  --dry-run  只统计不删除
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

HOME = os.path.expanduser("~/.xai")
DB = os.path.join(HOME, "sessions.db")
MARKER = "[stub-answer]"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只统计不删除")
    args = ap.parse_args()

    if not os.path.exists(DB):
        print(f"[cleanup] sessions.db 不存在: {DB}")
        return 0

    conn = sqlite3.connect(DB, timeout=10)
    conn.execute("PRAGMA busy_timeout=5000")
    cur = conn.execute("SELECT id, session, role FROM messages WHERE content LIKE ?", (f"%{MARKER}%",))
    hits = cur.fetchall()
    print(f"[cleanup] 命中含 '{MARKER}' 的消息: {len(hits)} 条")
    if not hits:
        conn.close()
        return 0

    by_session: dict[str, int] = {}
    for _id, session, _role in hits:
        by_session[session] = by_session.get(session, 0) + 1
    for s, c in sorted(by_session.items(), key=lambda x: -x[1])[:10]:
        print(f"  - session={s[:40]}  残条={c}")

    if args.dry_run:
        print("[cleanup] --dry-run：未删除任何数据")
        conn.close()
        return 0

    conn.execute("DELETE FROM messages WHERE content LIKE ?", (f"%{MARKER}%",))
    conn.commit()
    print(f"[cleanup] 已删除 {len(hits)} 条 stub 残条")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
