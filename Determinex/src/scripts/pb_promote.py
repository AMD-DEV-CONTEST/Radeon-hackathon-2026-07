"""
pb_promote.py — Promote a tool from pending_unlock to locked tier after passing eval.

Validates strict criteria, writes lock_metadata.json, moves directories,
updates eval_index.json, appends to lock_ledger.jsonl.

Usage:
  python scripts/pb_promote.py --tool entr --eval-report path/to/eval.json
  python scripts/pb_promote.py --tool entr  # finds latest_eval_result.json automatically
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
PB_DIR = ROOT / "corpus" / "programbench"
PENDING_BASE = PB_DIR / "pending_unlock"
LOCKED_BASE = PB_DIR / "locked"
TIER1 = LOCKED_BASE / "tier_1_perfect"
TIER2 = LOCKED_BASE / "tier_2_upstream_skips"
IN_PROGRESS = PB_DIR / "in_progress"
LOG_DIR = ROOT / "logs"
LOCK_LEDGER = LOG_DIR / "lock_ledger.jsonl"
INDEX_FILE = PB_DIR / "eval_index.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def git_describe() -> str:
    try:
        result = subprocess.run(
            ["git", "describe", "--always", "--dirty"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def ledger_contains(entry: dict) -> bool:
    if not LOCK_LEDGER.exists():
        return False
    keys = ("slug", "tier", "passed", "total", "source")
    try:
        with open(LOCK_LEDGER, encoding="utf-8") as f:
            for line in f:
                try:
                    existing = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if all(existing.get(key) == entry.get(key) for key in keys):
                    return True
    except OSError:
        return False
    return False


def safe_extract_tar(tar_path: Path, dest: Path) -> None:
    dest_resolved = dest.resolve()
    with tarfile.open(tar_path, "r:gz") as tf:
        members = tf.getmembers()
        for member in members:
            target = (dest / member.name).resolve()
            if target != dest_resolved and dest_resolved not in target.parents:
                raise ValueError(f"Unsafe tar member path: {member.name}")
        tf.extractall(dest, members)


def load_eval_report(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def validate_lock(data: dict) -> tuple[bool, dict, list[str]]:
    """Validate lock criteria. Returns (is_valid, counts, errors)."""
    tr = data.get("test_results", [])
    ctr = collections.Counter(r.get("status") for r in tr)
    total = len(tr)
    passed = ctr.get("passed", 0)
    not_run = ctr.get("not_run", 0)
    skipped = ctr.get("skipped", 0)
    failed = ctr.get("failure", 0) + ctr.get("failed", 0)
    pct = (passed / total * 100) if total else 0.0

    counts = dict(
        total=total, passed=passed, not_run=not_run, skipped=skipped, failed=failed, pct=pct
    )
    errors = []

    if passed != total:
        if not_run > 0:
            errors.append(f"FAIL: not_run={not_run} (must be 0)")
        if failed > 0:
            errors.append(f"FAIL: failed={failed} (must be 0)")
        if passed + skipped != total:
            errors.append(f"FAIL: passed({passed})+skipped({skipped}) != total({total})")

    # Determine tier
    if passed == total and not_run == 0 and failed == 0 and skipped == 0:
        tier = "tier_1_perfect"
        ok = True
    elif passed + skipped == total and not_run == 0 and failed == 0:
        tier = "tier_2_upstream_skips"
        ok = True
    else:
        tier = ""
        ok = False

    counts["tier"] = tier
    counts["status"] = (
        "strict_lock"
        if tier == "tier_1_perfect"
        else ("upstream_skips" if tier == "tier_2_upstream_skips" else "partial")
    )
    return ok, counts, errors


def find_tool_source_dir(slug: str) -> Path | None:
    """Find where the tool currently lives (pending_unlock or in_progress)."""
    for pri in ("priority_1_under100", "priority_2_under300", "priority_3_over300"):
        d = PENDING_BASE / pri / slug
        if d.exists():
            return d
    d = PENDING_BASE / slug
    if d.exists():
        return d
    d = IN_PROGRESS / slug
    if d.exists():
        return d
    # Also check legacy locked
    d = LOCKED_BASE / slug
    if d.exists():
        return d
    return None


def load_index() -> list[dict]:
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    return []


def save_index(index: list[dict]) -> None:
    INDEX_FILE.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")


def _ships_unproven_prebuilt_binary(slug: str, tarball_path: Path) -> tuple[bool, str]:
    """True if the submission ships a >2MB ELF (a potential answer-key binary) AND no
    from-source proof is on record for this slug. Reuses the provenance guard's proof
    registry -- a verified from-source build (pb_provenance_verify) clears the flag."""
    try:
        import determinex_pb_provenance_guard as PG

        proofs = PG.load_proofs()
    except Exception:
        proofs = {}
    if slug in proofs:
        return False, "from-source proof on record"
    try:
        with tarfile.open(tarball_path, "r:gz") as t:
            for m in t.getmembers():
                if m.isfile() and m.size > 2_000_000:
                    ef = t.extractfile(m)
                    if ef is not None and ef.read(4) == b"\x7fELF":
                        return True, (
                            f"ships a {m.size // 1024 // 1024}MB prebuilt binary "
                            f"({m.name}) with no from-source proof"
                        )
    except Exception as e:
        return False, f"scan error (allowing): {e}"
    return False, "no prebuilt binary shipped"


def promote_tool(
    slug: str,
    eval_data: dict | None = None,
    eval_report_path: Path | None = None,
    source: str = "unknown",
    tarball: Path | None = None,
) -> bool:
    print(f"\n{'-' * 60}")
    print(f"  PROMOTING: {slug}")

    # Load eval data
    if eval_data is None and eval_report_path:
        eval_data = load_eval_report(eval_report_path)
    if eval_data is None:
        # Try to find the latest eval result
        tool_dir = find_tool_source_dir(slug)
        if tool_dir:
            for candidate in ("latest_eval_result.json", "eval_report.json"):
                p = tool_dir / candidate
                if p.exists():
                    eval_data = load_eval_report(p)
                    break
    if eval_data is None:
        print(f"  ERROR: No eval data found for '{slug}'", file=sys.stderr)
        return False

    # Validate
    ok, counts, errors = validate_lock(eval_data)
    if not ok:
        print(f"  LOCK VALIDATION FAILED for '{slug}':")
        for err in errors:
            print(f"    {err}")
        return False

    # BUILD-PROVENANCE GATE (the atlas lesson, enforced inline): a lock whose submission
    # ships a prebuilt binary can pass via that answer-key ELF instead of building from
    # source. Refuse to archive such a lock unless a from-source proof is on record
    # (pb_provenance_verify rebuilds it with the binary removed and records the proof).
    _src_dir_for_prov = find_tool_source_dir(slug)
    _prov_tarball = tarball
    if _prov_tarball is None and _src_dir_for_prov:
        for _tn in ("submission_uncapped.tar.gz", "submission.tar.gz"):
            if (_src_dir_for_prov / _tn).exists():
                _prov_tarball = _src_dir_for_prov / _tn
                break
    if _prov_tarball and _prov_tarball.exists():
        ships, why = _ships_unproven_prebuilt_binary(slug, _prov_tarball)
        if ships:
            print(f"  PROVENANCE GATE FAILED for '{slug}': {why}")
            print(
                "    -> run: python scripts/pb_provenance_verify.py --slug <slug> "
                "--tarball <tarball>  (records a from-source proof), or repack to drop the binary."
            )
            return False

    tier = counts["tier"]
    tier_dir = TIER1 if tier == "tier_1_perfect" else TIER2

    print(f"  Tier: {tier}")
    print(
        f"  Score: {counts['passed']}/{counts['total']} "
        f"(nr={counts['not_run']}, sk={counts['skipped']}, fa={counts['failed']})"
    )

    # Determine destination
    dest_dir = tier_dir / slug
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Find source dir
    source_dir = find_tool_source_dir(slug)

    # Write eval_report.json
    eval_report_dest = dest_dir / "eval_report.json"
    if eval_report_path and eval_report_path.exists():
        shutil.copy2(eval_report_path, eval_report_dest)
    else:
        eval_report_dest.write_text(
            json.dumps(eval_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # Copy submission tarball if available
    tarball_dest = dest_dir / "submission.tar.gz"
    if tarball and tarball.exists():
        shutil.copy2(tarball, tarball_dest)
    elif source_dir:
        for tball_name in ("submission_uncapped.tar.gz", "submission.tar.gz"):
            t = source_dir / tball_name
            if t.exists():
                shutil.copy2(t, tarball_dest)
                break

    # Copy source/ dir if present. A supplied tarball is authoritative so the
    # archived source snapshot stays aligned with submission.tar.gz.
    dest_source = dest_dir / "source"
    if tarball and tarball.exists():
        if dest_source.exists():
            shutil.rmtree(dest_source)
        dest_source.mkdir(parents=True, exist_ok=True)
        safe_extract_tar(tarball, dest_source)
    elif source_dir and (source_dir / "source").exists() and not dest_source.exists():
        shutil.copytree(source_dir / "source", dest_source)

    # Compute hashes
    tarball_sha = sha256_file(tarball_dest) if tarball_dest.exists() else ""
    report_sha = sha256_file(eval_report_dest) if eval_report_dest.exists() else ""

    # Detect language from source dir
    language = "unknown"
    if source_dir:
        for f in (source_dir / "source").glob("**/*") if (source_dir / "source").exists() else []:
            if f.suffix in (".rs",):
                language = "rust"
                break
            elif f.suffix in (".go",):
                language = "go"
                break
            elif f.suffix in (".py",):
                language = "python"
                break
            elif f.suffix in (".c", ".h"):
                language = "c"
                break
            elif f.suffix in (".java",):
                language = "java"
                break

    # Was this a partial_eval_100 before?
    was_partial = False
    cap_removed = False
    if source_dir:
        ticket_path = source_dir / "unlock_ticket.json"
        if ticket_path.exists():
            try:
                ticket = json.loads(ticket_path.read_text())
                was_partial = True
                cap_removed = bool(ticket.get("cap_type"))
            except Exception:
                pass
        if (source_dir / "submission_uncapped.tar.gz").exists():
            cap_removed = True

    # Write lock_metadata.json
    meta = {
        "slug": slug,
        "locked_at": datetime.now(UTC).isoformat(),
        "locked_source": source,
        "official_passed": counts["passed"],
        "official_total": counts["total"],
        "official_not_run": counts["not_run"],
        "official_skipped": counts["skipped"],
        "official_failed": counts["failed"],
        "tier": tier,
        "eval_count": None,
        "override_type": "none",
        "language": language,
        "submission_sha256": tarball_sha,
        "eval_report_sha256": report_sha,
        "determinex_version": git_describe(),
        "was_partial_eval_100": was_partial,
        "cap_removed": cap_removed,
        "notes": "",
    }
    (dest_dir / "lock_metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # Append to lock_ledger.jsonl
    LOG_DIR.mkdir(exist_ok=True)
    ledger_entry = {
        "slug": slug,
        "locked_at": meta["locked_at"],
        "tier": tier,
        "passed": counts["passed"],
        "total": counts["total"],
        "source": source,
        "was_partial_eval_100": was_partial,
        "cap_removed": cap_removed,
    }
    if not ledger_contains(ledger_entry):
        with open(LOCK_LEDGER, "a", encoding="utf-8") as f:
            f.write(json.dumps(ledger_entry) + "\n")

    # Update eval_index.json
    index = load_index()
    found = False
    for e in index:
        if e["slug"] == slug:
            e["status"] = counts["status"]
            e["tier"] = tier
            e["official_score_pct"] = round(counts["pct"], 4)
            e["official_passed"] = counts["passed"]
            e["official_total"] = counts["total"]
            e["official_not_run"] = counts["not_run"]
            e["official_skipped"] = counts["skipped"]
            e["official_failed"] = counts["failed"]
            e["source"] = f"filesystem/{tier}"
            e["eval_report_path"] = str(eval_report_dest.relative_to(ROOT)).replace("\\", "/")
            e["eval_report_sha256"] = report_sha
            e["submission_sha256"] = tarball_sha
            e["last_eval_date"] = datetime.now(UTC).date().isoformat()
            e["last_eval_source"] = source
            e.pop("ceiling_reason", None)
            e.pop("sub_bucket", None)
            e.pop("ceiling_confirmed", None)
            e.pop("locked_version", None)
            found = True
            break
    if not found:
        index.append(
            {
                "slug": slug,
                "status": counts["status"],
                "tier": tier,
                "official_score_pct": round(counts["pct"], 4),
                "official_passed": counts["passed"],
                "official_total": counts["total"],
                "official_not_run": counts["not_run"],
                "official_skipped": counts["skipped"],
                "official_failed": counts["failed"],
                "priority": None,
                "assigned_to": None,
                "source": f"filesystem/{tier}",
                "eval_report_path": str(eval_report_dest.relative_to(ROOT)).replace("\\", "/"),
                "eval_report_sha256": report_sha,
                "submission_sha256": tarball_sha,
                "last_eval_date": datetime.now(UTC).date().isoformat(),
                "last_eval_source": source,
            }
        )

    # Re-sort: locks first, then by score
    def sort_key(e):
        ord = {
            "strict_lock": 0,
            "upstream_skips": 1,
            "pending_unlock": 2,
            "ceiling_confirmed": 3,
            "in_progress": 4,
            "partial": 5,
            "board_cache_only": 6,
        }
        return (ord.get(e.get("status", ""), 9), -(e.get("official_score_pct") or 0))

    # Preserve existing-row order to keep eval_index diffs focused. Only sort
    # when a new row had to be appended.
    if not found:
        index.sort(key=sort_key)
    save_index(index)

    strict_count = sum(1 for e in index if e.get("status") == "strict_lock")
    upstream_count = sum(1 for e in index if e.get("status") == "upstream_skips")

    print(f"\n  NEW LOCK: {slug} - {counts['passed']}/{counts['total']} [{tier}]")
    print(
        f"  Current counts: {strict_count} strict + {upstream_count} upstream = "
        f"{strict_count + upstream_count} total locks / 200 tools"
    )
    print(f"  Lock ledger: {LOCK_LEDGER}")
    print(f"  Lock metadata: {dest_dir / 'lock_metadata.json'}")

    return True


def main():
    parser = argparse.ArgumentParser(description="Promote a PB tool to locked status")
    parser.add_argument("--tool", required=True, help="Tool slug to promote")
    parser.add_argument("--eval-report", help="Path to eval report JSON")
    parser.add_argument("--source", default="local", help="Eval source: local, hetzner, etc.")
    parser.add_argument("--tarball", help="Path to (uncapped) submission tarball")
    args = parser.parse_args()

    eval_report_path = Path(args.eval_report) if args.eval_report else None
    tarball = Path(args.tarball) if args.tarball else None

    ok = promote_tool(
        args.tool,
        eval_report_path=eval_report_path,
        source=args.source,
        tarball=tarball,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
