"""Stage the full corpus as a Hugging Face dataset — everything git cannot carry.

THE SPLIT, AND WHY IT IS NOT ARBITRARY. The public git repo carries the knowledge layer: the
oracles, our `compile.sh` recipes, the board, `build_knowledge.json`, and `canonical_tasks.json`
which pins repository+commit for all 200 tasks (1,709 files, 69 MB). It cannot carry the rest —
158,788 files and a 9.73 GiB pack, against GitHub's 1 GB soft limit and 100 MB per-file hard limit.
A dataset host is built for exactly that, and this stages the upload.

WHAT IS EXCLUDED, AND WHY THAT IS NOT NEGOTIABLE. A vendored tree with no license text is withheld
here as well. Redistribution is redistribution: moving other people's code to a different host does
not change what MIT, BSD, ISC and Apache-2.0 require, and we cannot supply a copyright notice we do
not have. The boundary comes from `third_party_corpus_audit.py --manifest`, so the repo and the
dataset enforce ONE decision rather than two that can drift apart.

    python scripts/release/third_party_corpus_audit.py --manifest corpus/REDISTRIBUTION_BOUNDARY.json
    python scripts/release/export_corpus_dataset.py --into .tmp/determinex-corpus-dataset

This script STAGES only. It does not upload, and it holds no credentials: pushing a dataset under
someone's account is their action to take, with their token, after they have read what is in it.
The staged directory is ready for `huggingface-cli upload`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

BOUNDARY = Path("corpus") / "REDISTRIBUTION_BOUNDARY.json"
NOTICES = Path("corpus") / "THIRD_PARTY_NOTICES.md"


def _tracked_corpus() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "corpus"], cwd=_ROOT, capture_output=True, timeout=1800
    )
    return [p for p in out.stdout.decode("utf-8", errors="replace").split("\0") if p]


def load_boundary(root: Path) -> tuple[set[str], list[dict], int]:
    """(withheld tree prefixes, withheld rows, publishable project count)."""
    path = root / BOUNDARY
    if not path.is_file():
        raise SystemExit(
            f"missing {BOUNDARY}. Generate it first:\n"
            "  python scripts/release/third_party_corpus_audit.py "
            f"--manifest {BOUNDARY.as_posix()}"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    withheld = data.get("withheld", [])
    prefixes = {str(row["path"]).replace("\\", "/").rstrip("/") + "/" for row in withheld}
    return prefixes, withheld, int(data.get("publishable_count", 0))


def dataset_card(published: int, withheld: list[dict], file_count: int, size_mb: float) -> str:
    return f"""---
license: agpl-3.0
pretty_name: Determinex Corpus
tags:
  - code
  - benchmark
  - programbench
  - swe-bench
---

# Determinex Corpus

The knowledge layer and vendored upstream trees that the Determinex **Native Reimplementation
Loop** learns from: for each CLI tool, the real upstream source at a pinned commit plus a real test
oracle, so a model reimplements against ground truth rather than against a description.

**{file_count:,} files, {size_mb:,.0f} MB, {published} vendored projects.**

## Licensing — read this first

Determinex's own code is **AGPL-3.0-or-later**. **This dataset is not all Determinex's code.**
Each vendored project here remains under **its own license, held by its own copyright holders**,
and nothing is relicensed by inclusion. These are separate programs distributed together — mere
aggregation.

Every project's license text travels with its tree, and `THIRD_PARTY_NOTICES.md` lists all of them
with SPDX identifier, upstream URL and pinned commit. **If you redistribute any part of this
dataset, those licenses bind you, not Determinex's.**

{len(withheld)} tree(s) present in the working repository are **excluded** from this dataset
because they carry no license text and none could be recovered from upstream. They are listed in
`THIRD_PARTY_NOTICES.md`. Fetch them from their own maintainers instead:

```bash
determinex corpus fetch <tool>
```

## What is here

| Path | Contents |
| --- | --- |
| `programbench/canonical_tasks.json` | repository + commit pinned for all 200 tasks |
| `programbench/eval_index.json` | per-tool rows with `eval_report_sha256` |
| `programbench/build_knowledge.json` | learned SYMPTOM to FIX classes |
| `programbench/per_tool_overrides/` | our `compile.sh` recipes inside each upstream checkout |
| `programbench/locked/` | archived evaluations and their source trees |
| `THIRD_PARTY_NOTICES.md` | every vendored project, its license, upstream and commit |

## Verifying an evaluation

The public git repo carries `eval_index.json` with `eval_report_sha256` for each row; this dataset
carries the reports. Hash the report you downloaded and compare — that proves the artifact is the
one the published number came from.

## Source

<https://github.com/DarthCeltic/determinex>
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--into", type=Path, default=Path(".tmp/determinex-corpus-dataset"))
    parser.add_argument("--dry-run", action="store_true", help="report what would be staged")
    args = parser.parse_args()

    root = Path.cwd()
    withheld_prefixes, withheld_rows, publishable = load_boundary(root)
    print(f"boundary: {len(withheld_rows)} tree(s) withheld for want of a license text\n")

    paths = _tracked_corpus()
    staged, skipped = [], 0
    for rel in paths:
        posix = rel.replace("\\", "/")
        if any(posix.startswith(prefix) for prefix in withheld_prefixes):
            skipped += 1
            continue
        staged.append(rel)

    total = sum((root / p).stat().st_size for p in staged if (root / p).is_file())
    print(f"  tracked corpus files : {len(paths):,}")
    print(f"  staged for dataset   : {len(staged):,}  ({total / 1e6:,.0f} MB)")
    print(f"  excluded (unlicensed): {skipped:,}")

    if args.dry_run:
        print("\nDry run — nothing written.")
        return 0

    dest = args.into if args.into.is_absolute() else root / args.into
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    for rel in staged:
        src = root / rel
        if not src.is_file():
            continue
        # corpus/x/y -> <dest>/x/y : the dataset root IS the corpus.
        target = dest / Path(rel).relative_to("corpus")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)

    notices = root / NOTICES
    if notices.is_file():
        shutil.copy2(notices, dest / "THIRD_PARTY_NOTICES.md")
    (dest / "README.md").write_text(
        dataset_card(publishable, withheld_rows, len(staged), total / 1e6), encoding="utf-8"
    )

    print(f"\nstaged at {dest}")
    print("\nNOT uploaded. Publishing under an account is the account holder's action:")
    print(f"  huggingface-cli upload <user>/determinex-corpus {dest} --repo-type dataset")
    print("\nRead THIRD_PARTY_NOTICES.md before you do — it states what other people own in here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
