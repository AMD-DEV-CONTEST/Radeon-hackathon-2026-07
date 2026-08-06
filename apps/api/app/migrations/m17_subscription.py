"""M17 migration: subscription tiers, usage counters, marketplace tables.

Usage:
    cd apps/api
    python -m app.migrations.m17_subscription
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "botversex_dev.db"

USER_COLUMNS: list[str] = [
    "ALTER TABLE users ADD COLUMN subscription_tier VARCHAR(32) DEFAULT 'free';",
    "ALTER TABLE users ADD COLUMN tier_expires_at TIMESTAMP;",
    "ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR(128);",
]

TABLES: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS usage_counters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        metric VARCHAR(64) NOT NULL,
        period VARCHAR(7) NOT NULL,
        value INTEGER NOT NULL DEFAULT 0,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, metric, period)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS skill_listings (
        id TEXT PRIMARY KEY,
        skill_id VARCHAR(128) NOT NULL,
        seller_id TEXT NOT NULL,
        title VARCHAR(200) NOT NULL,
        description TEXT,
        price_cents INTEGER NOT NULL DEFAULT 0,
        currency VARCHAR(8) NOT NULL DEFAULT 'CNY',
        license_type VARCHAR(32) NOT NULL DEFAULT 'personal',
        revenue_share_bps INTEGER NOT NULL DEFAULT 3000,
        status VARCHAR(32) NOT NULL DEFAULT 'pending',
        is_active BOOLEAN NOT NULL DEFAULT 1,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS subscription_records (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        provider VARCHAR(32) NOT NULL,
        external_id VARCHAR(128),
        tier VARCHAR(32) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'active',
        current_period_start TIMESTAMP,
        current_period_end TIMESTAMP,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """,
]

BACKFILL: list[str] = [
    "UPDATE users SET subscription_tier = 'free' WHERE subscription_tier IS NULL;",
    "UPDATE users SET subscription_tier = 'creator' WHERE role = 'admin';",
]


def run() -> None:
    if not DB_PATH.exists():
        print(f"[SKIP] DB not found at {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    for stmt in USER_COLUMNS:
        try:
            cur.execute(stmt)
            print(f"  [OK] {stmt.strip()[:70]}")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print(f"  [SKIP] {stmt.strip()[:60]}")
            else:
                print(f"  [ERR] {e}")

    for stmt in TABLES:
        cur.executescript(stmt)
        print("  [OK] table ensured")

    conn.commit()

    for stmt in BACKFILL:
        try:
            cur.execute(stmt)
            print(f"  [OK] {stmt.strip()} ({cur.rowcount} rows)")
        except Exception as e:
            print(f"  [WARN] {e}")

    conn.commit()
    conn.close()
    print(f"\nM17 migration done (DB: {DB_PATH})")


if __name__ == "__main__":
    run()
