"""Package licensed source into a verifier-ready corpus intake manifest."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from corpus.code_ingest.deduper import Deduper
from corpus.code_ingest.license_detector import detect
from corpus.code_ingest.malware_pattern_scanner import scan_path as malware_scan
from corpus.code_ingest.quality_filter import assess as quality_assess
from corpus.code_ingest.secret_scanner import is_clean as secrets_clean
from corpus.code_ingest.source_fetcher import stage_local_source

DEFAULT_STAGING = Path(
    os.environ.get("DETERMINEX_CODE_INGEST_STAGING", "T:/determinex_corpus/intake_sources")
)
DEFAULT_MANIFEST_DIR = Path(
    os.environ.get("DETERMINEX_CODE_INGEST_MANIFESTS", "T:/determinex_corpus/intake_manifests")
)


@dataclass
class IntakeDecision:
    ingest_allowed: bool
    reasons: list[str] = field(default_factory=list)


def _hash_manifest(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.blake2b(raw, digest_size=32).hexdigest()


def assess_source(
    source: Path, *, benchmark: str = "code_ingest", staging_root: Path = DEFAULT_STAGING
) -> dict[str, Any]:
    fetched = stage_local_source(source, staging_root)
    staged = Path(fetched.staged_path)
    license_result = detect(staged)
    secret_ok = secrets_clean(staged)
    malware = malware_scan(staged)
    quality = quality_assess(staged)

    deduper = Deduper()
    duplicate_hits = 0
    for file_path in staged.rglob("*"):
        if not file_path.is_file():
            continue
        try:
            result = deduper.add(file_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if result.is_duplicate:
            duplicate_hits += 1

    reasons: list[str] = []
    if not license_result.ingest_allowed:
        reasons.append(f"license_not_green:{license_result.bucket}")
    if not secret_ok:
        reasons.append("secret_scan_failed")
    if not malware.clean:
        reasons.append("malware_pattern_scan_failed")
    if not quality.passed:
        reasons.extend(quality.reasons)
    # Duplicates are ranking signal, not an intake blocker. A source tree can
    # legitimately contain repeated license headers, generated shims, or small
    # equivalent examples; task extraction can down-rank them later.

    payload: dict[str, Any] = {
        "schema_version": "determinex-code-intake-v1",
        "captured_at": dt.datetime.now(dt.UTC).isoformat(),
        "benchmark": benchmark,
        "source": fetched.to_dict(),
        "license": license_result.to_dict(),
        "secret_scan": {"clean": secret_ok},
        "malware_scan": malware.to_dict(),
        "quality": quality.to_dict(),
        "dedupe": {"unique_files_seen": deduper.size, "duplicate_hits": duplicate_hits},
        "decision": IntakeDecision(ingest_allowed=not reasons, reasons=reasons).__dict__,
    }
    payload["manifest_hash"] = _hash_manifest(payload)
    return payload


def write_manifest(payload: dict[str, Any], out_dir: Path = DEFAULT_MANIFEST_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    source_name = Path(payload["source"]["staged_path"]).name
    path = out_dir / f"{source_name}.{payload['manifest_hash'][:12]}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--benchmark", default="code_ingest")
    parser.add_argument("--staging-root", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    args = parser.parse_args()
    payload = assess_source(args.source, benchmark=args.benchmark, staging_root=args.staging_root)
    path = write_manifest(payload, args.out_dir)
    print(path)
    print(json.dumps(payload["decision"], indent=2, sort_keys=True))
    return 0 if payload["decision"]["ingest_allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
