#!/usr/bin/env python3
"""determinex_pb_build_cycle.py -- bracket every build segment with corpus shots, loop until done.

The operator's model: a build segment is [START shot] -> build/fix -> [END shot]. The two shots
"clear up the missed problems of continuous build" -- run the cycle as many times as needed.

  START shot  (cmd: start) -- determinex_pb_ask_corpus.ask_corpus(slug): what the corpus knows
              (prescription + prior VERIFIED fixes inserted by earlier END shots). Snapshots the
              current eval score as the cycle's BEFORE.
  -- you (or the model) build/fix using that knowledge, then re-eval --
  END shot    (cmd: end --change "...") -- determinex_pb_corpus_verify.verify(): reads the new score
              as AFTER, then POINTS OUT / CORRECTS / INSERTS, and says DONE or LOOP-AGAIN.

The END shot's inserts land in build_knowledge.json, so the NEXT START shot is already smarter.
No duplication: START = ask_corpus (read), END = corpus_verify (write); both share
build_knowledge.json. State is one tiny json per slug under .cycle_state/.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PB = ROOT / "corpus" / "programbench"
OVR = PB / "per_tool_overrides"
STATE = PB / ".cycle_state"
sys.path.insert(0, str(ROOT / "scripts"))


def _latest_score(slug: str) -> tuple[int, int]:
    """Read the most recent eval.json for the tool -> (passed, total). (0,0) if none."""
    fs = glob.glob(str(OVR / slug / "*.eval.json"))
    if not fs:
        return (0, 0)
    d = json.loads(Path(max(fs, key=os.path.getmtime)).read_text(encoding="utf-8"))
    tr = d.get("test_results", [])
    c = collections.Counter(t.get("status") for t in tr)
    return (c.get("passed", 0), len(tr))


def cmd_start(slug: str) -> None:
    STATE.mkdir(exist_ok=True)
    from determinex_pb_ask_corpus import ask_corpus

    shot = ask_corpus(slug)
    p, tot = _latest_score(slug)
    (STATE / f"{slug}.json").write_text(json.dumps({"before": f"{p}/{tot}"}), encoding="utf-8")
    print(f"================ START SHOT: {slug} ================")
    print(f"BEFORE score: {p}/{tot}")
    pt = shot.get("per_tool")
    if pt:
        print("CORPUS per_tool (concrete, incl. prior VERIFIED fixes):")
        for k, v in pt.items():
            print("  ", json.dumps(v)[:400])
    print("CORPUS prescription (what to do, ordered):")
    for line in shot.get("prescription", [])[:8]:
        print("  -", line)
    print(
        "---> BUILD now using the above, re-eval, then run: build_cycle end "
        f'{slug} --change "<what you changed>" [--class <key>]'
    )


def cmd_end(slug: str, change: str | None, klass: str | None, gen: str | None) -> None:
    from determinex_pb_corpus_verify import verify

    st = STATE / f"{slug}.json"
    before = json.loads(st.read_text(encoding="utf-8"))["before"] if st.exists() else "0/0"
    p, tot = _latest_score(slug)
    after = f"{p}/{tot}"
    r = verify(slug, before, after, change, klass, gen)
    print(f"================ END SHOT: {slug}  {before} -> {after} [{r['direction']}] ===========")
    for x in r["points_out"]:
        print("  POINT-OUT :", x)
    for x in r["corrected"]:
        print("  CORRECTED :", x)
    for x in r["inserted"]:
        print("  INSERTED  :", x)
    # loop decision
    if tot and p == tot:
        print(f"==> DONE: {slug} at {after} (100%). Cycle complete.")
    else:
        miss = tot - p if tot else "?"
        print(
            f"==> LOOP-AGAIN: {miss} not-yet-passing. Run: build_cycle start {slug}  "
            "(next START shot now includes what this END shot inserted)."
        )


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("slug")
    e = sub.add_parser("end")
    e.add_argument("slug")
    e.add_argument("--change")
    e.add_argument("--class", dest="klass")
    e.add_argument("--generalizes-to", dest="gen")
    a = ap.parse_args()
    if a.cmd == "start":
        cmd_start(a.slug)
    else:
        cmd_end(a.slug, a.change, a.klass, a.gen)


if __name__ == "__main__":
    main()
