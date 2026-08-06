"""M6 migration: add skill_id / robot_type / train_backend / hf_model_id to existing tables.

Usage:
    cd apps/api
    python -m app.migrations.m6_skill_columns

Safe to run multiple times — uses IF NOT EXISTS / catches 'duplicate column'.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# Locate the DB file: derive from settings.DATABASE_URL
DB_PATH = Path(__file__).resolve().parents[2] / "botversex_dev.db"

MIGRATIONS: list[str] = [
    # datasets
    "ALTER TABLE datasets ADD COLUMN skill_id VARCHAR(128);",
    "ALTER TABLE datasets ADD COLUMN robot_type VARCHAR(64) DEFAULT 'so101';",
    # training_jobs
    "ALTER TABLE training_jobs ADD COLUMN skill_id VARCHAR(128);",
    "ALTER TABLE training_jobs ADD COLUMN train_backend VARCHAR(16) DEFAULT 'local';",
    # models
    "ALTER TABLE models ADD COLUMN skill_id VARCHAR(128);",
    "ALTER TABLE models ADD COLUMN robot_type VARCHAR(64) DEFAULT 'so101';",
    "ALTER TABLE models ADD COLUMN hf_model_id VARCHAR(256);",
]

BACKFILL: list[str] = [
    "UPDATE datasets SET skill_id = 'so101_generic_teleop' WHERE skill_id IS NULL;",
    "UPDATE datasets SET robot_type = 'so101' WHERE robot_type IS NULL;",
    "UPDATE training_jobs SET skill_id = 'so101_generic_teleop' WHERE skill_id IS NULL;",
    "UPDATE training_jobs SET train_backend = 'local' WHERE train_backend IS NULL;",
    "UPDATE models SET skill_id = 'so101_generic_teleop' WHERE skill_id IS NULL;",
    "UPDATE models SET robot_type = 'so101' WHERE robot_type IS NULL;",
]


def run() -> None:
    if not DB_PATH.exists():
        print(f"[SKIP] DB not found at {DB_PATH}; will be created on next app startup with new columns.")
        return

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    applied = 0
    for stmt in MIGRATIONS:
        try:
            cur.execute(stmt)
            applied += 1
            print(f"  [OK] {stmt.strip()}")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print(f"  [SKIP] already exists: {stmt.strip()[:60]}...")
            else:
                print(f"  [ERR] {e}: {stmt.strip()}")
    conn.commit()

    backfilled = 0
    for stmt in BACKFILL:
        try:
            cur2 = conn.cursor() if not conn else conn.cursor()
            cur2.execute(stmt)
            backfilled += cur2.rowcount
            print(f"  [OK] backfill: {stmt.strip()[:70]}... ({cur2.rowcount} rows)")
        except Exception as e:
            print(f"  [WARN] backfill: {e}")

    conn.commit()
    conn.close()
    print(f"\nM6 migration done: {applied} columns added, {backfilled} rows backfilled (DB: {DB_PATH})")


if __name__ == "__main__":
    run()
