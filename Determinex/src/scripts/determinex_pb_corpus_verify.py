#!/usr/bin/env python3
"""determinex_pb_corpus_verify.py -- close the build->corpus loop.

After something is BUILT (a reimpl fix / cap removal / env match) and EVAL'd, this step VERIFIES
the outcome against the corpus and does three things the operator asked for:

  * POINTS OUT  -- what the corpus already knew (did we rediscover a known fix = wasted time?),
                   and whether the actual outcome CONFIRMS or CONTRADICTS the corpus prescription.
  * CORRECTS    -- if a corpus prescription was followed and the score REGRESSED, record a
                   counter-finding so the corpus stops prescribing it for that context.
  * INSERTS MISSING -- if the change is novel (the corpus only had the high-level class, or
                   nothing), insert the CONCRETE fix under per_tool[slug] (+ an optional reusable
                   class pattern), so the next run gets the specific fix, not a vague class.

No duplication: it READS via determinex_pb_ask_corpus.ask_corpus and WRITES the same
build_knowledge.json that ask_corpus reads. Deterministic; never an LLM judgement.

CLI:
  python determinex_pb_corpus_verify.py <slug> --before P/TOT --after P/TOT \
      --change "stty raw -> cbreak (-echo -icanon) on os.Stdin: keys reach the tty" \
      [--class tty_render_reimpl_rawmode] [--generalizes-to "go,rust tui reimpls"]
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PB = ROOT / "corpus" / "programbench"
KB_PATH = PB / "build_knowledge.json"
sys.path.insert(0, str(ROOT / "scripts"))


def _parse_frac(x: str) -> tuple[int, int]:
    m = re.match(r"\s*(\d+)\s*/\s*(\d+)\s*", x)
    if not m:
        raise SystemExit(f"bad P/TOT: {x!r}")
    return int(m.group(1)), int(m.group(2))


def _prescription(slug: str) -> dict:
    """Read the corpus's current view of this tool (class + per_tool + prescription terms)."""
    try:
        from determinex_pb_ask_corpus import ask_corpus

        return ask_corpus(slug)
    except Exception as e:  # corpus read must never crash the verify step
        return {"slug": slug, "per_tool": None, "prescription": [], "_read_error": str(e)}


def verify(
    slug: str,
    before: str,
    after: str,
    change: str | None,
    klass: str | None,
    generalizes_to: str | None,
) -> dict:
    kb = json.loads(KB_PATH.read_text(encoding="utf-8"))
    bp, bt = _parse_frac(before)
    ap, at = _parse_frac(after)
    delta = ap - bp
    direction = "IMPROVED" if delta > 0 else ("REGRESSED" if delta < 0 else "UNCHANGED")

    presc = _prescription(slug)
    presc_terms = [str(p).lower() for p in presc.get("prescription", [])]
    had_per_tool = bool(presc.get("per_tool"))
    # Did the corpus already encode the SPECIFIC change (not just the class)?
    change_l = (change or "").lower()
    known_specific = bool(change_l) and any(
        tok in json.dumps(presc.get("per_tool") or {}).lower()
        for tok in change_l.split()
        if len(tok) > 4
    )

    report = {
        "slug": slug,
        "before": f"{bp}/{bt}",
        "after": f"{ap}/{at}",
        "delta": delta,
        "direction": direction,
        "points_out": [],
        "corrected": [],
        "inserted": [],
    }

    # --- POINTS OUT ----------------------------------------------------------
    if presc_terms:
        report["points_out"].append(f"corpus prescription was: {presc.get('prescription')[:4]}")
    else:
        report["points_out"].append("corpus had NO prescription for this tool")
    if known_specific:
        report["points_out"].append(
            "corpus ALREADY had this specific fix in per_tool -> rediscovered (avoidable next time)"
        )
    elif had_per_tool:
        report["points_out"].append(
            "corpus had a per_tool note but not THIS specific fix -> partial knowledge"
        )
    else:
        report["points_out"].append(
            "corpus had only class-level signal (or none) -> this fix is NEW knowledge"
        )

    now = datetime.date.today().isoformat()
    log = kb.setdefault("verification_log", [])

    # --- CORRECT (regression after following a prescription) -----------------
    if direction == "REGRESSED" and presc_terms:
        key = f"correction_{slug.split('.')[0].replace('__', '_')}_{now.replace('-', '_')}"
        kb[key] = {
            "type": "CORRECTION",
            "tool": slug,
            "followed_prescription": presc.get("prescription")[:4],
            "result": f"REGRESSED {bp}->{ap} (/{bt})",
            "change_that_regressed": change,
            "rule": "Do NOT prescribe the above for this context; it lowered the score.",
            "recorded": now,
        }
        report["corrected"].append(key)

    # --- INSERT MISSING (novel concrete fix on improvement/unchanged) --------
    if change and (direction == "IMPROVED" or not known_specific):
        per = kb.setdefault("per_tool", {})
        entry = per.get(slug)
        note = f"VERIFIED-FIX ({now}): {change} | {bp}/{bt} -> {ap}/{at} ({direction})"
        if isinstance(entry, dict):
            prior = entry.get("note", "")
            entry["note"] = (prior + " || " + note) if prior else note
            entry["verified_fix"] = change
            entry["verified_delta"] = f"{bp}->{ap}"
        else:
            per[slug] = {"note": note, "verified_fix": change, "verified_delta": f"{bp}->{ap}"}
        report["inserted"].append(f"per_tool[{slug}]")

        if klass:  # reusable class pattern so SIBLING tools benefit
            ck = f"class_{klass}"
            kb.setdefault(ck, {})
            kb[ck].update(
                {
                    "pattern": change,
                    "first_proven_on": slug,
                    "delta": f"{bp}->{ap}",
                    "generalizes_to": generalizes_to or "",
                    "recorded": now,
                }
            )
            report["inserted"].append(ck)

    log.append(
        {
            "slug": slug,
            "delta": delta,
            "direction": direction,
            "change": change,
            "known_specific": known_specific,
            "at": now,
        }
    )
    kb["_updated"] = datetime.datetime.now().isoformat(timespec="seconds")
    # atomic write: concurrent evals (campaign + manual) must never corrupt build_knowledge.json
    fd, tmp = tempfile.mkstemp(dir=str(KB_PATH.parent), suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(kb, fh, indent=2)
        os.replace(tmp, KB_PATH)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--before", required=True, help="P/TOT before the change")
    ap.add_argument("--after", required=True, help="P/TOT after the change")
    ap.add_argument("--change", help="concrete description of what was built/fixed")
    ap.add_argument("--class", dest="klass", help="reusable class key to record (siblings benefit)")
    ap.add_argument("--generalizes-to", dest="gen", help="which tools/langs this class applies to")
    a = ap.parse_args()
    r = verify(a.slug, a.before, a.after, a.change, a.klass, a.gen)
    print(f"=== corpus-verify: {r['slug']}  {r['before']} -> {r['after']}  [{r['direction']}] ===")
    for p in r["points_out"]:
        print("  POINT-OUT :", p)
    for c in r["corrected"]:
        print("  CORRECTED :", c)
    for i in r["inserted"]:
        print("  INSERTED  :", i)
    if not r["corrected"] and not r["inserted"]:
        print("  (nothing to correct/insert -- corpus already aligned)")


if __name__ == "__main__":
    main()
