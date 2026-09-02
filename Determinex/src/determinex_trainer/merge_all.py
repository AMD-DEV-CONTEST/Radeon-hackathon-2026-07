"""
merge_all.py — Deduplicate and merge all corpus JSONL files
============================================================
Reads every .jsonl from the real_scale directory, deduplicates by
SHA256(output.strip()), and writes corpus_deduped.jsonl to the merged dir.

SQL cap: examples where partition_corpus.py would route to specialist_sql
are capped at 40K to prevent SQL dominating the specialist slot.

Usage:
  python determinex_trainer/merge_all.py
  python determinex_trainer/merge_all.py --in ${DETERMINEX_MODELS_DIR:-~/determinex-models}/corpus/real_scale --out ${DETERMINEX_MODELS_DIR:-~/determinex-models}/corpus/merged
"""

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

_DEFAULT_IN = (
    Path(os.environ.get("DETERMINEX_MODELS_DIR", str(Path.home() / "determinex-models")))
    / "corpus/real_scale"
)
_DEFAULT_OUT = (
    Path(os.environ.get("DETERMINEX_MODELS_DIR", str(Path.home() / "determinex-models")))
    / "corpus/merged"
)

# SQL output detection — matches partition_corpus.py's _SQL_OUTPUT pattern
_SQL_RE = re.compile(
    r"\b(SELECT|INSERT\s+INTO|UPDATE\s+\w|DELETE\s+FROM|CREATE\s+TABLE|"
    r"ALTER\s+TABLE|DROP\s+TABLE|WITH\s+\w+\s+AS|JOIN\s+\w|GROUP\s+BY|"
    r"ORDER\s+BY|HAVING|UNION|EXCEPT|INTERSECT)\b",
    re.I,
)

SQL_CAP = 40_000


def sha256(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8", errors="replace")).hexdigest()


def merge(in_dir: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "corpus_deduped.jsonl"

    sources = sorted(in_dir.glob("*.jsonl"))
    if not sources:
        print(f"[ERROR] No .jsonl files found in {in_dir}")
        sys.exit(1)

    print(f"\nReading from: {in_dir}")
    print(f"Output:       {out_path}")
    print(f"Sources:      {len(sources)} files\n")

    seen: set[str] = set()
    kept: list[dict] = []
    sql_count = 0
    total_raw = 0
    skipped_dup = 0
    skipped_sql_cap = 0
    skipped_bad = 0

    for src in sources:
        file_kept = 0
        try:
            with open(src, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    total_raw += 1
                    try:
                        ex = json.loads(line)
                    except json.JSONDecodeError:
                        skipped_bad += 1
                        continue

                    output = ex.get("output", "") or ""
                    key = sha256(output)

                    if key in seen:
                        skipped_dup += 1
                        continue

                    # SQL cap
                    if _SQL_RE.search(output):
                        if sql_count >= SQL_CAP:
                            skipped_sql_cap += 1
                            continue
                        sql_count += 1

                    seen.add(key)
                    kept.append(ex)
                    file_kept += 1

        except Exception as e:
            print(f"  [WARN] {src.name}: {e}")
            continue

        if file_kept:
            print(f"  {src.name}: kept {file_kept:,}")

    print(f"\nWriting {len(kept):,} unique examples...")
    with open(out_path, "w", encoding="utf-8") as f:
        for ex in kept:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print("\n" + "=" * 60)
    print("MERGE RESULTS")
    print("=" * 60)
    print(f"  Total raw read:      {total_raw:>10,}")
    print(
        f"  Duplicates removed:  {skipped_dup:>10,}  ({skipped_dup / max(total_raw, 1) * 100:.1f}%)"
    )
    print(f"  SQL cap removed:     {skipped_sql_cap:>10,}  (cap={SQL_CAP:,})")
    print(f"  Bad JSON skipped:    {skipped_bad:>10,}")
    print(f"  Unique kept:         {len(kept):>10,}")
    print(f"  SQL examples kept:   {sql_count:>10,}")
    print(f"\n  Output: {out_path}")
    print("\n  Next step:")
    print("    python scripts/partition_corpus.py")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge and deduplicate corpus")
    parser.add_argument("--in", dest="in_dir", type=Path, default=_DEFAULT_IN)
    parser.add_argument("--out", dest="out_dir", type=Path, default=_DEFAULT_OUT)
    args = parser.parse_args()
    merge(args.in_dir, args.out_dir)


if __name__ == "__main__":
    main()
