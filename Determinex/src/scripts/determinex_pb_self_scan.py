#!/usr/bin/env python3
"""
determinex_pb_self_scan.py -- the corpus scans ITSELF for deficiencies
===================================================================
Aggregates every existing self-guard (no duplication -- it shells the canonical
checks) AND audits build_knowledge.json's factual CLAIMS against current ground
truth, so prose that drifts from reality (the "0 tarballs install tmux" /
"172 tools" / "UNDEPLOYED" class) is surfaced and fixed, not trusted.

Sections:
  A. GUARDS    -- run the canonical --guard / check-integrity entrypoints.
  B. CLAIMS    -- verify specific factual claims in build_knowledge against data.
  C. COUNTS    -- lock-count consistency across registry / eval_index / prose.
  D. MISLABEL  -- ceiling rows without a cert; provenance-dead reimpls in scope.

Usage: python scripts/determinex_pb_self_scan.py
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PB = ROOT / "corpus" / "programbench"
OV = PB / "per_tool_overrides"


def _short(s: str) -> str:
    s = s.split("__", 1)[1] if "__" in s else s
    return s.split(".")[0].replace("_native", "").replace("_model", "").lower()


def _run(cmd: list[str]) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            [sys.executable, *cmd], cwd=ROOT, capture_output=True, text=True, timeout=180
        )
        ok = r.returncode == 0
        tail = (r.stdout or r.stderr or "").strip().splitlines()
        return ok, " | ".join(tail[-2:]) if tail else ""
    except Exception as e:
        return False, f"ERR {e}"


def section_guards() -> list[tuple[str, bool, str]]:
    checks = [
        ("lock-registry integrity", ["scripts/determinex_pb_lock_registry.py", "check-integrity"]),
        ("tier reconcile guard", ["scripts/pb_tier_classify.py", "--guard"]),
        ("override scan guard", ["scripts/pb_override_scan.py", "--guard"]),
        ("provenance/anti-gaming guard", ["scripts/determinex_pb_provenance_guard.py", "--guard"]),
        ("doc/count check", ["scripts/pb_doc_count_check.py"]),
    ]
    return [(name, *_run(cmd)) for name, cmd in checks]


def section_claims() -> list[tuple[str, bool, str]]:
    """Verify build_knowledge factual claims against current data."""
    kb = json.loads((PB / "build_knowledge.json").read_text(encoding="utf-8"))
    out: list[tuple[str, bool, str]] = []

    # CLAIM: "0 tarballs install tmux" / "172 tools have tmux/pty not_run" (tui_collection)
    installs = sum(
        1
        for d in OV.iterdir()
        if (d / "compile.sh").exists()
        and re.search(
            r"apt.*install.*tmux|install.*-y.*tmux",
            (d / "compile.sh").read_text(encoding="utf-8", errors="replace"),
        )
    )
    partial = sum(
        1
        for d in OV.iterdir()
        if (d / "compile.sh").exists()
        and '"test_tmux*.py","test_pty*.py","test_curses*.py"'
        in (d / "compile.sh").read_text(encoding="utf-8", errors="replace")
    )
    tui_status = kb.get("class_patterns", {}).get("tui_collection", {}).get("status", "")
    claim_zero = "0 tarballs install tmux" in (
        kb.get("class_patterns", {}).get("tui_collection", {}).get("fix", "") + tui_status
    )
    out.append(
        (
            "build_knowledge 'tui_collection UNDEPLOYED / 0 install tmux'",
            not (claim_zero and installs > 0),
            f"reality: {installs} overrides install tmux, {partial} still test_tmux-filtered; "
            f"claim says '{tui_status[:40]}' -> STALE if installs>0 & partial==0",
        )
    )

    # CLAIM: mass_jump_targets scan date freshness
    sd = kb.get("mass_jump_targets", {}).get("_scan_date", "")
    out.append(
        (
            f"mass_jump_targets scan date ({sd})",
            True,
            f"scanned {sd}; re-scan if locks/builds changed since",
        )
    )
    return out


def section_counts() -> list[tuple[str, bool, str]]:
    out = []
    vl = json.loads((PB / "verified_locks.json").read_text(encoding="utf-8"))["locks"]
    vl_perfect = {
        _short(k)
        for k, v in vl.items()
        if isinstance(v, dict) and v.get("passed") == v.get("total")
    }
    rows = json.loads((PB / "eval_index.json").read_text(encoding="utf-8"))
    rows = rows if isinstance(rows, list) else list(rows.values())
    rows = [
        r
        for r in rows
        if isinstance(r, dict) and not r.get("alias_of") and not r.get("canonical_slug")
    ]
    sl = {_short(r["slug"]) for r in rows if r.get("status") == "strict_lock"}
    out.append(
        (
            "lock count: verified_locks(perfect) vs eval_index(strict_lock)",
            vl_perfect == sl,
            f"registry={len(vl_perfect)} index={len(sl)} "
            f"{'MATCH' if vl_perfect == sl else 'DRIFT: ' + str(sorted(vl_perfect ^ sl)[:6])}",
        )
    )
    # CLAUDE.md prose number
    try:
        cm = ROOT / "Determinex" / "CLAUDE.md"
        cm = cm if cm.exists() else (ROOT / "CLAUDE.md")
        txt = cm.read_text(encoding="utf-8", errors="replace") if cm.exists() else ""
        m = re.search(r"(\d+)\s*confirmed full-suite locks", txt)
        prose = int(m.group(1)) if m else None
        out.append(
            (
                "CLAUDE.md prose lock count vs registry",
                prose == len(vl_perfect) if prose else True,
                f"prose={prose} registry={len(vl_perfect)}",
            )
        )
    except Exception:
        pass
    return out


def section_mislabel() -> list[tuple[str, bool, str]]:
    out = []
    rows = json.loads((PB / "eval_index.json").read_text(encoding="utf-8"))
    rows = rows if isinstance(rows, list) else list(rows.values())

    def has_cert(r):
        for c in (r.get("slug", ""), r.get("source", "")):
            if c and (PB / "locked" / c / "CEILING_CERT.md").exists():
                return True
        rp = r.get("eval_report_path") or ""
        return bool(rp and (pathlib.Path(rp).parent / "CEILING_CERT.md").exists())

    nocert = [
        r["slug"]
        for r in rows
        if isinstance(r, dict) and r.get("tier") == "ceiling_certified" and not has_cert(r)
    ]
    out.append(
        (
            "ceiling_certified rows WITHOUT a CEILING_CERT.md",
            len(nocert) == 0,
            f"{len(nocert)} uncertified: {nocert[:6]}",
        )
    )
    return out


def section_consistency() -> list[tuple[str, bool, str]]:
    """DEEPER: cross-field consistency the surface guards miss."""
    out = []
    rows = json.loads((PB / "eval_index.json").read_text(encoding="utf-8"))
    rows = rows if isinstance(rows, list) else list(rows.values())
    rows = [
        r
        for r in rows
        if isinstance(r, dict) and not r.get("alias_of") and not r.get("canonical_slug")
    ]
    # tier vs status disagreement (tuc was tier=ceiling_certified, status=open)
    bad = [
        r["slug"]
        for r in rows
        if r.get("tier") == "strict_lock" and r.get("status") != "strict_lock"
    ]
    bad += [
        r["slug"]
        for r in rows
        if r.get("status") == "strict_lock" and r.get("tier") != "strict_lock"
    ]
    out.append(
        ("tier vs status agreement on locks", len(bad) == 0, f"{len(bad)} disagree: {bad[:6]}")
    )
    # autodrive verdicted LOCKED but NOT in verified_locks (un-promoted / gate-rejected)
    try:
        ad = json.loads((PB / "autodrive_results.json").read_text(encoding="utf-8"))
        adlock = {
            _short(k)
            for k, v in ad.get("runs", {}).items()
            if isinstance(v, dict) and v.get("verdict") == "LOCKED"
        }
        vl = {
            _short(k)
            for k in json.loads((PB / "verified_locks.json").read_text(encoding="utf-8"))["locks"]
        }
        orphan = adlock - vl
        out.append(
            (
                "autodrive LOCKED verdicts all in registry",
                len(orphan) == 0,
                f"{len(orphan)} locked-but-unregistered: {sorted(orphan)[:6]}",
            )
        )
    except Exception:
        pass
    return out


def section_registry() -> list[tuple[str, bool, str]]:
    """DEEPER: registry archive integrity + reimpls that must never be locks."""
    out = []
    vl = json.loads((PB / "verified_locks.json").read_text(encoding="utf-8"))["locks"]
    noarch = [
        k
        for k, v in vl.items()
        if isinstance(v, dict) and not (PB / "locked" / k / "submission.tar.gz").exists()
    ]
    out.append(
        (
            "every verified_lock has a local sha-pinned archive",
            len(noarch) == 0,
            f"{len(noarch)} missing-archive (unverifiable): {noarch[:8]}",
        )
    )
    # provenance-dead reimpls must not appear as a lock
    kb = json.loads((PB / "build_knowledge.json").read_text(encoding="utf-8"))
    reimpl = {
        re.split(r"[(]", t)[0].strip().lower()
        for t in kb.get("provenance_dead_reimpls", {}).get("tools", [])
    }
    locked_reimpl = [k for k in vl if _short(k) in reimpl]
    out.append(
        (
            "no provenance-dead reimpl is a verified lock",
            len(locked_reimpl) == 0,
            f"{locked_reimpl}",
        )
    )
    return out


def section_drift() -> list[tuple[str, bool, str]]:
    """DEEPER: module-pattern drift (the NEW_IGNORE class) + source-gap detection."""
    out = []
    # pb_tui_unlock_batch NEW_IGNORE must match keifu's proven pattern (test_tmux RUNS)
    tui = (ROOT / "scripts" / "pb_tui_unlock_batch.py").read_text(encoding="utf-8")
    keifu_aligned = (
        "NEW_IGNORE   = 'collect_ignore_glob = "
        '["test_pty*.py","test_pexpect*.py","test_curses*.py"]\''
    ) in tui
    out.append(
        (
            "pb_tui_unlock_batch NEW_IGNORE == keifu (test_tmux runs)",
            keifu_aligned,
            "aligned" if keifu_aligned else "DRIFT: still filters test_tmux -> undeployed",
        )
    )
    # canonical bidir plugin must carry the mirror hook
    bidir = (ROOT / "scripts" / "determinex_pb_bidir_restore.py").read_text(encoding="utf-8")
    out.append(
        (
            "bidir module carries _cb_mirror + strip",
            "_cb_mirror" in bidir and "def strip_bidir" in bidir,
            "present" if "_cb_mirror" in bidir else "MISSING",
        )
    )
    # source-gap: non-locked override dirs missing a build manifest
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import determinex_pb_autofix as AF

        gaps = []
        for d in OV.iterdir():
            if not (d / "compile.sh").exists():
                continue
            miss = AF._detect_missing_source(d)
            if miss:
                gaps.append(f"{d.name}:{miss[:2]}")
        out.append(
            (
                "no override dir has a detectable source-gap",
                len(gaps) == 0,
                f"{len(gaps)} gaps: {gaps[:5]}",
            )
        )
    except Exception as e:
        out.append(("source-gap scan", False, f"scan err {e}"))
    return out


def main() -> int:
    print("=" * 70)
    print("CORPUS SELF-SCAN — deficiencies surfaced for fixing")
    print("=" * 70)
    deficiencies = 0
    for title, fn in [
        ("A. GUARDS", section_guards),
        ("B. CLAIMS", section_claims),
        ("C. COUNTS", section_counts),
        ("D. MISLABEL", section_mislabel),
        ("E. CONSISTENCY (deep)", section_consistency),
        ("F. REGISTRY (deep)", section_registry),
        ("G. MODULE DRIFT (deep)", section_drift),
    ]:
        print(f"\n## {title}")
        for name, ok, detail in fn():
            flag = "OK  " if ok else "DEFICIENT"
            if not ok:
                deficiencies += 1
            print(f"  [{flag}] {name}")
            if detail:
                print(f"            {detail}")
    print(f"\n{'=' * 70}\nTOTAL DEFICIENCIES: {deficiencies}")
    return 1 if deficiencies else 0


if __name__ == "__main__":
    raise SystemExit(main())
