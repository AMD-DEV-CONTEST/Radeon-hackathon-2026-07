#!/usr/bin/env python3
"""
determinex_pb_provenance_guard.py -- anti-test-gaming guard (the credibility gate)
===============================================================================
The #1 "laughed at" risk: a locked binary that PASSES by DETECTING THE TEST (reads the test
name, embeds golden outputs, switches behavior on test identity) instead of IMPLEMENTING the
tool. One such tool found by a skeptic's grep discredits the entire board. This is distinct
from determinex_copyright_guard (which checks attribution vs registered references); this checks
that the binary EARNS its passes.

It scans each locked tool's SOURCE for gaming signatures and demands every hit be either
JUSTIFIED (recorded in provenance_justifications.json -- e.g. svd2rust-style per-context
routing where the contexts are genuinely distinct and the output is independently correct)
or treated as a RED violation. Surface + require justification = a skeptic's grep finds
nothing we haven't already audited.

Gaming signatures (RED unless justified):
  * reads test identity        PYTEST_CURRENT_TEST, sys.argv scan for test paths, stack-walk to test
  * embeds golden output        include_bytes!/include_str!/embed of golden|expected|snapshot|fixture
  * branches on test name       match/switch/if on a test-name string to choose output
Usage:
  python scripts/determinex_pb_provenance_guard.py            # report
  python scripts/determinex_pb_provenance_guard.py --guard    # exit 1 if any UNJUSTIFIED hit on a lock
"""

from __future__ import annotations

import json
import os
import re
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCKED = ROOT / "corpus" / "programbench" / "locked"
REG = ROOT / "corpus" / "programbench" / "verified_locks.json"
JUST = ROOT / "corpus" / "programbench" / "provenance_justifications.json"
# from-source PROOFS: a lock that ships a prebuilt binary is only cleared if its source
# build was independently verified (answer-key removed -> still builds + passes). Written by
# pb_provenance_verify. A shipped binary WITHOUT a proof here is an unverified credibility
# risk (the atlas failure mode) and fails the guard.
PROOFS = ROOT / "corpus" / "programbench" / "provenance_proofs.json"


def load_proofs() -> dict:
    if not PROOFS.exists():
        return {}
    try:
        return json.loads(PROOFS.read_text(encoding="utf-8")).get("from_source", {})
    except Exception:
        return {}


def record_proof(slug: str, info: dict) -> None:
    """Record a verified from-source build (clears the ships-prebuilt-binary flag)."""
    data = {"from_source": {}}
    if PROOFS.exists():
        try:
            data = json.loads(PROOFS.read_text(encoding="utf-8"))
            data.setdefault("from_source", {})
        except Exception:
            data = {"from_source": {}}
    data["from_source"][slug] = info
    PROOFS.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


GAMING = [
    (
        "reads-test-identity",
        re.compile(
            r"PYTEST_CURRENT_TEST|PYTEST_XDIST|getenv\([\"']PYTEST|"
            r"argv.*test_|inspect\.stack\(\).*test|__name__.*test_",
            re.I,
        ),
    ),
    (
        "embeds-golden",
        re.compile(
            r"include_bytes!\s*\(\s*[\"'][^\"']*(golden|expected|snapshot|fixture|\.out)|"
            r"include_str!\s*\(\s*[\"'][^\"']*(golden|expected|snapshot|fixture)|"
            r"embed_file.*(golden|expected|snapshot)",
            re.I,
        ),
    ),
    (
        "branch-on-test-name",
        re.compile(
            r"(match|switch|if|case)[^\n]{0,40}(test_[a-z0-9_]+)[^\n]{0,20}(=>|:|then|\{)|"
            r"==\s*[\"']test_[a-z0-9_]+[\"']",
            re.I,
        ),
    ),
]
_SRC_EXT = (".rs", ".go", ".c", ".cpp", ".h", ".hpp", ".py", ".js", ".ts")


def load_just() -> dict:
    return json.loads(JUST.read_text(encoding="utf-8")) if JUST.exists() else {"justified": {}}


def examinable(tool: str) -> list[str]:
    """Which artifacts of `tool` this guard can actually open.

    scan_tool() returns [] both when a tool is genuinely clean and when there is
    nothing to look at -- a missing tarball hits `return hits`, an unreadable one hits
    `except Exception: pass`. Those are opposite facts sharing one representation, and
    the guard read the pair as "clean".

    Measured 2026-07-29 on the real tree: 2 of the 5 verified_locks entries
    (`cheat__cheat.b8098dc`, `lymphatus__caesium-clt`) had NEITHER a submission tarball
    NOR a tracked source/ dir, so 40% of the registry was certified free of test-gaming
    having been examined not at all. `cheat__cheat.b8098dc` is also a registry/disk NAME
    mismatch: disk carries `cheat__cheat/`, holding only a ceiling cert.
    """
    found = []
    if (LOCKED / tool / "source").is_dir():
        found.append("source/")
    if (LOCKED / tool / "submission.tar.gz").exists():
        found.append("submission.tar.gz")
    return found


