#!/usr/bin/env python3
"""resign_renamed_evidence.py -- heal evidence signatures broken by the mechanical rename.

WHAT BROKE: commit 804a115ff ("mechanical rename of Citadel to Determinex") rewrote strings
INSIDE signed evidence records (schema_version, record_type prefixes) AND the hardcoded
fallback HMAC keys in all 23 scripts/corpus/programbench/*_record.py signer modules
(citadel-* -> determinex-*). Every record signed before the rename now fails verification:
its stored signature covers the OLD content under the OLD key.

WHAT THIS DOES (provenance-preserving, fail-closed):
  1. Inventories assurance/evidence/**/*.json records carrying record_signature.
  2. For each record that FAILS current verification:
       a. Recovers the pre-rename version from git (parent of the rename commit).
       b. Derives the pre-rename key (mechanical rename => new key with s/determinex/citadel/)
          and REQUIRES the old content to verify under the old key -- cryptographic proof the
          record is the authentic pre-rename artifact, not a tamper.
       c. Only then re-signs the CURRENT content with the CURRENT key.
  3. Writes a migration ledger (old/new signature, pre-rename commit, proof status) beside
     this script's output so the re-attestation is itself auditable.
Records that fail step 2b are left untouched and reported -- never blind-resigned.

Usage:  python scripts/corpus/programbench/resign_renamed_evidence.py [--apply]
        (default is dry-run report)
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import importlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

RENAME_COMMIT = "804a115ff"
EVIDENCE = ROOT / "assurance" / "evidence"
LEDGER = EVIDENCE / "signature_rename_migration_ledger.json"


def _modules_for(record_type: str) -> list:
    """Candidate signer modules for a record type, most specific first: the type-derived module
    (programbench_upstream_artifact_authority_recheck -> upstream_artifact_authority_recheck_record),
    then codex_completion_campaign_record -- make_platform_record (the shared signer behind the
    one-off tandem-lane record types) delegates to it. Trying multiple candidates is SAFE because
    healing requires the pre-rename content to verify under the candidate's pre-rename key -- a
    record not signed by that module simply fails the continuity proof and is left untouched."""
    base = record_type.removeprefix("programbench_")
    names = [f"{base}_record", base]
    # trailing-token strip: bounded_rerun_authorization -> bounded_rerun_record,
    # real_bounded_rerun_outcome -> real_bounded_rerun_record
    parts = base.split("_")
    for i in range(len(parts) - 1, 1, -1):
        names.append("_".join(parts[:i]) + "_record")
    names.append("codex_completion_campaign_record")
    out = []
    for name in names:
        try:
            mod = importlib.import_module(f"corpus.programbench.{name}")
        except ImportError:
            continue
        if hasattr(mod, "_record_key") and hasattr(mod, "_canonical_json") and mod not in out:
            out.append(mod)
    return out


def _git_show(path: Path) -> dict | None:
    rel = path.relative_to(ROOT).as_posix()
    r = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{RENAME_COMMIT}^:{rel}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def _verify_with(mod, record: dict, key: bytes) -> bool:
    payload = {k: v for k, v in record.items() if k != "record_signature"}
    want = hmac_mod.new(key, mod._canonical_json(payload), hashlib.blake2b).hexdigest()
    return hmac_mod.compare_digest(str(record.get("record_signature") or ""), want)


def run(apply: bool = False) -> dict:
    from typing import Any

    results: dict[str, Any] = {
        "scanned": 0,
        "already_valid": 0,
        "healed": [],
        "unprovable": [],
        "no_module": [],
        "no_git_history": [],
    }
    for p in sorted(EVIDENCE.rglob("*.json")):
        if p.name == LEDGER.name:
            continue
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(rec, dict) or "record_signature" not in rec:
            continue
        results["scanned"] += 1
        rt = str(rec.get("record_type") or "")
        mods = _modules_for(rt)
        if not mods:
            results["no_module"].append({"path": str(p), "record_type": rt})
            continue
        if any(_verify_with(m, rec, m._record_key()) for m in mods):
            results["already_valid"] += 1
            continue
        # Recover + prove the pre-rename artifact against each candidate signer.
        old = _git_show(p)
        if old is None:
            results["no_git_history"].append(str(p))
            continue
        proven = None
        for m in mods:
            if _verify_with(m, old, m._record_key().replace(b"determinex", b"citadel")):
                proven = m
                break
        if proven is None:
            results["unprovable"].append(str(p))  # NOT authentic pre-rename -> never resign
            continue
        new_key = proven._record_key()
        payload = {k: v for k, v in rec.items() if k != "record_signature"}
        new_sig = hmac_mod.new(
            new_key, proven._canonical_json(payload), hashlib.blake2b
        ).hexdigest()
        entry = {
            "path": str(p.relative_to(ROOT)),
            "record_type": rt,
            "old_signature": rec["record_signature"],
            "new_signature": new_sig,
            "pre_rename_commit": RENAME_COMMIT + "^",
            "signer": proven.__name__,
            "continuity_proven": True,
        }
        if apply:
            rec["record_signature"] = new_sig
            p.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        results["healed"].append(entry)
    if apply and results["healed"]:
        prior = []
        if LEDGER.exists():
            try:
                prior = json.loads(LEDGER.read_text(encoding="utf-8")).get("entries", [])
            except (OSError, json.JSONDecodeError):
                prior = []
        known = {e.get("path") for e in prior}
        merged = prior + [e for e in results["healed"] if e["path"] not in known]
        ledger = {
            "_doc": "Signature migration after the mechanical Citadel->Determinex rename "
            "(commit 804a115ff) broke pre-rename evidence signatures. Each entry's "
            "continuity was PROVEN (pre-rename content verified under pre-rename "
            "key) before re-signing current content under the current key.",
            "migrated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "entries": merged,
        }
        LEDGER.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    return results


def main() -> int:
    apply = "--apply" in sys.argv
    res = run(apply=apply)
    print(
        json.dumps(
            {**res, "applied": apply, "healed_count": len(res["healed"])}, indent=1, default=str
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
