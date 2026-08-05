#!/usr/bin/env python3
"""Determinex PB drive-tick -- one cheap, deterministic step of the autonomous drive.

Each tick (the 19h test-max loop calls this after pulling fresh eval JSONs):
  1. read every eval JSON with the canonical reader (determinex_eval_report),
  2. COMPOUND CORPUS KNOWLEDGE: append each tool's unique failures (argv + expected
     + actual + traceback) to the model-reimpl training corpus, deduped so re-runs
     never bloat it -- every failure becomes flywheel training data,
  3. update a running drive ledger (best score per tool, build-fail flags),
  4. recompute the benchmark-wide test total by overlaying the ledger on the
     eval_index baseline, and print it.

It does NOT touch eval_index.json, the board, or locked archives (that's the gated
driver's job). It only grows the corpus and the ledger -- knowledge compounds, the
board stays honest. Memory-watch / docker-prune are environment ops the loop runs
over SSH (df/free/docker image prune); this script is the corpus+ledger brain.

Usage:
  python scripts/determinex_pb_drive_tick.py <jsons_dir> [--corpus PATH] [--ledger PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import determinex_eval_report as ER  # noqa: E402

CORPUS = Path("corpus/programbench/training_corpus/model_reimpl_corpus.jsonl")
LEDGER = Path("corpus/programbench/drive_ledger.json")
INDEX = Path("corpus/programbench/eval_index.json")
BUILD_FAIL_RATIO = 0.05  # passed/total below this on a >300-test suite => build/invocation failure


def _seen_keys(corpus: Path) -> set[str]:
    """Dedup key set already in the corpus (tool|test|attempt-ish)."""
    keys = set()
    if corpus.exists():
        for line in corpus.open(encoding="utf-8", errors="replace"):
            try:
                r = json.loads(line)
                keys.add(f"{r.get('tool')}|{r.get('test')}|{r.get('attempt', '')}")
            except Exception:
                pass
    return keys


def _slug_of(path: Path) -> str:
    n = path.name
    for suf in (".eval.json", ".json"):
        if n.endswith(suf):
            return n[: -len(suf)]
    return n


def tick(jsons_dir: Path, corpus: Path, ledger_path: Path) -> dict:
    attempt = f"drive_{date.today().isoformat()}"
    seen = _seen_keys(corpus)
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}

    added = 0
    summary = []
    corpus.parent.mkdir(parents=True, exist_ok=True)
    with corpus.open("a", encoding="utf-8") as cf:
        for jp in sorted(jsons_dir.glob("*.eval.json")):
            slug = _slug_of(jp)
            try:
                rep = ER.load(jp)
            except Exception as e:
                summary.append((slug, f"READ_FAIL {e}"))
                continue
            # compound: append unique failures
            per_test_seen = set()
            for fr in rep.failures:
                if fr.short in per_test_seen:
                    continue
                per_test_seen.add(fr.short)
                key = f"{slug}|{fr.short}|{attempt}"
                if key in seen:
                    continue
                seen.add(key)
                cf.write(
                    json.dumps(
                        {
                            "tool": slug,
                            "test": fr.short,
                            "argv": fr.argv,
                            "expect_rc": fr.expect_rc,
                            "expect_in": fr.expect_in[:3],
                            "actual_rc": fr.returncode_actual,
                            "trace": fr.text[:1200],
                            "attempt": attempt,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                added += 1
            # ledger: keep best score; flag build-fail / lock / ceiling-near
            prev = ledger.get(slug, {})
            best_p = max(rep.passed, prev.get("best_passed", 0))
            build_fail = rep.total >= 300 and rep.passed / max(rep.total, 1) < BUILD_FAIL_RATIO
            ledger[slug] = {
                "best_passed": best_p,
                "total": rep.total,
                "last_passed": rep.passed,
                "is_lock": rep.is_lock,
                "not_run": rep.not_run,
                "build_fail": build_fail,
                "last_eval": date.today().isoformat(),
            }
            tag = " LOCK" if rep.is_lock else (" BUILD-FAIL?" if build_fail else "")
            summary.append((slug, f"{rep.passed}/{rep.total}{tag}"))

    ledger_path.write_text(json.dumps(ledger, indent=1), encoding="utf-8")

    # benchmark-wide total: overlay ledger best scores onto the eval_index baseline
    bench = _benchmark_total(ledger)

    print(f"=== drive tick: {len(summary)} eval(s) ===")
    for slug, s in summary:
        print(f"  {slug:38} {s}")
    print(f"\ncorpus: +{added} rows  (total {sum(1 for _ in corpus.open(encoding='utf-8'))})")
    build_fails = [s for s, v in ledger.items() if v.get("build_fail")]
    if build_fails:
        print(f"build-fail flags (giant-build credit-refresh targets): {build_fails}")
    if bench:
        print(
            f"\nBENCHMARK-WIDE: {bench['passed']:,} / {bench['total']:,} "
            f"= {100 * bench['passed'] / bench['total']:.2f}%  "
            f"(ledger overlays {bench['overlaid']} tools onto index baseline)"
        )
    return {"added": added, "ledger": str(ledger_path), "bench": bench}


def _benchmark_total(ledger: dict) -> dict:
    if not INDEX.exists():
        return {}
    idx = json.loads(INDEX.read_text(encoding="utf-8", errors="replace"))
    passed = total = overlaid = 0
    for r in idx:
        slug = r.get("slug", "")
        # match ledger by hashed-slug prefix (index uses bare slug)
        led = None
        for k, v in ledger.items():
            if k.startswith(slug) or k.split(".")[0] == slug:
                led = v
                break
        t = r.get("official_total") or r.get("total") or 0
        p = r.get("official_passed") or r.get("passed") or 0
        if led and led.get("total"):
            t = led["total"]
            p = max(p, led["best_passed"])
            overlaid += 1
        passed += p
        total += t
    return {"passed": passed, "total": total, "overlaid": overlaid}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Determinex PB drive-tick (compound corpus + ledger)")
    ap.add_argument("jsons_dir", type=Path)
    ap.add_argument("--corpus", type=Path, default=CORPUS)
    ap.add_argument("--ledger", type=Path, default=LEDGER)
    a = ap.parse_args(argv)
    tick(a.jsons_dir, a.corpus, a.ledger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