def near_matches(tool: str) -> list[str]:
    """Locked dirs whose name is close to `tool`, so an unscannable entry can name its
    own likely fix instead of leaving the operator to guess at a rename."""
    if not LOCKED.is_dir():
        return []
    stem = tool.split(".")[0]
    return sorted(
        d.name
        for d in LOCKED.iterdir()
        if d.is_dir()
        and d.name != tool
        and not d.name.startswith("_")
        and (d.name.startswith(stem) or stem.startswith(d.name))
    )[:3]


def scan_tool(tool: str) -> list[dict]:
    hits = []
    # SOURCE-SNAPSHOT scan: the submission.tar.gz is often gitignored (regenerable), so the
    # tracked evidence is locked/<tool>/source/. An answer-key ELF committed THERE is the same
    # credibility risk as one in the tarball -- scan it too (closes the prior blind spot where
    # the guard only opened the tarball and missed binaries committed in source/).
    src_dir = LOCKED / tool / "source"
    if src_dir.is_dir():
        for p in src_dir.rglob("*"):
            try:
                if p.is_file() and p.stat().st_size > 2_000_000:
                    with open(p, "rb") as fh:
                        if fh.read(4) == b"\x7fELF":
                            hits.append(
                                {
                                    "file": f"source/{p.relative_to(src_dir).as_posix()}",
                                    "kind": "ships-prebuilt-binary",
                                    "snippet": f"{p.stat().st_size // 1024 // 1024}MB ELF in tracked source/",
                                }
                            )
            except Exception:
                continue
    tarp = LOCKED / tool / "submission.tar.gz"
    if not tarp.exists():
        return hits
    try:
        with tarfile.open(tarp, "r:gz") as t:
            for m in t.getmembers():
                n = m.name
                low = n.lower()
                # BUILD-PROVENANCE: a submission that SHIPS a prebuilt binary can pass by
                # falling back to that answer-key ELF instead of building from source (the
                # atlas failure mode: a 'lock' that was the official binary, not the build).
                # Any shipped large ELF is a credibility risk -> demand a from-source proof.
                if m.isfile() and m.size > 2_000_000:
                    magic = b""
                    try:
                        ef = t.extractfile(m)
                        if ef is not None:
                            magic = ef.read(4)
                    except Exception:
                        magic = b""
                    if magic == b"\x7fELF":
                        hits.append(
                            {
                                "file": n,
                                "kind": "ships-prebuilt-binary",
                                "snippet": f"{m.size // 1024 // 1024}MB ELF shipped in submission",
                            }
                        )
                        continue
                # SOURCE only (skip the shipped test files themselves)
                if (
                    not n.endswith(_SRC_EXT)
                    or "/test" in low
                    or low.startswith("test")
                    or "conftest" in low
                ):
                    continue
                try:
                    txt = t.extractfile(n).read().decode("utf-8", "replace")
                except Exception:
                    continue
                for kind, rx in GAMING:
                    mm = rx.search(txt)
                    if mm:
                        hits.append({"file": n, "kind": kind, "snippet": mm.group(0)[:80]})
    except Exception:
        pass
    return hits


def audit() -> dict:
    reg = list(json.loads(REG.read_text(encoding="utf-8"))["locks"]) if REG.exists() else []
    just = load_just().get("justified", {})
    proofs = load_proofs()
    flagged = {}
    unscannable: dict[str, list[str]] = {}
    for tool in sorted(reg):
        if not examinable(tool):
            # Recorded, not skipped. "Nothing to open" is a distinct verdict from
            # "opened it and it was clean", and only the second one is a pass.
            unscannable[tool] = near_matches(tool)
            continue
        hits = scan_tool(tool)
        if not hits:
            continue

        # a hit clears if (a) recorded justified, OR (b) for ships-prebuilt-binary, a
        # from-source proof exists (the source build was verified without the answer key).
        def _cleared(h):
            if h["kind"] in just.get(tool, []):
                return True
            if h["kind"] == "ships-prebuilt-binary" and tool in proofs:
                return True
            return False

        unjust = [h for h in hits if not _cleared(h)]
        flagged[tool] = {
            "hits": hits,
            "unjustified": unjust,
            "status": "JUSTIFIED" if not unjust else "NEEDS-REVIEW",
        }
    return {
        "registry_present": REG.exists(),
        "scanned": len(reg) - len(unscannable),
        "registered": len(reg),
        "unscannable": unscannable,
        "flagged": flagged,
    }


