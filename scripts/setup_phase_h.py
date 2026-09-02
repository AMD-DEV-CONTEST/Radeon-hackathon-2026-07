#!/usr/bin/env python
"""
Phase H 初始化脚本

创建 Phase H 所需数据库表并播种演示用户。

用法:
    python scripts/setup_phase_h.py [--db-path PATH]

默认 db-path 为 $SQLITE_PATH/projectpack.db 或 ./data/projectpack.db
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.phase_h_sql import seed_phase_h_tables


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase H Database Setup")
    parser.add_argument(
        "--db-path",
        default=os.environ.get("SQLITE_PATH", str(Path("data") / "projectpack.db")),
        help="Path to the SQLite database file",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[Phase H] Setting up tables in: {db_path}")
    seed_phase_h_tables(str(db_path))
    print("[Phase H] Tables created and demo users seeded successfully.")
    print("   Demo accounts:")
    print("     admin  / admin123  (管理员)")
    print("     pm     / pm123     (项目经理)")
    print("     member / member123 (团队成员)")
    print("     guest  / guest123  (只读访客)")


if __name__ == "__main__":
    main()
