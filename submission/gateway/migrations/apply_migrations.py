from __future__ import annotations

import argparse
import os
from pathlib import Path

import psycopg


MIGRATIONS_TABLE = "schema_migrations"
MIGRATIONS_DIR = Path(__file__).resolve().parent


def iter_migration_files() -> list[Path]:
    return sorted(
        path
        for path in MIGRATIONS_DIR.glob("*.sql")
        if path.is_file() and path.name[0].isdigit()
    )


def ensure_migrations_table(conn: psycopg.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MIGRATIONS_TABLE} (
            filename text PRIMARY KEY,
            applied_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def applied_migrations(conn: psycopg.Connection) -> set[str]:
    rows = conn.execute(f"SELECT filename FROM {MIGRATIONS_TABLE}").fetchall()
    return {row[0] for row in rows}


def apply_migration(conn: psycopg.Connection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    with conn.transaction():
        conn.execute(sql)
        conn.execute(
            f"INSERT INTO {MIGRATIONS_TABLE} (filename) VALUES (%s)",
            (path.name,),
        )


def apply_all(database_url: str) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(database_url) as conn:
        ensure_migrations_table(conn)
        seen = applied_migrations(conn)
        for path in iter_migration_files():
            if path.name in seen:
                continue
            apply_migration(conn, path)
            applied.append(path.name)
    return applied


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply UnionAgents SQL migrations.")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="PostgreSQL connection URL. Defaults to DATABASE_URL.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL is required or pass --database-url.")

    applied = apply_all(args.database_url)
    if applied:
        print("Applied migrations:")
        for filename in applied:
            print(f"- {filename}")
    else:
        print("No pending migrations.")


if __name__ == "__main__":
    main()