def main() -> int:
    r = audit()
    guard = "--guard" in sys.argv
    # Opt-in abstention for a checkout that deliberately ships no locked archives (the public
    # mirror filters those vendored trees). Deliberately a flag, not an inference: see the
    # long note at the unscannable branch below.
    # Env var as well as flag: the pre-commit config is shared between the dev repo and the
    # public mirror, so the declaration has to live where the filtered checkout actually is
    # (the CI workflow), not in a config both of them read.
    allow_filtered = (
        "--allow-filtered-checkout" in sys.argv
        or os.environ.get("DETERMINEX_FILTERED_CHECKOUT") == "1"
    )
    print(
        f"provenance/anti-gaming scan: {r['scanned']} of {r['registered']} registered locks examined"
    )
    needs = {t: v for t, v in r["flagged"].items() if v["status"] == "NEEDS-REVIEW"}
    just = {t: v for t, v in r["flagged"].items() if v["status"] == "JUSTIFIED"}
    print(f"  JUSTIFIED (audited, recorded): {len(just)} {sorted(just)}")
    print(f"  NEEDS-REVIEW (potential gaming): {len(needs)}")
    for t, v in needs.items():
        for h in v["unjustified"][:3]:
            print(f"    {t}: {h['kind']} in {h['file']} -> {h['snippet']!r}")

    if r["unscannable"]:
        print(f"  UNSCANNABLE (no artifact on disk): {len(r['unscannable'])}")
        for tool, near in sorted(r["unscannable"].items()):
            hint = f"  (did you mean: {', '.join(near)}?)" if near else ""
            print(f"    {tool}: no source/ and no submission.tar.gz{hint}")

    if guard and needs:
        print(
            "\nPROVENANCE GUARD FAILED: unjustified test-gaming signatures on locked tools. "
            "Audit each: justify (genuinely-distinct context, independently-correct output) "
            "or fix the tool to implement the behavior. Record in provenance_justifications.json."
        )
        return 1

    # A verdict requires having looked. CLAUDE.md records what the alternative cost:
    # "regenerating the stale verified_locks.json (was 64, missing 35 locks -> the
    # provenance_guard never checked them) EXPOSED 4 illegitimate locks". A guard whose
    # input is absent or short does not complain about what is missing from it, so the
    # absence has to be the failure -- otherwise "PASSED" silently means "examined none".
    if guard and not r["registry_present"]:
        print(
            f"\nPROVENANCE GUARD FAILED: no registry at {REG}. Nothing was examined, so "
            "no lock can be certified. Regenerate verified_locks.json (see "
            "determinex_pb_lock_registry.py) and re-run."
        )
        return 1
    if guard and not r["registered"]:
        print(
            "\nPROVENANCE GUARD FAILED: the registry lists zero locks. Nothing was "
            "examined, so this is not a pass -- regenerate verified_locks.json."
        )
        return 1
    if guard and r["unscannable"]:
        # FILTERED vs BROKEN, and the difference must be DECLARED, never inferred.
        #
        # corpus/programbench/locked/ holds vendored upstream trees that filter_corpus does
        # not publish, so in the public mirror every archive is absent by design and this
        # guard would fail forever. The obvious shortcut is to infer "filtered" whenever
        # nothing is scannable -- and that is exactly wrong, because it is indistinguishable
        # from a registry naming a tool whose archive vanished. Counts cannot tell those
        # apart, so a guard that decides from counts is guessing that absence is benign.
        # That is the failure mode this whole module exists to refuse, and
        # tests/test_guards_never_pass_on_nothing.py is the thing that caught me doing it.
        #
        # So: unscannable is a HARD FAILURE by default. A filtered checkout says so out loud
        # with --allow-filtered-checkout, which still refuses to call the result a pass and
        # still fails the moment even one archive IS present (a partial tree is drift, not a
        # filter).
        if allow_filtered and r["scanned"] == 0 and len(r["unscannable"]) == r["registered"]:
            print(
                f"\nPROVENANCE GUARD CANNOT VERIFY: all {r['registered']} registered "
                "lock(s) have no artifact here, and --allow-filtered-checkout was passed, "
                "so this is declared to be a checkout that does not ship "
                "corpus/programbench/locked/. Nothing was gamed; nothing was examined "
                "either. NOT a pass -- an abstention."
            )
            return 0
        print(
            "\nPROVENANCE GUARD FAILED: a registered lock has no artifact to examine, so "
            "its provenance is unverified -- which is not the same as clean. Restore the "
            "archive, correct the registry entry, or drop the lock. If this checkout "
            "deliberately does not ship corpus/programbench/locked/ (the public mirror "
            "filters those vendored trees), pass --allow-filtered-checkout to abstain "
            "explicitly instead of having the guard assume it."
        )
        return 1
    if guard:
        print(
            f"\nPROVENANCE GUARD PASSED: {r['scanned']} lock(s) examined, "
            "no unjustified test-gaming."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
