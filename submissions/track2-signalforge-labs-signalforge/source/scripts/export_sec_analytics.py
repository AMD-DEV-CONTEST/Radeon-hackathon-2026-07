#!/usr/bin/env python3
"""Build a local DuckDB catalog and Zstandard Parquet files from SEC JSONL artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


TABLES = ("companies", "filings", "reported_facts", "normalized_metrics", "issues")


def sql_path(path: Path) -> str:
    return "'" + str(path.resolve()).replace("'", "''") + "'"


def export(source: Path, destination: Path, database: Path) -> dict:
    import duckdb

    destination.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database))
    try:
        outputs = {}
        for table in TABLES:
            jsonl = source / f"{table}.jsonl"
            if not jsonl.is_file():
                raise FileNotFoundError(jsonl)
            connection.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM read_json_auto({sql_path(jsonl)}, format='newline_delimited')")
            parquet = destination / f"{table}.parquet"
            connection.execute(f"COPY {table} TO {sql_path(parquet)} (FORMAT parquet, COMPRESSION zstd)")
            outputs[parquet.name] = {
                "sha256": hashlib.sha256(parquet.read_bytes()).hexdigest(),
                "rows": connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0],
            }
        connection.execute("CREATE OR REPLACE VIEW latest_metrics AS SELECT * FROM normalized_metrics")
        return outputs
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    outputs = export(args.source, args.output, args.database)
    manifest = {
        "schema_version": "signalforge/sec-analytics-manifest/v1",
        "duckdb_version": __import__("duckdb").__version__,
        "source_manifest_sha256": hashlib.sha256((args.source / "manifest.json").read_bytes()).hexdigest(),
        "files": outputs,
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
