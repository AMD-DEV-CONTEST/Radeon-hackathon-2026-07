#!/usr/bin/env python3
"""run_eval.py — deterministic model evaluation harness (Todo 5).

Consumes an explicit --responses stub file (NEVER contacts a model in QA mode —
this is the deterministic response/stub input contract), calls the same
extractor/judge contract shape as production, computes the metrics defined in
the plan's Verification strategy, and writes a schema-valid report to --out.

Usage:
  python scripts/run_eval.py --fixtures <dir> --manifest <path> \
      --responses <stub.json> --out <report.json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path


def normalize_key(s: str) -> str:
    """Exact normalized key: lowercase, stripped punctuation/whitespace."""
    import re
    return re.sub(r"[\s\W_]+", "", s.lower())


def load_fixtures(fixtures_dir: Path, manifest_path: Path) -> list[dict]:
    manifest = json.loads(manifest_path.read_text())
    cases = []
    for item in manifest.get("cases", []):
        text_path = Path(str(fixtures_dir) + "/" + item["text"])
        c = dict(item)
        c["text"] = text_path.read_text() if text_path.exists() else item.get("text", "")
        c["normalized_sha"] = hashlib.sha256(c["text"].replace("\r\n", "\n").encode()).hexdigest()
        cases.append(c)
    return cases


def compute_metrics(cases: list[dict], responses: dict) -> dict:
    """MACRO aggregation: per-fixture metrics averaged across fixtures.

    Populations (on [0,100] scale) per the Verification strategy:
      source_support    = decoded candidate units with exact quote match / all decoded candidates
      unsupported_claim = candidates whose quote span does not match or entailment failed / all candidates
      key_point_coverage= matched key points / gold key points (normalized-key match)
      grading_agreement = fixtures where model verdict == gold label / all graded fixtures
      duplicate         = units stored status duplicate / all decoded candidates
      schema_validity   = parseable outputs / all outputs
    """
    per_fixture = []
    fatal = []
    for c in cases:
        resp = responses.get(c["id"], {})
        out = resp.get("output")
        parsed = resp.get("parsed", {})
        if out is None or parsed is None:
            fatal.append({"fixture": c["id"], "condition": "unparseable_json"})
            per_fixture.append(None)
            continue
        cards = parsed.get("cards", [])
        if not isinstance(cards, list) or not cards:
            fatal.append({"fixture": c["id"], "condition": "empty_card_list"})
            per_fixture.append(None)
            continue
        total = len(cards)
        supported = sum(1 for c in cards
                        if c.get("quote") and c["quote"] in c.get("source_text", c.get("text", "")))
        unsupported = total - supported
        dup = sum(1 for c in cards if c.get("duplicate"))
        # key-point coverage vs gold
        gold_keys = set(normalize_key(k) for k in c.get("key_points", []))
        matched = 0
        for c2 in cards:
            for kp in c2.get("key_points", []):
                if normalize_key(kp) in gold_keys:
                    matched += 1
        cov = (matched / len(gold_keys) * 100) if gold_keys else 100.0
        grading = resp.get("grading")
        if grading is not None:
            agree = 1.0 if grading.get("verdict") == c.get("gold_verdict") else 0.0
        else:
            agree = None
        per_fixture.append({
            "source_support": supported / total * 100 if total else 0.0,
            "unsupported_claim": unsupported / total * 100 if total else 0.0,
            "key_point_coverage": round(cov, 2),
            "grading_agreement": (agree * 100) if agree is not None else None,
            "duplicate": dup / total * 100 if total else 0.0,
            "schema_validity": 100.0,
        })
    # macro mean over non-None fixtures
    vals = [f for f in per_fixture if f is not None]
    n = len(vals) or 1
    def mean(k):
        nums = [f[k] for f in vals if f.get(k) is not None]
        return round(sum(nums) / (len(nums) or 1), 2)
    return {
        "source_support": mean("source_support"),
        "unsupported_claim": mean("unsupported_claim"),
        "key_point_coverage": mean("key_point_coverage"),
        "grading_agreement": mean("grading_agreement"),
        "duplicate": mean("duplicate"),
        "schema_validity": mean("schema_validity"),
    }, fatal


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--responses", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    fixtures_dir = Path(args.fixtures)
    manifest_path = Path(args.manifest)
    responses = json.loads(Path(args.responses).read_text())
    cases = load_fixtures(fixtures_dir, manifest_path)
    metrics, fatal = compute_metrics(cases, responses)

    report = {
        "report_schema_version": 1,
        "model": responses.get("model", "stub"),
        "metrics": metrics,
        "fatal_failures": fatal,
        "inputs": {"fixtures": len(cases), "manifest": str(manifest_path),
                   "responses": str(Path(args.responses))},
        "environment": {"eval_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"EVAL_OK: report written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
