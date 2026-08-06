#!/usr/bin/env python3
"""Recompute usage_counters.storage_bytes for all users (Phase 2)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"
sys.path.insert(0, str(API))

from app.models.database import SessionLocal  # noqa: E402
from app.services.storage_meter import refresh_all_users  # noqa: E402


def main() -> None:
    db = SessionLocal()
    try:
        totals = refresh_all_users(db)
        print(f"Refreshed storage for {len(totals)} user(s)")
        for uid, nbytes in totals.items():
            print(f"  {uid}: {nbytes} bytes")
    finally:
        db.close()


if __name__ == "__main__":
    main()
