#!/usr/bin/env python3
"""
determinex_pb_autodrive.py -- the CLOSED-LOOP convert driver ("no hand loops")
===========================================================================
The belt (pb_parallel) only ever did `eval -> log score`: it re-confirmed near-locks
at 99% forever (0 deploys/cycle) and burned 35-min evals on whales that produce no
binary. The engine is sound; the LOOP was open. This closes it by composing the three
gates that already exist as components -- no new swarm, no per-tool hand loop:

  1. BUILD-PROBE / build-class FIX   determinex_pb_autofix.fix (go-toolchain / cc-deps /
       build-target / tarball-drift) -> pack_submission. Gate on the OUTCOME (did a
       binary appear / did rc127 disappear), never on "fix-text already present".
  2. REMOTE EVAL                     pb_eval_unified.run_hetzner_eval (scp -> programbench
       eval -> pull eval.json). One live eval at a time (no swarm -- the chaos lesson).
  3. AUTO-PROMOTE                    on a clean 100% (passed==total, 0 fail/nr/sk) the
       tarball+report are archived to locked/<slug>/ and determinex_pb_lock_registry.
       verify_and_register sha-pins it -- but only AFTER its own re-check of clean +
       provenance-guard (anti-test-gaming) + archive-present. Auto-pin is sound BY
       CONSTRUCTION: the gate is the credibility guarantee, the registry is git-tracked
       and reversible.

A tool that still build-fails after the build-class fix is logged needs-manual-build
(mega-whales gdal/duckdb/php need per-tool configure engineering -- see
build_knowledge.json whale_specific_builds) and the loop moves on; it never spins.

Usage:
  python scripts/determinex_pb_autodrive.py --queue build_fail_whales [--max-attempts 2]
  python scripts/determinex_pb_autodrive.py --slugs sqlite__sqlite.839433d,...
  python scripts/determinex_pb_autodrive.py --dry-run --slugs <slug>   # wiring check, no live eval
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import re
import shlex
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
LOCKED = ROOT / "corpus" / "programbench" / "locked"
OVERRIDES = ROOT / "corpus" / "programbench" / "per_tool_overrides"
LOG = ROOT / "corpus" / "programbench" / "autodrive_results.json"

# On the eval box, uv lives in /root/.local/bin, which a non-interactive ssh `nohup` launch does
# NOT pick up -- without it `uv run programbench eval` dies with FileNotFoundError and every tool
# logs a silent no-eval (total 0). Guarantee the eval subprocess can always find it. (box footgun)
for _p in ("/root/.local/bin", str(Path.home() / ".local" / "bin")):
    if os.path.isdir(_p) and _p not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = _p + os.pathsep + os.environ.get("PATH", "")

# Build-fail whales first (the operator decision 2026-06-22). Full author__repo.hash slugs.
# Ordered easiest-recipe-first (corpus build_knowledge: srgn=go-toolchain, sqlite=build-essential,
# ctags/cppcheck=cc-deps) so the cheap wins land before the mega-whales (gdal/duckdb/php).
BUILD_FAIL_WHALES = [
    "alexpovel__srgn.89f943b",  # go_x_toolchain (GOTOOLCHAIN=go1.24.1)
    "sqlite__sqlite.839433d",  # builds clean w/ build-essential; tarball-drift
    "universal-ctags__ctags.243595e",  # cc_build_deps
    "danmar__cppcheck.0a5b103",  # cc deps; behavioral tail
    "rust-ethereum__ethabi.b1710ad",  # rust workspace / source-gap
    "halitechallenge__halite.822cfb6",  # libtclap-dev + restrict build
    "samtools__samtools.aa823b5",  # htslib sibling dep
    "robertdavidgraham__masscan.b99d433",
    "arq5x__bedtools2.dd57059",
    "ffmpeg__ffmpeg.360a402",  # mega: codec -dev libs
    "osgeo__proj.75d455c",  # mega: cmake generated headers
    "php__php-src.c891263",  # mega
    "osgeo__gdal.0847f12",  # mega
    "duckdb__duckdb.bdb65ec",  # mega: build timeout
]


EVAL_INDEX = ROOT / "corpus" / "programbench" / "eval_index.json"
VERIFIED = ROOT / "corpus" / "programbench" / "verified_locks.json"
# Terminal verdicts: don't re-drive these every pass (locked, or stuck pending human work).
_TERMINAL = {
    "LOCKED",
    "needs-manual-build",
    "behavioral",
    "no-override-dir",
    "clean-but-pin-rejected",
    "reimpl-lock-candidate",
    "needs-local-oracle-tail",
    "needs-local-oracle",
    "oracle-red-needs-tail",
    "needs-spec-extraction",
    "needs-native-reimpl",
}


def _short(slug: str) -> str:
    s = slug.split("__", 1)[1] if "__" in slug else slug
    return s.split(".")[0].replace("_native", "").replace("_model", "").lower()


def _canonical_slug(slug: str) -> str:
    """Resolve short aliases to the unique full override slug when possible."""
    try:
        import determinex_pb_autofix as AF

        return AF._resolve_full_slug(slug) or slug
    except Exception:
        return slug


def _is_terminal_verdict(verdict: object) -> bool:
    if not isinstance(verdict, str):
        return False
    return verdict in _TERMINAL or any(verdict.startswith(f"{t}:") for t in _TERMINAL)


def _corpus_consult(slug: str) -> dict:
    try:
        import determinex_pb_ask_corpus as AC

        ans = AC.ask_corpus(slug)
        return {
            "engine": ans.get("recommended_engine", ""),
            "source_shape": ans.get("source_shape", {}),
            "spec": ans.get("spec"),
            "reimpl_skill": ans.get("reimpl_skill"),
            "prescription": (ans.get("prescription") or [])[:8],
        }
    except Exception as e:
        return {"error": str(e)}


def _build_full_queue() -> list[str]:
    """The full-200 drive queue: every per_tool_overrides tool that is NOT already locked,
    NOT a confirmed/certified ceiling, and NOT a provenance-dead reimpl. Ordered near-lock
    first (by eval_index official_score_pct desc) so the most-convertible land soonest."""
    import determinex_pb_autofix as AF

    # locked (by short name)
    locked = set()
    try:
        locked = {_short(k) for k in json.loads(VERIFIED.read_text(encoding="utf-8"))["locks"]}
    except Exception:
        pass
    # reimpls that can never lock (provenance) + confirmed ceilings (capped <100)
    kb = AF.load_knowledge() or {}
    reimpl = {
        re.split(r"[(]", t)[0].strip().lower()
        for t in kb.get("provenance_dead_reimpls", {}).get("tools", [])
    }
    # eval_index: status (to drop ceilings) + score (to order)
    score: dict[str, float] = {}
    ceiling: set[str] = set()
    try:
        rows = json.loads(EVAL_INDEX.read_text(encoding="utf-8"))
        rows = rows if isinstance(rows, list) else list(rows.values())
        for r in rows:
            if not isinstance(r, dict):
                continue
            sn = _short(r.get("slug", ""))
            if r.get("status") in ("ceiling_confirmed", "ceiling_certified"):
                ceiling.add(sn)
            sc = r.get("official_score_pct")
            if isinstance(sc, (int, float)):
                score[sn] = max(score.get(sn, 0.0), float(sc))
    except Exception:
        pass
    # Honor the proven_ceilings registry (the autodrive's triage certifies here) so a freshly
    # certified ceiling is DROPPED next pass -- no waiting for an eval_index reconcile.
    try:
        pc = json.loads(
            (ROOT / "corpus" / "programbench" / "proven_ceilings.json").read_text(encoding="utf-8")
        )
        for t in pc.get("ceilings", {}) if isinstance(pc, dict) else {}:
            ceiling.add(_short(t))
    except Exception:
        pass
    # CANON-AUDIT-demoted gamers (pass via answer-key binary / PYTEST_CURRENT_TEST routing):
    # the provenance guard would reject any lock anyway -- don't waste evals on them.
    gamers = {"yj", "svd2rust", "ripgrep", "sd"}
    # Dedup by short_name: one override dir per task, preferring the canonical
    # owner__repo.hash form over a bare short alias (so we drive/pin the canonical copy).
    by_short: dict[str, str] = {}
    for d in OVERRIDES.iterdir():
        if not (d.is_dir() and (d / "compile.sh").exists()):
            continue
        sn = _short(d.name)
        if sn in locked or sn in reimpl or sn in ceiling or sn in gamers:
            continue
        canonical = bool(re.search(r"__.+\.[0-9a-f]{7,8}$", d.name))
        cur = by_short.get(sn)
        if cur is None or (canonical and not re.search(r"__.+\.[0-9a-f]{7,8}$", cur)):
            by_short[sn] = d.name
    q = list(by_short.values())
    q.sort(key=lambda s: score.get(_short(s), 0.0), reverse=True)
    return q


def parse_counts(data: dict) -> dict:
    tr = data.get("test_results") if isinstance(data, dict) else None
    if not isinstance(tr, list):
        return {"total": 0, "passed": 0, "failed": 0, "not_run": 0, "skipped": 0, "rc127": 0}
    c = collections.Counter(r.get("status") for r in tr)
    rc127 = sum(1 for r in tr if "127" in str((r.get("extra") or {}).get("text", ""))[:160])
    return {
        "total": len(tr),
        "passed": c.get("passed", 0),
        "failed": c.get("failure", 0) + c.get("failed", 0) + c.get("error", 0),
        "not_run": c.get("not_run", 0),
        "skipped": c.get("skipped", 0),
        "rc127": rc127,
    }


def verdict_of(c: dict) -> str:
    t, p = c["total"], c["passed"]
    if t == 0:
        return "no-eval"
    if p == t and c["failed"] == 0 and c["not_run"] == 0 and c["skipped"] == 0:
        return "clean-lock"
    # rc127 == "no binary for this test" -> an UNAMBIGUOUS build failure, not behavior. A substantial
    # rc127 fraction means the build is (partially) broken, so route to the build-class autofix FIRST
    # (un-break the no-binary branches), not to the behavioral path (adjudicate/reimpl can't fix a
    # missing binary). 15% is safe: a near-lock (>=90% pass) has <=10% non-pass so it can never reach
    # it. The build path either un-breaks further or honestly lands `needs-manual-build` -- both beat
    # mislabeling a partial build as `behavioral` (e.g. gotests 378/1504 rc127 = 25%).
    if c["rc127"] >= max(1, int(0.15 * t)) or p < 0.05 * t:
        return "build-fail"
    if p >= 0.90 * t:
        return "near-lock"
    return "behavioral"


def _autofix(slug: str, apply: bool) -> dict:
    """Run the deterministic build-class autofix on the override dir. Returns its result."""
    import determinex_pb_autofix as AF

    full = AF._resolve_full_slug(slug) or slug
    report = AF._find_eval_report(full, None)
    res = AF.autofix(full, report, apply=apply)
    return {
        "changed": getattr(res, "changed", False),
        "applied": getattr(res, "applied", []),
        "skipped": getattr(res, "skipped", []),
        "eval_report": str(report) if report else None,
    }


def _repack(slug: str) -> Path:
    import determinex_pb_autofix as AF

    return AF.pack_submission(slug)


def _harvest_build_err(slug: str) -> str:
    """Fetch the ACTUAL build error from the compiled image (programbench-compiled/<slug>:determinex-cached)
    so the build fix is NEVER blind. Runs LOCALLY on the eval box (local docker); SSHes to Hetzner
    only when driving REMOTELY (Windows). The prior version ALWAYS SSH'd -- on the box that is an
    SSH-to-our-own-IP that fails, so the harvest came back empty and every build-fail stayed blind
    ('no build.err harvested'). If no *.err file was left behind, re-run compile.sh in the image to
    capture the build error directly (lua-class: compile.sh that doesn't redirect to a .err file)."""
    import subprocess

    img = f"programbench-compiled/{slug}:determinex-cached"
    find_inner = (
        f"docker run --rm --entrypoint sh {img} -lc "
        f'\'for f in $(find /workspace -maxdepth 3 -name "*.err" 2>/dev/null); do '
        f'echo "[$f]"; tail -40 "$f"; done\''
    )
    rerun_inner = (
        f"docker run --rm --entrypoint sh {img} -lc "
        f"'cd /workspace 2>/dev/null && [ -f compile.sh ] && sh ./compile.sh 2>&1 | tail -80'"
    )
    on_box = Path("/root/ProgramBench").is_dir()

    def _run(inner: str, timeout: int) -> str:
        try:
            if on_box:
                # shell=False + argv list. The shell was here only to append ` 2>/dev/null`,
                # which subprocess expresses directly. `inner` is always
                # `docker run ... sh -lc '<script>'`; shlex.split keeps the quoted script as a
                # single token, so the container's shell still sees its own &&/|/2>&1 -- but
                # the host shell no longer gets to interpret the string at all.
                r = subprocess.run(
                    shlex.split(inner),
                    shell=False,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    stderr=subprocess.DEVNULL,
                )
            else:
                from pb_eval_unified import HETZNER_IP, HETZNER_SSH_KEY

                r = subprocess.run(
                    [
                        "ssh",
                        "-i",
                        str(HETZNER_SSH_KEY),
                        "-o",
                        "StrictHostKeyChecking=no",
                        f"root@{HETZNER_IP}",
                        inner + " 2>/dev/null",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            return r.stdout or ""
        except Exception:
            return ""

    out = _run(find_inner, 120)
    if not out.strip():
        out = _run(rerun_inner, 300)  # robust fallback: re-run the build, capture stderr
    return out


def _build_err_fix(slug: str) -> dict:
    """The NEVER-BLIND build fix: harvest build.err, diagnose missing deps, inject the apt
    install into compile.sh. Returns {pkgs, sigs, applied}."""
    import determinex_pb_autofix as AF

    full = AF._resolve_full_slug(slug) or slug
    err = _harvest_build_err(full)
    if not err.strip():
        return {"pkgs": [], "sigs": [], "applied": False, "note": "no build.err harvested"}
    pkgs, sigs = AF.diagnose_build_err(err)
    if not pkgs:
        return {
            "pkgs": [],
            "sigs": sigs,
            "applied": False,
            "note": "no dep signature (per-tool build engineering)",
        }
    cs = OVERRIDES / full / "compile.sh"
    new, ch = AF.inject_apt_deps(cs.read_text(encoding="utf-8", errors="replace"), pkgs)
    if ch:
        cs.write_text(new, encoding="utf-8", newline="\n")
    return {"pkgs": pkgs, "sigs": sigs, "applied": ch}


def _source_gap_fetch(slug: str) -> dict:
    """Safety-net for a build-fail that survives a fresh repack: if the LOCAL override is
    genuinely missing referenced source (go subpkg / rust workspace member), fetch it from
    upstream @pinned commit. (Most 'source-gap' whales are actually tarball DRIFT — local
    complete, remote stale — already fixed by the repack; this fires only on a real gap.)"""
    import determinex_pb_autofix as AF

    full = AF._resolve_full_slug(slug) or slug
    tool_dir = OVERRIDES / full
    missing = AF._detect_missing_source(tool_dir)
    if not missing:
        return {"restored": [], "missing": [], "note": "local source complete (drift, not gap)"}
    restored, errs = AF.source_gap_upstream_fetch(full, tool_dir)
    return {"restored": restored, "missing": missing, "errs": errs}


def _triage(slug: str, reference_check: bool = False) -> dict:
    """The route brain: classify the tool's CURRENT failures (determinex_autofix.triage on the best
    eval_report) into winnable / proven-ceiling / slop, so the drive can ROUTE instead of grinding
    blindly. Best-effort (empty verdict on error -> treated as winnable, never auto-certified).
    reference_check=True builds a clean reference + proves slop the SOUND way (heavy; give-up only)."""
    import determinex_autofix as AX
    import determinex_pb_autofix as AF

    full = AF._resolve_full_slug(slug) or slug
    report = OVERRIDES / full / "eval_report.json"
    if not report.exists():
        return {"n": 0, "reopen": 0, "genuine": 0, "slop": 0, "note": "no-report"}
    try:
        return AX.triage(report, submission=OVERRIDES / full, reference_check=reference_check)
    except Exception as e:
        return {"n": 0, "reopen": 0, "genuine": 0, "slop": 0, "note": f"triage-err: {e}"}


def _certify_ceiling(slug: str, tri: dict) -> dict:
    """Certify a PROVEN ceiling so the queue STOPS grinding it. Caller MUST gate: only when the
    triage proved EVERY remaining failure IMPOSSIBLE (reopen==0, genuine>0, slop==0). Writes the
    proof doc to locked/<tool>/CEILING_CERT.md + registers in proven_ceilings.json (which the
    queue-order drops). Honest + REVERSIBLE -- delete the registry entry if later shown winnable."""
    import determinex_pb_autofix as AF

    full = AF._resolve_full_slug(slug) or slug
    try:
        dest = LOCKED / full
        dest.mkdir(parents=True, exist_ok=True)
        cert = [
            f"# CEILING CERT: {full}",
            "",
            f"Auto-certified {time.strftime('%Y-%m-%d %H:%M')} by autodrive triage "
            f"(Impossibility Adjudicator: every remaining failure proven IMPOSSIBLE).",
            f"genuine(proven-impossible)={tri.get('genuine')}  reopenable={tri.get('reopen')}  "
            f"slop={tri.get('slop')}",
            "",
            "## Proofs (per the Adjudicator)",
        ]
        for p in tri.get("proofs", []):
            cert.append(f"- {str(p)[:400]}")
        (dest / "CEILING_CERT.md").write_text("\n".join(cert) + "\n", encoding="utf-8")
    except Exception as e:
        return {"certified": False, "note": f"cert-doc-err: {e}"}
    pc_path = ROOT / "corpus" / "programbench" / "proven_ceilings.json"
    try:
        pc = json.loads(pc_path.read_text(encoding="utf-8")) if pc_path.exists() else {}
        if not isinstance(pc, dict):
            pc = {}
        pc.setdefault("schema", "proven-ceilings-v1")
        pc.setdefault("ceilings", {})
        pc["ceilings"][full] = {
            "genuine": tri.get("genuine"),
            "reopen": tri.get("reopen"),
            "certified": time.strftime("%Y-%m-%d"),
            "source": "autodrive-triage",
            "proofs": [str(p)[:300] for p in tri.get("proofs", [])][:5],
        }
        pc_path.write_text(json.dumps(pc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception as e:
        return {"certified": False, "note": f"registry-err: {e}"}
    return {"certified": True, "genuine": tri.get("genuine"), "registered": "proven_ceilings.json"}


def _archive_and_pin(slug: str, tarball: Path, data: dict) -> dict:
    """On a clean 100%: archive tarball+report into locked/<slug>/ then sha-pin via the
    registry (which re-checks clean + provenance-guard + archive-present)."""
    import determinex_pb_lock_registry as REG

    dest = LOCKED / slug
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(tarball, dest / "submission.tar.gz")
    report = dest / "eval_report.json"
    report.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return REG.verify_and_register(slug, report, source="autodrive")


def _load_log() -> dict:
    if LOG.exists():
        try:
            return json.loads(LOG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"_schema": "determinex-pb-autodrive-v1", "runs": {}}


def _save_log(d: dict) -> None:
    LOG.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


def _report_passed(path: Path) -> int:
    """passed-count of an eval_report.json on disk, or -1 if missing/unparseable."""
    if not path.exists():
        return -1
    try:
        from collections import Counter

        old = json.loads(path.read_text(encoding="utf-8"))
        return Counter(x.get("status") for x in (old.get("test_results") or [])).get("passed", 0)
    except Exception:
        return -1


def _persist_best(path: Path, data: dict, counts: dict) -> bool:
    """Write the eval report to `path` ONLY if it is BETTER than what's already there -- more tests
    passed, OR a full lock, OR the existing is missing/unparseable. Keeps the BEST eval per tool so a
    flaky or memory-STARVED re-eval (the 0-passed / all-not_run case the box-memory note warns about)
    can NEVER clobber a good result. The board + durability track the best, not the latest. autofix
    then works on the best state's remaining failures. Returns True if it wrote."""
    new_p = int(counts.get("passed", 0) or 0)
    new_t = int(counts.get("total", 0) or 0)
    old_p = _report_passed(path)
    if new_p > old_p or (new_t > 0 and new_p == new_t) or old_p < 0:
        path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        return True
    return False


def _hetzner_up() -> bool:
    """Is the Hetzner eval box reachable? The watch loop gates on this so a Hetzner
    outage makes autodrive IDLE (local-only mode) instead of error-spamming the queue."""
    import subprocess

    try:
        from pb_eval_unified import HETZNER_IP, HETZNER_SSH_KEY

        r = subprocess.run(
            [
                "ssh",
                "-i",
                str(HETZNER_SSH_KEY),
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "ConnectTimeout=10",
                "-o",
                "BatchMode=yes",
                f"root@{HETZNER_IP}",
                "true",
            ],
            capture_output=True,
            timeout=20,
        )
        return r.returncode == 0
    except Exception:
        return False


def _fresh_eval(slug: str, tarball: Path) -> tuple[dict, dict, str]:
    """Run a real eval; return (data, counts, verdict). Uses the LOCAL eval when we're already
    ON the eval box (/root/ProgramBench present) -- SSHing to ourselves fails; falls back to the
    remote Hetzner path off-box. Env DETERMINEX_EVAL_LOCAL=1/0 forces the choice."""
    import os
    from pathlib import Path as _P

    from pb_eval_unified import run_hetzner_eval, run_local_eval

    force = os.environ.get("DETERMINEX_EVAL_LOCAL")
    use_local = (force == "1") or (force != "0" and _P("/root/ProgramBench").is_dir())
    data = (run_local_eval(slug, tarball) if use_local else run_hetzner_eval(slug, tarball)) or {}
    c = parse_counts(data)
    return data, c, verdict_of(c)


def _sub_fingerprint(d: Path) -> tuple:
    """(relpath, size, mtime_ns) for every file under the submission dir -- a wording-independent
    way to tell whether an --apply actually CHANGED the submission (the autofix prints an
    `-- APPLIED --` header even when the action list is empty)."""
    fp = []
    for p in sorted(d.rglob("*")):
        if p.is_file():
            try:
                st = p.stat()
                fp.append((str(p.relative_to(d)), st.st_size, st.st_mtime_ns))
            except OSError:
                pass
    return tuple(fp)


def _behavioral_fix(slug: str, verdict: str = "behavioral") -> dict:
    """BEHAVIORAL END -- the autodrive's old dead-end, now where the residual gets CLOSED. The
    build is un-broken but real tests still fail. Close it LEGITIMATELY, never PYTEST_CURRENT_TEST
    gaming. NOTE on stage 2: a from-scratch native reimpl can't beat a working build's high pass-rate
    and won't converge in any sane budget (jplot, a 1441-test NEAR-LOCK, timed out the 3600s reimpl
    producing nothing -- pure waste). So stage 2 is SKIPPED for near-locks and time-capped otherwise.
      (1) determinex_autofix --apply -- the adjudicator applies deterministic REAL-CONTEXT fixes
          (ROUTE detect-on-cwd/argv/env, MATCH env+technique: pty/locale/..., IMPOSSIBLE -> proof).
      (2) if nothing deterministic changed (a genuine semantic NEEDS_WORK residual), the corpus-fed
          black-box reimpl loop (determinex_reimpl_drive) proposes a real native reimpl -- the LLM
          touch, on a clean un-broken slate (the legit native path).
    Returns {changed, notes}. The autodrive re-evals the result through the SAME cache-purge +
    provenance-guard path, so a behavioral fix that regresses or games is rejected at the pin."""
    import subprocess as _sp

    import determinex_pb_autofix as AF

    full = AF._resolve_full_slug(slug) or slug
    d = OVERRIDES / full
    report = d / "eval_report.json"
    scripts = ROOT / "scripts"
    changed = False
    notes: list[str] = []
    # (1) adjudicated deterministic real-context behavioral fixes (legit, no gaming). Detect a REAL
    #     change by fingerprinting the submission dir before/after: the autofix prints an
    #     `-- APPLIED --` header even when the action list is empty, so keyword-matching the output
    #     false-positives and would loop the autodrive re-evaling an unchanged submission.
    before = _sub_fingerprint(d)
    try:
        r = _sp.run(
            [
                sys.executable,
                str(scripts / "determinex_autofix.py"),
                "report",
                str(report),
                "--apply",
                "--submission",
                str(d),
            ],
            capture_output=True,
            text=True,
            timeout=900,
        )
        o = (r.stdout or "") + (r.stderr or "")
        notes.append("adjudicate:" + o[-160:].replace("\n", " "))
    except Exception as e:
        notes.append(f"adjudicate-err:{e}")
    if _sub_fingerprint(d) != before:
        changed = True
    # (2) deterministic layer closed nothing -> the corpus-fed LLM reimpl (black-box, legit). This is
    #     a SEPARATE track: determinex_reimpl_drive runs its OWN official eval (now cache-purge'd) + corpus
    #     record, writing logs/reimpl/<short>_drive.py -- it does NOT write per_tool_overrides. So it
    #     must NOT set `changed`: that would loop the autodrive re-evaling an unchanged submission and
    #     re-running the model every attempt. Run once, capture the official score; a lock is surfaced
    #     as a promotion candidate (guarded promotion is a separate step -- never auto-clobber a
    #     hand-tuned foundation submission).
    reimpl_official = None
    # Skip the (futile, slow) reimpl on near-locks: a working build already >=90%, a from-scratch
    # reimpl can't beat it and just burns the timeout. Only attempt it on lower-pass "behavioral"
    # residuals where a reimpl could plausibly help -- and cap it at 900s so one tool can't eat an hour.
    allow_reimpl = os.environ.get("DETERMINEX_AUTODRIVE_ALLOW_REIMPL") == "1"
    if not changed and verdict != "near-lock" and allow_reimpl:
        try:
            # NOTE: reimpl_drive runs the official eval by DEFAULT; the flag to disable is
            # --no-official. There is no --official (passing it crashes argparse -> stage 2 never
            # ran; caught live on nsh). Official eval stays on by omission.
            models = os.environ.get("DETERMINEX_REIMPL_MODELS", "local/qwen2.5-coder:7b-instruct")
            lang = os.environ.get("DETERMINEX_REIMPL_LANG", "python")
            r = _sp.run(
                [
                    sys.executable,
                    str(scripts / "determinex_reimpl_drive.py"),
                    full,
                    "--iters",
                    "1",
                    "--models",
                    models,
                    "--lang",
                    lang,
                ],
                capture_output=True,
                text=True,
                timeout=900,
            )
            o = (r.stdout or "") + (r.stderr or "")
            m = re.search(r"OFFICIAL:\s*(\d+)\s*/\s*(\d+)\s+solved=(\w+)", o)
            if m:
                solved = (
                    m.group(3).strip().lower() == "true" or "verified skill locked" in o.lower()
                )
                reimpl_official = {
                    "passed": int(m.group(1)),
                    "total": int(m.group(2)),
                    "solved": solved,
                }
            notes.append("reimpl:" + o[-160:].replace("\n", " "))
        except Exception as e:
            notes.append(f"reimpl-err:{e}")
    elif not changed and verdict != "near-lock":
        notes.append(
            "reimpl-skipped: autodrive does not launch LLM reimpl by default; "
            "ask_corpus -> local oracle -> explicit determinex_reimpl_drive lane required"
        )
    return {"changed": changed, "notes": notes, "reimpl_official": reimpl_official}


def _amplify_build_fix(slug: str) -> dict:
    """Build-COMMAND/layout fix (lua-class) that the deterministic dep/source fixers can't do: ask
    the model for a corrected compile.sh, VERIFIED by re-eval -- amplified verified-search keeps a
    candidate ONLY if it actually builds + passes more (never gamed; sound-oracle bounded). Reuses
    determinex_pb_amplified_fix + determinex_providers (make_hetzner_eval_fn auto-evals LOCALLY on the box).
    Writes the winning compile.sh into the override dir; the drive's next re-eval + provenance pin
    validate it. Returns {changed, ...}."""
    import determinex_pb_autofix as AF

    full = AF._resolve_full_slug(slug) or slug
    d = OVERRIDES / full
    cs_path = d / "compile.sh"
    report = d / "eval_report.json"
    if not cs_path.exists():
        return {"changed": False, "note": "no compile.sh"}
    try:
        import determinex_pb_amplified_fix as AMP
        import determinex_providers as PV
    except Exception as e:
        return {"changed": False, "note": f"amplify-unavailable: {e}"}
    avail = [n for n, ok in PV.available().items() if ok]
    if not avail:
        return {"changed": False, "note": "no model provider"}
    failures = []
    try:
        tr = json.loads(report.read_text(encoding="utf-8")).get("test_results") or []
        failures = [
            AMP._Failure(
                x.get("test_id", "") or x.get("name", ""),
                x.get("name", ""),
                (x.get("extra", {}) or {}).get("text", "")
                if isinstance(x.get("extra"), dict)
                else "",
            )
            for x in tr
            if x.get("status") not in ("passed", "not_run", "skipped")
        ][:25]
    except Exception:
        pass
    compile_sh = cs_path.read_text(encoding="utf-8", errors="replace")
    try:
        base_tarball = _repack(slug)
        generate = PV.get_rotating_generator(avail)
        eval_fn = AMP.make_hetzner_eval_fn(full, base_tarball)  # auto-local on the eval box
        r = AMP.amplified_fix(full, compile_sh, failures, generate, eval_fn, k=4, rounds=1)
    except Exception as e:
        return {"changed": False, "note": f"amplify-err: {e}"}
    best = getattr(r, "best", None)
    if getattr(r, "solved", False) and best is not None:
        cs_path.write_text(best.text, encoding="utf-8", newline="\n")
        # FLYWHEEL: distill this VERIFIED solve into a learned class so the NEXT tool with the same
        # symptom gets the fix first-shot. Grows build_knowledge.learned_classes; the grounded
        # prompt picks it up live. Oracle-gated next use, so a rough class can only help.
        learned = {}
        try:
            ftext = "\n".join((getattr(f, "text", "") or "") for f in failures)[:4000]
            learned = AMP.learn_class(full, ftext, compile_sh, best.text)
        except Exception as e:
            learned = {"learned": False, "why": f"flywheel-err: {e}"}
        return {
            "changed": True,
            "solved": True,
            "samples": getattr(r, "total_samples", None),
            "proof": (getattr(r, "proof", "") or "")[:120],
            "learned": learned,
        }
    return {
        "changed": False,
        "solved": False,
        "samples": getattr(r, "total_samples", None),
        "next": (getattr(r, "next_moves", None) or [])[:3],
    }


def _free_disk() -> None:
    """Recover disk for evals by pruning transient :determinex-cached build images (they rebuild on
    demand -- the cache-purge already forces a rebuild) + dangling images + build/container cache.
    Keeps :task + cleanroom images. Called on a disk-guard eval error (nothing is mid-build at that
    point), so the box-resident drive self-heals instead of eval-erroring the rest of the queue."""
    import subprocess as _sp

    try:
        # The shell was here for one pipe into grep. Python filters a list without granting
        # /bin/sh a say in what runs.
        _all = _sp.run(
            ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout.split()
        imgs = [i for i in _all if ":determinex-cached" in i]
        for img in imgs:
            _sp.run(["docker", "rmi", "-f", img], capture_output=True, timeout=30)
        for args in (
            ["image", "prune", "-f"],
            ["builder", "prune", "-f"],
            ["container", "prune", "-f"],
        ):
            _sp.run(["docker", *args], capture_output=True, timeout=120)
        print(
            f"  [self-heal] pruned {len(imgs)} :determinex-cached + caches to recover eval disk",
            flush=True,
        )
    except Exception:
        pass


def drive_one(slug: str, max_attempts: int, dry_run: bool) -> dict:
    """PROBE-FIRST closed loop. The local eval_report is often STALE (srgn read 86%
    locally while the live build was 0/2080 + missing go.mod), so we NEVER let a stale
    report pick the fix. Order: fresh eval -> if clean, pin -> else autofix on the FRESH
    report -> repack -> re-eval. Gate on the real outcome, never on fix-text presence."""
    import determinex_pb_autofix as AF

    slug = AF._resolve_full_slug(slug) or slug  # eval_index short slug ('ov') -> real override dir
    log: dict = {
        "slug": slug,
        "attempts": [],
        "verdict": "?",
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    if not (OVERRIDES / slug).is_dir():
        log["verdict"] = "no-override-dir"
        return log

    if dry_run:
        fx = _autofix(slug, apply=False)
        log["attempts"].append(
            {"attempt": 0, "autofix": fx, "note": "dry-run: wiring OK, no live eval"}
        )
        log["verdict"] = "dry-run-ok"
        return log

    # Addendum H/I gate: consult corpus BEFORE repacking or official eval. If the
    # corpus says this is upstream-source or has a spec/skill that must be
    # checked locally, do not spend an official eval here. The reimpl/local-oracle
    # lane owns that next step.
    consult0 = _corpus_consult(slug)
    try:
        import determinex_pb_corpus_router as CR

        route0 = CR.route_from_corpus({**consult0, "slug": slug})
        route0d = route0.to_dict()
    except Exception as e:
        route0 = None
        route0d = {"verdict": "corpus-route-error", "error": str(e), "official_eval_allowed": False}
    if not route0d.get("official_eval_allowed"):
        log["attempts"].append({"attempt": 0, "corpus": consult0, "corpus_route": route0d})
        verdict = str(route0d.get("verdict") or "needs-local-oracle")
        if verdict == "needs-local-oracle":
            verdict = "needs-local-oracle-tail"
        log["verdict"] = verdict
        return log

    tarball = _repack(slug)
    last_passed = -1
    for attempt in range(1, max_attempts + 1):
        a: dict = {"attempt": attempt}
        t0 = time.time()
        try:
            data, c, v = _fresh_eval(slug, tarball)
        except Exception as e:
            emsg = str(e)
            if "PROVENANCE_REJECT" in emsg:
                a["error"] = f"eval-preflight-rejected: {emsg}"
                log["attempts"].append(a)
                log["verdict"] = f"clean-but-pin-rejected:{emsg}"
                return log
            # self-heal: the box-resident drive accumulates :determinex-cached build images until the
            # eval disk guard trips. Prune (safe -- the eval errored at preflight, nothing mid-build)
            # and retry ONCE so a full disk doesn't eval-error the rest of the queue.
            if "disk" in emsg.lower() and not a.get("disk_pruned"):
                _free_disk()
                a["disk_pruned"] = True
                try:
                    data, c, v = _fresh_eval(slug, tarball)
                except Exception as e2:
                    a["error"] = f"eval-error: {e2}"
                    log["attempts"].append(a)
                    log["verdict"] = "eval-error"
                    return log
            else:
                a["error"] = f"eval-error: {e}"
                log["attempts"].append(a)
                log["verdict"] = "eval-error"
                return log
        a.update({"counts": c, "verdict": v, "secs": int(time.time() - t0)})
        # ALWAYS persist the fresh eval report so the next --watch pass (and the
        # adjudicator) see the REAL current failures, never a stale build-broken report.
        # (atlas's override report read 1477 failures while the live eval was 2 -> the
        # stale-report bug that blocks behavioral near-lock closure.)
        try:
            _persist_best(
                OVERRIDES / slug / "eval_report.json", data, c
            )  # keep the BEST, never clobber
        except Exception:
            pass

        if v == "clean-lock":
            pin = _archive_and_pin(slug, tarball, data)
            a["pin"] = pin
            log["attempts"].append(a)
            log["verdict"] = (
                "LOCKED" if pin.get("ok") else f"clean-but-pin-rejected:{pin.get('why')}"
            )
            return log

        consult = _corpus_consult(slug)
        a["corpus"] = consult
        engine = consult.get("engine", "")
        if v == "near-lock" and engine in {"reimpl-skill-oracle", "spec-local-oracle"}:
            a["note"] = (
                "near-lock reimpl tail must be patched under determinex_local_oracle before another official eval"
            )
            log["attempts"].append(a)
            log["verdict"] = "needs-local-oracle-tail"
            return log
        if engine == "native-reimpl-loop":
            a["note"] = (
                "current override is upstream-source/provenance-invalid; route to explicit native reimpl lane"
            )
            log["attempts"].append(a)
            log["verdict"] = "needs-native-reimpl"
            return log

        # ROUTE on a TRIAGE of the residual: a PROVEN ceiling (every remaining failure IMPOSSIBLE,
        # nothing reopenable, no slop, with proof) is CERTIFIED + dropped from the queue -- don't
        # grind the impossible. Everything else is winnable -> fall through to the close chain.
        tri = _triage(slug)
        a["triage"] = {k: tri.get(k) for k in ("n", "reopen", "genuine", "slop") if k in tri}
        if (
            c.get("failed", 0) > 0
            and tri.get("reopen", 1) == 0
            and tri.get("genuine", 0) > 0
            and tri.get("slop", 0) == 0
            and tri.get("proofs")
        ):
            cert = _certify_ceiling(slug, tri)
            a["certify"] = cert
            log["attempts"].append(a)
            log["verdict"] = "ceiling-certified" if cert.get("certified") else v
            return log

        # Not a lock. If this is the last attempt, stop (don't fix what we won't re-eval).
        if attempt == max_attempts:
            a["note"] = "residual after final attempt; per-tool MATCH needed"
            log["attempts"].append(a)
            log["verdict"] = v
            return log

        # Feed the report into autofix where _find_eval_report looks. _persist_best keeps the BEST
        # (a flaky/starved worse re-eval won't clobber a good report); autofix targets its failures.
        fresh_report = OVERRIDES / slug / "eval_report.json"
        _persist_best(fresh_report, data, c)
        fx = _autofix(slug, apply=True)
        a["autofix"] = fx
        # On a build-fail, run the NEVER-BLIND chain: (1) harvest build.err -> diagnose missing deps
        # -> inject apt; (2) source-gap safety-net (genuine local gap only); (3) if those find
        # nothing, it's a build-COMMAND/layout issue -> model-amplified compile.sh fix (verified).
        sg = {"restored": []}
        be = {"applied": False}
        amp = {"changed": False}
        if v == "build-fail":
            be = _build_err_fix(slug)
            a["build_err_fix"] = be
            sg = _source_gap_fetch(slug)
            a["source_gap"] = sg
            if not be["applied"] and not sg["restored"]:
                # deterministic dep/source fixes found nothing -> a build-COMMAND/layout issue
                # (lua-class: wrong cd/make target). Ask the model for a corrected compile.sh,
                # VERIFIED by re-eval -- amplified search keeps ONLY a candidate that actually builds.
                amp = _amplify_build_fix(slug)
                a["amplify"] = amp
        log["attempts"].append(a)

        if (
            v == "build-fail"
            and not fx["changed"]
            and not be["applied"]
            and not sg["restored"]
            and not amp["changed"]
            and c["passed"] <= last_passed
        ):
            # build broken, autofix + source-gap + amplified compile.sh fix all found nothing,
            # no progress => mega-whale needing per-tool build engineering. Never spin.
            log["verdict"] = "needs-manual-build"
            return log
        # BEHAVIORAL END (was the dead-end): the build is un-broken but real tests still fail and
        # the deterministic build-class autofix changed NOTHING. DON'T stop -- the behavioral fix
        # MUST happen. Close it LEGITIMATELY (never PYTEST_CURRENT_TEST gaming): the adjudicator's
        # real-context fixes (ROUTE detect-on-cwd/argv/env, MATCH env+technique: pty/locale/...,
        # IMPOSSIBLE->proof) + the corpus-fed black-box LLM reimpl for a genuine semantic residual.
        # Then re-eval through the SAME cache-purge + provenance-guard path.
        if v != "build-fail" and not fx["changed"]:
            bx = _behavioral_fix(slug, v)
            a["behavioral_fix"] = bx
            if bx.get("changed"):
                # the adjudicator wrote a REAL-CONTEXT fix INTO the submission -> re-eval + pin it.
                last_passed = max(last_passed, c["passed"])
                tarball = _repack(slug)
                continue
            # deterministic layer exhausted. The LLM reimpl track ran once (corpus-learned,
            # official-scored) but does NOT write per_tool_overrides -> nothing to re-eval here.
            ro = bx.get("reimpl_official")
            if ro and ro.get("solved"):
                # the LLM produced a from-scratch native reimpl that OFFICIALLY passes 100% -- the
                # north star hit. Surface for guarded promotion (never auto-clobber the foundation).
                log["verdict"] = "reimpl-lock-candidate"
            else:
                # PHASE 3 (give-up only, bounded -> no per-pass build cost): prove the residual the
                # SOUND way -- build a clean reference + run the real invocations. Certify the ceiling
                # ONLY when EVERY remaining failure is proven-impossible OR proven-slop (a correct
                # binary fails it too) and NOTHING stays winnable. Reversible; never a false ceiling.
                tri2 = _triage(slug, reference_check=True)
                a["triage_ref"] = {
                    k: tri2.get(k) for k in ("n", "reopen", "genuine", "slop") if k in tri2
                }
                winnable_left = tri2.get("n", 0) - tri2.get("genuine", 0) - tri2.get("slop", 0)
                if (tri2.get("slop", 0) + tri2.get("genuine", 0)) > 0 and winnable_left <= 0:
                    cert = _certify_ceiling(slug, tri2)
                    a["certify_slop"] = cert
                    log["verdict"] = "ceiling-certified" if cert.get("certified") else v
                else:
                    log["verdict"] = v  # genuine residual stands; corpus learned for next time
            return log
        last_passed = max(last_passed, c["passed"])
        tarball = _repack(slug)  # re-eval the repacked candidate next attempt

    log["verdict"] = "exhausted-attempts"
    return log


def main() -> int:
    # Line-buffer stdout so the log reflects progress LIVE when redirected to a file. Block-buffered
    # stdout (the default for a non-tty) hides "Uploading/Purging/PID" + per-eval prints until the
    # buffer fills -> a "frozen" log looks like a hang when the eval is actually running on the box.
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--queue", choices=["build_fail_whales"], help="named queue")
    ap.add_argument("--slugs", help="comma-separated full slugs (overrides --queue)")
    ap.add_argument(
        "--all",
        action="store_true",
        help="drive the FULL non-locked queue (every drivable tool toward 200)",
    )
    ap.add_argument(
        "--watch",
        action="store_true",
        help="persistent: loop passes forever, re-reading the queue each time "
        "(new locks drop out); skips terminally-verdicted tools",
    )
    ap.add_argument(
        "--interval", type=int, default=1800, help="--watch sleep between passes (s); default 1800"
    )
    ap.add_argument(
        "--retry-terminal",
        action="store_true",
        help="--watch: also re-drive needs-manual/behavioral tools each pass",
    )
    ap.add_argument("--max-attempts", type=int, default=2)
    ap.add_argument(
        "--dry-run", action="store_true", help="wiring check: autofix only, no live eval, no pin"
    )
    args = ap.parse_args()

    def _resolve_queue() -> list[str]:
        if args.slugs:
            return [s.strip() for s in args.slugs.split(",") if s.strip()]
        if args.all:
            return _build_full_queue()
        if args.queue == "build_fail_whales":
            return list(BUILD_FAIL_WHALES)
        ap.error("specify --slugs, --all, or --queue")
        return []

    def _one_pass(pass_no: int) -> list[str]:
        state = _load_log()
        raw_queue = _resolve_queue()
        queue: list[str] = []
        seen: set[str] = set()
        for raw_slug in raw_queue:
            full = _canonical_slug(raw_slug)
            if full in seen:
                continue
            seen.add(full)
            queue.append(full)
        # skip tools already terminally verdicted (locked / stuck), unless --retry-terminal
        skip = set()
        if not args.retry_terminal:
            for slug, r in state.get("runs", {}).items():
                if isinstance(r, dict) and _is_terminal_verdict(r.get("verdict")):
                    skip.add(_canonical_slug(slug))
                    if r.get("slug"):
                        skip.add(_canonical_slug(str(r.get("slug"))))
        todo = [s for s in queue if s not in skip]
        print(
            f"\n[autodrive] ===== PASS {pass_no} | queue={len(queue)} "
            f"todo={len(todo)} skip(terminal)={len(skip)} =====",
            flush=True,
        )
        locked_now = []
        for i, slug in enumerate(todo, 1):
            print(f"\n[autodrive] [{i}/{len(todo)}] === {slug} ===", flush=True)
            try:
                r = drive_one(slug, args.max_attempts, args.dry_run)
            except Exception as e:
                r = {"slug": slug, "verdict": f"driver-error: {e}", "attempts": []}
            state = _load_log()  # reload (other writers) before merge-save
            state["runs"][slug] = r
            _save_log(state)
            attempts = r.get("attempts") or []
            last = attempts[-1] if isinstance(attempts, list) and attempts else {}
            counts = last.get("counts", "") if isinstance(last, dict) else ""
            print(f"[autodrive] {slug}: {r['verdict']}  {counts}", flush=True)
            if r["verdict"] == "LOCKED":
                locked_now.append(slug)
        print(
            f"\n[autodrive] PASS {pass_no} done. newly LOCKED: {len(locked_now)} {locked_now}",
            flush=True,
        )
        return locked_now

    if not args.watch:
        _one_pass(1)
        print(f"[autodrive] verdict log -> {LOG}")
        return 0

    # persistent watch: loop forever, re-reading the queue each pass. Gated on Hetzner:
    # if the eval box is down, IDLE (local-only mode -- the local corpus_loop carries on)
    # and re-probe every 5 min instead of error-spamming the queue.
    pass_no = 1
    total_locked = 0
    # ON the eval box, evals run LOCALLY (run_local_eval; /root/ProgramBench present) -- there is no
    # Hetzner to reach (SSHing to our own public IP fails), so the reachability gate must NOT idle us.
    # Only idle when we're a REMOTE driver (Windows) AND the box is down.
    on_box = Path("/root/ProgramBench").is_dir()
    while True:
        if not on_box and not _hetzner_up():
            print(
                f"[autodrive][watch] Hetzner UNREACHABLE — local-only mode; "
                f"idling, re-probe in 300s. ({datetime.datetime.now():%H:%M:%S})",
                flush=True,
            )
            time.sleep(300)
            continue
        total_locked += len(_one_pass(pass_no))
        print(
            f"[autodrive][watch] cumulative new locks: {total_locked}. "
            f"sleeping {args.interval}s before pass {pass_no + 1}...",
            flush=True,
        )
        pass_no += 1
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
