#!/usr/bin/env python3
"""
determinex_pb_certify_ceiling.py -- the CORPUS certifies its own ceilings
======================================================================
A "ceiling" claim (a tool that cannot reach 100%) must be PROVEN by the system, not
asserted by a human or a model. This routes every ceiling-labeled tool's eval data
through the Impossibility Adjudicator (determinex_adjudicator.adjudicate_eval_report) and:

  * CERTIFY  -- iff EVERY non-passing unit adjudicates IMPOSSIBLE (upstream-skip or
                identical-context-conflict). Writes locked/<slug>/CEILING_CERT.md from
                the adjudicator's PROOF (the strategies + the actual failing tests +
                expected/actual + score). This is the corpus generating + certifying.
  * DEMOTE   -- iff ANY non-passing unit is reopenable (UNBLOCK/MATCH/ROUTE/NEEDS_WORK).
                It is NOT a ceiling -- it is fixable work mislabeled as a ceiling. Emits
                the reopenable partition so autodrive picks it up.

No prose is invented: the cert is rendered from Adjudication objects. A tool is certified
ONLY when the adjudicator finds zero reopenable units. (build_knowledge legit_ceiling +
the Legitimate-Ceiling Standard: a ceiling is real ONLY if upstream skips unprovisionably
OR a proven logical contradiction.)

Usage:
  python scripts/determinex_pb_certify_ceiling.py --all-ceilings [--apply] [--update-index]
  python scripts/determinex_pb_certify_ceiling.py --slug <full_slug> [--apply]
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import tarfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
LOCKED = ROOT / "corpus" / "programbench" / "locked"
INDEX = ROOT / "corpus" / "programbench" / "eval_index.json"

import determinex_pb_autofix as AF  # noqa: E402
from determinex_adjudicator import (  # noqa: E402
    Verdict,
    _base_nodeid,
    adjudicate_eval_report,
)


def _resolve_inputs(slug: str) -> tuple[Path | None, str, str, str]:
    """(eval_report_path, conftest_text, compile_sh_text, archive_dir) for a tool."""
    full = AF._resolve_full_slug(slug) or slug
    report = AF._find_eval_report(full, None)
    conftest = compile_sh = ""
    archive = LOCKED / full
    # pull compile.sh (carries the conftest heredoc) from the locked tarball or override
    for tarp in (
        archive / "submission.tar.gz",
        ROOT / "corpus/programbench/per_tool_overrides" / full / "submission.tar.gz",
    ):
        if tarp.exists():
            try:
                with tarfile.open(tarp, "r:gz") as t:
                    for m in t.getmembers():
                        if m.name.endswith("compile.sh"):
                            compile_sh = t.extractfile(m).read().decode("utf-8", "replace")
                            conftest = compile_sh  # heredoc'd conftest lives inside compile.sh
                            break
            except Exception:
                pass
            break
    return report, conftest, compile_sh, str(archive)


def _partition(adjs):
    """Collapse bidir twins to unique units; return (unique_by_verdict, impossible, reopen)."""
    seen: dict[str, object] = {}
    for a in adjs:
        b = _base_nodeid(a.failure.test_id)
        seen.setdefault(b, a)
    uniq = list(seen.values())
    by_v: dict[Verdict, list] = defaultdict(list)
    for a in uniq:
        by_v[a.verdict].append(a)
    impossible = len(by_v.get(Verdict.IMPOSSIBLE, []))
    reopen = len(uniq) - impossible
    return by_v, impossible, reopen


def _render_cert(slug: str, report: Path, by_v, impossible: int) -> str:
    data = json.loads(report.read_text(encoding="utf-8"))
    tr = data.get("test_results", [])
    c = Counter(r.get("status") for r in tr)
    total = len(tr)
    passed = c.get("passed", 0)
    stamp = datetime.date.today().isoformat()
    imp = by_v.get(Verdict.IMPOSSIBLE, [])
    strat = Counter(a.strategy for a in imp)
    lines = [
        f"# CEILING CERTIFICATE — {slug}",
        "",
        f"> **Certified by** `determinex_pb_certify_ceiling.py` (Impossibility Adjudicator) on {stamp}.",
        "> Generated from eval data — not asserted. A ceiling is certified ONLY when EVERY",
        "> non-passing unit adjudicates IMPOSSIBLE (upstream-skip or identical-context-conflict).",
        "",
        f"**Score:** {passed}/{total} passed "
        f"({100 * passed / total:.2f}% — fail={c.get('failure', 0) + c.get('failed', 0) + c.get('error', 0)}, "
        f"not_run={c.get('not_run', 0)}, skipped={c.get('skipped', 0)}).",
        f"**Gap to 100%:** {impossible} unique non-passing unit(s), ALL proven IMPOSSIBLE. "
        "0 reopenable.",
        "",
        "## Why 100% is unreachable (the proof)",
        "",
    ]
    for s, n in strat.most_common():
        ex = next(a for a in imp if a.strategy == s)
        lines.append(f"### {s} — {n} unit(s)")
        lines.append(f"{ex.remediation}")
        lines.append("")
        samples = [a for a in imp if a.strategy == s][:5]
        lines.append("Representative units:")
        for a in samples:
            f = a.failure
            ln = f"- `{f.name[:90]}`"
            if f.expected and f.actual:
                ln += f" — expected `{f.expected[:40]}` vs actual `{f.actual[:40]}`"
            lines.append(ln)
        lines.append("")
    lines.append("## Verdict")
    lines.append(
        f"**LOCKED AT CEILING** at {passed}/{total}. The remaining {impossible} unit(s) "
        "cannot be satisfied by any single from-source binary without editing the "
        "benchmark fixtures. This is the maximum attainable score."
    )
    lines.append("")
    return "\n".join(lines)


def certify_one(slug: str, apply: bool) -> dict:
    report, conftest, compile_sh, archive = _resolve_inputs(slug)
    if not report or not report.exists():
        return {"slug": slug, "result": "no-eval-report"}
    adjs = adjudicate_eval_report(report, conftest, compile_sh)
    by_v, impossible, reopen = _partition(adjs)
    res = {"slug": slug, "impossible": impossible, "reopen": reopen, "report": str(report)}
    # PROOF REQUIRED, not just a count (2026-07-30). This certified on `impossible > 0 and
    # reopen == 0` alone and then wrote a CEILING_CERT.md asserting "ALL proven IMPOSSIBLE" and
    # "This is the maximum attainable score" into the locked archive -- and with --update-index
    # --apply it set eval_index status to ceiling_certified, which is what the public catalog is
    # generated from.
    #
    # Two facts make a bare count insufficient. First, the only IMPOSSIBLE verdict that is actually
    # reachable comes from a regex over pytest skip messages ("Too slow", "requires network", ...),
    # not from a proof: the identical-context-conflict branch in determinex_adjudicator.py is dead
    # code, because it builds `distinct` by excluding peers whose test_id equals f.test_id and then
    # requires exactly that equality for `same_ctx`. Second, an upstream skip is a provisioning
    # decision, not a demonstration that no binary can satisfy the requirement.
    #
    # So certification now requires every IMPOSSIBLE unit to carry a non-empty proof string. Today
    # that means nothing self-certifies, which is the correct outcome while the proof branch is
    # unreachable -- a certifier that cannot obtain proof must not issue certificates.
    impossible_adjs = by_v.get(Verdict.IMPOSSIBLE, [])
    # `remediation` is the field the adjudicator puts its explanation in -- Adjudication has
    # (failure, verdict, strategy, remediation, confidence) and the "PROOF: ..." text is passed
    # positionally as remediation. Reading a non-existent `rationale` here would have defaulted to
    # "" and marked every unit unproven: conservative by accident, and wrong as documentation.
    unproven = [
        a
        for a in impossible_adjs
        if not str(getattr(a, "remediation", "") or "").strip().startswith("PROOF:")
    ]
    if impossible > 0 and reopen == 0 and unproven:
        res["result"] = "DEMOTE_UNPROVEN"
        res["unproven_impossible"] = len(unproven)
        res["reason"] = (
            f"{len(unproven)} of {len(impossible_adjs)} IMPOSSIBLE unit(s) carry no PROOF: "
            f"rationale. A ceiling certificate asserts 'ALL proven IMPOSSIBLE' and must not be "
            f"issued on an upstream-skip classification alone."
        )
        return res
    if impossible > 0 and reopen == 0:
        res["result"] = "CERTIFIED"
        cert = _render_cert(slug, report, by_v, impossible)
        res["cert_path"] = str(Path(archive) / "CEILING_CERT.md")
        if apply:
            Path(archive).mkdir(parents=True, exist_ok=True)
            (Path(archive) / "CEILING_CERT.md").write_text(cert, encoding="utf-8")
    else:
        res["result"] = "DEMOTE"  # reopenable units exist -> NOT a ceiling
        res["reopenable_strategies"] = dict(
            Counter(
                a.strategy
                for v in (Verdict.UNBLOCK, Verdict.MATCH, Verdict.ROUTE, Verdict.NEEDS_WORK)
                for a in by_v.get(v, [])
            )
        )
    return res


def _ceiling_slugs() -> list[str]:
    rows = json.loads(INDEX.read_text(encoding="utf-8"))
    rows = rows if isinstance(rows, list) else list(rows.values())
    out = []
    for r in rows:
        if (
            isinstance(r, dict)
            and r.get("status") in ("ceiling_confirmed", "ceiling_certified")
            and not r.get("alias_of")
            and not r.get("canonical_slug")
        ):
            out.append(r.get("slug"))
    return [s for s in out if s]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--slug", help="certify one full slug")
    ap.add_argument(
        "--all-ceilings",
        action="store_true",
        help="run over every ceiling_confirmed/ceiling_certified row",
    )
    ap.add_argument("--apply", action="store_true", help="write CEILING_CERT.md files")
    ap.add_argument(
        "--update-index",
        action="store_true",
        help="set status: CERTIFIED->ceiling_certified, DEMOTE->open (with --apply)",
    )
    args = ap.parse_args()

    slugs = [args.slug] if args.slug else (_ceiling_slugs() if args.all_ceilings else [])
    if not slugs:
        ap.error("specify --slug or --all-ceilings")
        return 2

    results = [certify_one(s, args.apply) for s in slugs]
    cert = [r for r in results if r["result"] == "CERTIFIED"]
    demote = [r for r in results if r["result"] == "DEMOTE"]
    other = [r for r in results if r["result"] not in ("CERTIFIED", "DEMOTE")]

    print(f"\n=== CEILING CERTIFICATION ({len(results)} tools) ===")
    print(f"\nCERTIFIED ({len(cert)}) — all non-passing units proven IMPOSSIBLE:")
    for r in cert:
        print(
            f"  {r['slug']:42s} {r['impossible']} ceiling unit(s){'  [cert written]' if args.apply else ''}"
        )
    print(f"\nDEMOTE ({len(demote)}) — reopenable work, NOT a ceiling:")
    for r in demote:
        print(
            f"  {r['slug']:42s} reopen={r['reopen']} impossible={r['impossible']}  {r.get('reopenable_strategies', {})}"
        )
    if other:
        print(f"\nUNRESOLVED ({len(other)}):")
        for r in other:
            print(f"  {r['slug']:42s} {r['result']}")

    if args.update_index and args.apply:
        rows = json.loads(INDEX.read_text(encoding="utf-8"))
        is_list = isinstance(rows, list)
        idx = rows if is_list else list(rows.values())
        cset = {r["slug"] for r in cert}
        dset = {r["slug"] for r in demote}
        n = 0
        for e in idx:
            if not isinstance(e, dict):
                continue
            sl = e.get("slug")
            if sl in cset and e.get("status") != "ceiling_certified":
                e["status"] = "ceiling_certified"
                n += 1
            elif sl in dset and e.get("status") in ("ceiling_confirmed", "ceiling_certified"):
                e["status"] = "open"
                e["demoted_from_ceiling"] = True
                n += 1
        INDEX.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nupdated eval_index status on {n} row(s).")

    print(
        f"\nSUMMARY: {len(cert)} certified, {len(demote)} demoted (mislabeled), {len(other)} unresolved."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
