#!/usr/bin/env python3
"""determinex_pb_absorb -- SEED the flywheel from everything the system already knows in PROSE.

The flywheel (determinex_pb_amplified_fix.learn_class) learns (symptom -> fix) classes from FUTURE
verified solves. But years of hand-won knowledge already sit in prose: the campaign milestones in
CLAUDE.md, the corpus pattern docs (FAILURE_GROUPS / cross_tool_patterns / the playbooks), the
program docs. This absorbs that prose into build_knowledge.learned_classes so the grounded fixer
applies the accumulated knowledge FIRST-shot -- not just what it re-learns.

SOUND: absorbed classes are flagged source=prose, verified=False. They are HINTS; the next use is
still oracle-gated (a wrong hint fails verification, no harm). Gaming patterns are excluded at
extraction. One-time seed; the flywheel continues from verified solves.

Usage:  python3 determinex_pb_absorb.py [--max-chunks N] [--dry-run]
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KN = ROOT / "corpus" / "programbench" / "build_knowledge.json"

EXTRACT_PROMPT = """From the notes below (about fixing CLI tools' BUILDS and TESTS for a benchmark),
extract REUSABLE fix classes. Output ONLY a JSON list (no prose). Each item:
  {{"detect": "<generalized symptom: an error/failure signature, with tool names, absolute paths and
     version numbers replaced by <tool> / <path> / <n>>",
    "fix": "<the concrete, generalizable fix: a build flag, toolchain pin, locale/timezone/clock,
     dep install, build-target, or output-format normalization>",
    "source_tool": "<the tool name if the note names one, else \\"\\">"}}
RULES: only CONCRETE, GENERALIZABLE fixes. EXCLUDE gaming (branching on PYTEST_CURRENT_TEST,
embedding golden/expected bytes, capping/ignoring test collection, shipping a prebuilt binary).
If the text contains no such fix, output exactly [].
NOTES:
{chunk}
JSON:"""

_GAMING = re.compile(
    r"pytest_current_test|current.test.routing|embed.*golden|golden.*bytes|del items\[|"
    r"collect_ignore|prebuilt binary|answer.key|hardcode.*expected",
    re.I,
)

# A real (symptom->fix) class: the DETECT looks like a FAILURE and the FIX is an ACTION -- this
# rejects strategy/meta prose the model sometimes returns ("X is the bottleneck -> move toward 100").
_SYMPTOM = re.compile(
    r"error|fail|not found|missing|cannot|can't|undefined|mismatch|exit|\brc\b|compil|build|panic|"
    r"exception|timeout|no such|expected|assert|unresolved|--|/workspace|stderr|stdout|segfault|"
    r"crash|wrong|incorrect|differ|unexpected|invalid|broke|broken|\bhang|stuck|version|skip|"
    r"not_run|rc=127|linker|header|cargo|go\.mod|configure",
    re.I,
)
_ACTION = re.compile(
    r"\b(install|build|export|set|add|convert|run|use|replace|remove|pin|enable|disable|apt|cargo|"
    r"make|cmake|sed|chmod|dos2unix|vendor|fetch|download|patch|inject|rename|link|copy|symlink|"
    r"create|generate|normalize|strip|wrap|redirect|mount|provision|ensure|check|verify|point|"
    r"target|expect|require|provide|specify|configure|update|delete|drop|prefer|switch|apply|"
    r"rebuild|recompile|adjust|correct|match|map|extract|validate|pass|disable)\b|--|=| -[a-zA-Z]",
    re.I,
)
# A raw CODE statement (not a failure description) -- the absorber sometimes pulls a code diff out of
# a source file ("if a in (...) -> if arg in (...)"); reject those as classes (refactors, not fixes).
_CODE = re.compile(
    r"^\s*(if |for |while |def |return |import |from |let |fn |func |var |const |pub |public |private |"
    r"class |struct |elif |else|try|except|match |switch |case |#include|//|/\*|\}|\{)",
    re.I,
)
# REQUIREMENT prose, not an observed failure: "X should support Y" / "ensure X handles Y". This was
# the dominant junk shape in the 2026-07-16 quarantine (behavioral-spec paraphrase loops). A detect
# in requirement voice is only kept if it ALSO carries a hard failure signature (a real observation).
_REQUIREMENT = re.compile(
    r"\b(should|must|shall|needs? to|is required to|ensure[sd]?|make sure|supports?|allows?|"
    r"handles?|accepts?|provides?)\b",
    re.I,
)
_HARD_FAIL = re.compile(
    r"error|fail|rc=\d|exit (code|status)|traceback|panic|segfault|not found|no such|missing|"
    r"mismatch|crash|\bhang|broken|undefined|timeout|cannot|can't|unresolved|assert|stderr|"
    r"not_run|linker|exception",
    re.I,
)
# A usable fix names a concrete ARTIFACT (a flag, package, command, file, version, env var) --
# "Ensure the tool supports both sort directions" names none and is unactionable requirement prose.
_CONCRETE = re.compile(
    r"--[a-z]|=|/[a-z]|\binstall\b|\bapt(-get)?\b|\bcargo\b|\bgo (mod|build)\b|\bsed\b|\bexport\b|"
    r"\bchmod\b|\bln -|\bmake\b|\bcmake\b|\bpatch\b|\bdos2unix\b|\bpip\b|\bnpm\b|\bgit \b|"
    r"\.(sh|toml|json|lock|mod|ac|mk|py|rs|go|c|h|cfg|ini|yaml|yml)\b|\bversion \d|(?-i:\b[A-Z_]{4,}\b)|"
    r"\bconftest\b|\bcompile\.sh\b|\btimeout \d|\b-[a-zA-Z] |\bsymlink\b|\bvendor\b|\blocale\b",
    re.I,
)


def _is_paraphrase_loop(det: str, fix: str) -> bool:
    """The quarantine's signature junk shape: the 'fix' merely restates the 'detect' ('ensure X
    supports Y' as the fix for 'X should support Y'). Real fixes name an ACTION+ARTIFACT the symptom
    does not (a flag, a package, a sed). High content-token overlap between the two = paraphrase."""
    dt = set(re.findall(r"[a-z0-9_.\-]{3,}", det.lower()))
    ft = set(re.findall(r"[a-z0-9_.\-]{3,}", fix.lower()))
    if not dt or not ft:
        return True
    novel = ft - dt  # what the fix ADDS beyond restating the symptom
    return len(novel) < 3 or len(ft & dt) / len(ft) > 0.75


def _quality_gate(det: str, fix: str) -> str | None:
    """Shared admission gate for absorbed/salvaged (unverified) classes. Returns the rejection
    reason, or None if the entry is admissible. Flywheel-verified entries never pass through this."""
    if len(re.findall(r"[A-Za-z]{3,}", det)) < 4:
        return "too-terse"
    if len(fix) < 10:
        return "fix-too-short"
    if not _SYMPTOM.search(det):
        return "no-symptom"
    if not _ACTION.search(fix):
        return "no-action"
    if _GAMING.search(det) or _GAMING.search(fix):
        return "gaming"
    if _CODE.search(det):
        return "code-not-symptom"
    if _REQUIREMENT.search(det) and not _HARD_FAIL.search(det):
        return "requirement-not-failure"
    if _REQUIREMENT.search(fix) and not _CONCRETE.search(fix):
        return "vague-fix"
    if _is_paraphrase_loop(det, fix):
        return "paraphrase-loop"
    return None


def _chunks(text: str, size: int = 3000):
    """Split on markdown structure so a chunk is a coherent note (a milestone / a pattern entry)."""
    parts = re.split(r"\n(?=#{1,6}\s|\* |\d+\.\s|\- |\|)", text)
    buf = ""
    for p in parts:
        if len(buf) + len(p) > size and buf.strip():
            yield buf
            buf = p
        else:
            buf = buf + "\n" + p if buf else p
    if buf.strip():
        yield buf


def _parse_json_list(out: str) -> list:
    """Robustly pull the JSON list out of a model reply (it may wrap it in prose/fences)."""
    if not out:
        return []
    m = re.search(r"\[.*\]", out, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _sources() -> list[Path]:
    """ALL the LOCAL prose knowledge to absorb -- the whole corpus, every doc, the specs, the memory
    learnings, the campaign milestones, and archived knowledge on T:. The web ingester (determinex_web
    or a saved-pages dir) drops fetched pages into corpus/programbench/ingest/ which this also picks
    up, so online material flows through the same distiller."""
    srcs: list[Path] = []
    for base, pat in (
        (ROOT / "corpus" / "programbench", "*.md"),  # top corpus docs (NOT source READMEs)
        (ROOT / "corpus" / "programbench" / "_strategy", "*.md"),
        (ROOT / "docs", "**/*.md"),  # the docs tree (no source trees in it)
        (ROOT / "specs", "*.md"),
        (ROOT / "corpus" / "programbench" / "ingest", "**/*.txt"),  # web-fetched pages land here
        (Path.home() / ".claude" / "projects" / "c--Dev-Determinex" / "memory", "*.md"),
    ):
        try:
            if base.exists():
                srcs += sorted(base.glob(pat))
        except Exception:
            continue
    for extra in (ROOT / "CLAUDE.md", ROOT.parent / "CLAUDE.md"):
        if extra.exists():
            srcs.append(extra)
    # NOTE: T:/determinex-archive + the T: tool-source trees are HUGE recursive globs -- too slow for
    # this per-batch hot path. They are a bounded one-time follow-on (--scan-drive writes a cached
    # file list to corpus/programbench/ingest/_drive_sources.txt that this then reads), not here.
    cache_list = ROOT / "corpus" / "programbench" / "ingest" / "_drive_sources.txt"
    if cache_list.exists():
        try:
            for line in cache_list.read_text(encoding="utf-8").splitlines():
                p = Path(line.strip())
                if line.strip() and p.exists():
                    srcs.append(p)
        except Exception:
            pass
    # CODEBASES: build configs (how tools/projects build -- the fix-relevant code) across the tool
    # overrides + T: tool source. The model extracts build patterns; the quality gate filters noise.
    cfg = (
        "compile.sh",
        "Cargo.toml",
        "go.mod",
        "Makefile",
        "CMakeLists.txt",
        "package.json",
        "pyproject.toml",
        "setup.py",
        "build.sh",
        "configure.ac",
    )
    cbase = (
        ROOT / "corpus" / "programbench" / "per_tool_overrides"
    )  # top-level config per tool only
    for name in cfg:
        try:
            if cbase.exists():
                srcs += sorted(cbase.glob("*/" + name))[:250]  # */name (top), not **/ (source tree)
        except Exception:
            continue
    # NOTE: the T: tool-source tree (determinex-programbench) is a HUGE recursive glob -- too slow for
    # this per-batch hot path. It's a bounded one-time follow-on (cached file list), not here.
    # de-dup; existing only; cap size at 400KB; SKIP dependency/build junk dirs (node_modules etc.)
    # SKIP behavioral_spec files: they describe INTENDED behavior (requirements), not observed
    # failures+fixes -- feeding them through the symptom->fix extractor produced 1165 tautological
    # paraphrase-loop "classes" (quarantined 2026-07-16, see learned_classes_quarantine_20260716).
    _SKIP = (
        "node_modules",
        "/.git/",
        "/target/",
        "/dist/",
        "/build/",
        "/vendor/",
        "site-packages",
        "/.venv",
        "/_superseded/",
        "behavioral_spec",
    )
    seen: set = set()
    out: list[Path] = []
    for s in srcs:
        try:
            sp = str(s).replace("\\", "/")
            if any(x in sp for x in _SKIP):
                continue
            rp = s.resolve()
            if s.exists() and rp not in seen and s.stat().st_size < 400_000:
                seen.add(rp)
                out.append(s)
        except (OSError, ValueError):
            continue
    return out


_CAP = 1500  # max learned classes kept (verified/flywheel preferred; the playbook ranks top-20)


def _bound_and_write(kn: dict, lc: dict, dry_run: bool) -> None:
    """MERGE-ON-WRITE, not blind-overwrite: a long absorb run (10-20+ min) holds `kn` in memory
    for its whole lifetime; if ANY other writer (a hand edit, another script) touches
    build_knowledge.json while this run is in flight, a naive full-snapshot write here silently
    erases that other write on the next periodic checkpoint. Found 2026-07-19: two entries
    recorded mid-session (corpus_hmac_key_missing_20260718,
    sqlite_migration_found_unnecessary_20260719) were lost this exact way and had to be manually
    restored. Fix: re-read the CURRENT on-disk file right before writing, and only overlay this
    run's own fields (learned_classes, absorbed_sources, and this run's in-memory kn's OTHER keys
    only if the disk copy doesn't already have a newer version of them) -- never blind-dump the
    stale in-memory snapshot over concurrent external edits."""
    if len(lc) > _CAP:  # keep verified (flywheel) over prose-absorbed, then recent
        drop = sorted(
            lc, key=lambda x: (bool(lc[x].get("verified")), str(lc[x].get("learned", "")))
        )
        for k in drop[: len(lc) - _CAP]:
            lc.pop(k, None)
    if dry_run:
        return
    try:
        current = json.loads(KN.read_text(encoding="utf-8"))
    except Exception:
        current = {}
    if isinstance(current, dict):
        # This run only OWNS learned_classes + absorbed_sources; every other top-level key gets
        # the CURRENT on-disk value if present (preserves concurrent external writes), falling
        # back to this run's in-memory copy only for keys the disk file doesn't have at all.
        merged = dict(current)
        for k, v in kn.items():
            if k not in ("learned_classes", "absorbed_sources") and k not in merged:
                merged[k] = v
        merged["learned_classes"] = lc
        merged["absorbed_sources"] = kn.get("absorbed_sources", [])
        kn = merged
    KN.write_text(json.dumps(kn, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def absorb(generate, max_chunks: int = 400, dry_run: bool = False) -> dict:
    """Model-extract (symptom->fix) classes from the prose into learned_classes. RESUMABLE (skips
    sources already in absorbed_sources) + INCREMENTAL (writes after each source) so a long FREE
    local-model run progresses + survives interruption; re-run to continue."""
    kn = json.loads(KN.read_text(encoding="utf-8"))
    lc = kn.setdefault("learned_classes", {})
    if not isinstance(lc, dict):
        lc, kn["learned_classes"] = {}, {}
    done = set(
        kn.setdefault("absorbed_sources", [])
        if isinstance(kn.get("absorbed_sources"), list)
        else []
    )
    added = scanned = skipped_gaming = srcs_done = 0
    for src in _sources():
        sid = str(src.resolve())
        if sid in done:  # RESUME: already absorbed this file
            continue
        if scanned >= max_chunks:
            break
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except Exception:
            done.add(sid)
            continue
        for ch in _chunks(text):
            if scanned >= max_chunks:
                break
            scanned += 1
            try:
                items = _parse_json_list(generate(EXTRACT_PROMPT.format(chunk=ch[:3500]), 0.1))
            except Exception:
                continue
            for it in items if isinstance(items, list) else []:
                if not isinstance(it, dict):
                    continue
                det = str(it.get("detect") or "").strip()[:200]
                fix = str(it.get("fix") or "").strip()[:600]
                if not det or not fix or len(det) < 12:
                    continue
                why = _quality_gate(det, fix)
                if why == "gaming":
                    skipped_gaming += 1
                if why:
                    continue
                key = (
                    "absorbed_"
                    + hashlib.sha256((det + "||" + fix).encode("utf-8")).hexdigest()[:10]
                )
                if key in lc:
                    continue
                lc[key] = {
                    "detect": det,
                    "symptom": det,
                    "fix": fix,
                    "source_tool": (str(it.get("source_tool") or "") or src.stem)[:40],
                    "source": "prose:" + src.name,
                    "verified": False,
                    "learned": time.strftime("%Y-%m-%d"),
                    "uses": 0,
                }
                added += 1
        done.add(sid)
        srcs_done += 1
        kn["absorbed_sources"] = sorted(done)
        _bound_and_write(kn, lc, dry_run)  # incremental checkpoint after each source
    return {
        "added": added,
        "scanned": scanned,
        "skipped_gaming": skipped_gaming,
        "srcs_done": srcs_done,
        "total_learned": len(lc),
        "remaining_sources": len(_sources()) - len(done),
    }


def scan_drive(max_files: int = 6000) -> dict:
    """One-time BOUNDED scan of the wider drive -- T: archive + every <repo-parent> project CODEBASE -- for
    knowledge + source files, written to the cached list _sources() reads. os.walk with junk-dir
    pruning (node_modules/.git/target/...) + a hard file cap, so it's bounded (the recursive globs
    were unbounded -> too slow). Includes code (.rs/.go/.c/.py) so the CODEBASES get ingested too."""
    import os

    # T:/determinex-archive is a 2.4MB post-rename skeleton; the real 29GB archive lives at
    # T:/determinex-archive (same split-brain pattern as corpus_root_split_brain_healed_2026_07_18
    # -- found + fixed 2026-07-19, this scan_drive() call had been silently reading ~nothing).
    roots = [
        Path("T:/determinex-archive"),
        ROOT.parent,
    ]  # T: archive + <repo-parent> (all 8 projects)
    SKIP = {
        "node_modules",
        ".git",
        "target",
        "dist",
        "build",
        "vendor",
        "site-packages",
        ".venv",
        "__pycache__",
        ".next",
        ".cargo",
        "determinex-models",
        "_superseded",
        ".pytest_cache",
        "backups",
        "dist-windows",
    }
    # prose + BUILD CONFIGS only. Raw .rs/.go/.c/.py source produces code-DIFF noise for a
    # symptom->fix distiller (gets purged); raw source belongs in a future code-RAG for the BUILDER.
    exts = {".md", ".txt", ".toml", ".mod", ".sh", ".cfg", ".ini", ".cmake"}
    found: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
            for f in files:
                if Path(f).suffix.lower() in exts:
                    fp = Path(dirpath) / f
                    try:
                        if fp.stat().st_size < 400_000:
                            found.append(str(fp))
                    except Exception:
                        continue
            if len(found) >= max_files:
                break
        if len(found) >= max_files:
            break
    out = ROOT / "corpus" / "programbench" / "ingest" / "_drive_sources.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(found), encoding="utf-8")
    return {"scanned_files": len(found), "cache": str(out)}


DOC_URLS = [
    # Rust / cargo
    "https://doc.rust-lang.org/cargo/reference/build-scripts.html",
    "https://doc.rust-lang.org/cargo/reference/config.html",
    "https://doc.rust-lang.org/cargo/commands/cargo-build.html",
    "https://doc.rust-lang.org/rustc/command-line-arguments.html",
    # Go
    "https://go.dev/doc/toolchain",
    "https://go.dev/ref/mod",
    "https://pkg.go.dev/cmd/cgo",
    # C / C++ / build
    "https://cmake.org/cmake/help/latest/manual/cmake.1.html",
    "https://cmake.org/cmake/help/latest/command/find_package.html",
    "https://www.gnu.org/software/make/manual/make.html",
    "https://people.freedesktop.org/~dbn/pkg-config-guide.html",
    # Python / pytest
    "https://docs.pytest.org/en/stable/how-to/failures.html",
    "https://packaging.python.org/en/latest/tutorials/packaging-projects/",
]


def _fetch_clean(u: str) -> str:
    """URL -> clean ingest text. Prefers Crawl4AI (github.com/unclecode/crawl4ai) when it is
    installed -- it renders JS and returns clean markdown, the right tool for the dynamic pages urllib
    cannot read (Stack Overflow, GitHub Issues). Falls back to urllib + tag-strip for static docs.
    Credit: Crawl4AI (unclecode/crawl4ai)."""
    try:
        from crawl4ai import WebCrawler  # type: ignore  # optional dep; clean JS-rendered markdown

        c = WebCrawler()
        c.warmup()
        md = (getattr(c.run(url=u), "markdown", "") or "").strip()
        if md:
            return md
    except Exception:
        pass  # not installed / API drift -> urllib fallback
    import urllib.request

    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 (determinex-ingest)"})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&[a-z#0-9]+;", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()


def fetch_urls(urls=None) -> dict:
    """Bulk-fetch curated DOC URLs (free, autonomous) -> stripped text in ingest/ -> the running
    distiller turns them into classes. Uses _fetch_clean (Crawl4AI when installed, else urllib), so
    JS-heavy pages (SO / GitHub Issues) work too once Crawl4AI is present."""
    urls = urls or DOC_URLS
    outdir = ROOT / "corpus" / "programbench" / "ingest"
    outdir.mkdir(parents=True, exist_ok=True)
    n = 0
    for u in urls:
        try:
            text = _fetch_clean(u)
            if len(text) > 300:
                fn = "web_" + re.sub(r"[^a-z0-9]+", "_", u.lower().split("//", 1)[-1])[:70] + ".txt"
                (outdir / fn).write_text(text[:200000], encoding="utf-8")
                n += 1
                print(f"  fetched {u} ({len(text)} chars)")
        except Exception as e:
            print(f"  fetch FAILED {u}: {e}")
    return {"fetched": n, "of": len(urls)}


def purge() -> dict:
    """One-pass cleanup: re-filter the ABSORBED (verified=False) learned_classes against the current
    quality gate (word-count + symptom + action + not-gaming + not-code) and drop the failures.
    Flywheel-VERIFIED classes are kept untouched. Run with the absorber paused (avoids a write race)."""
    kn = json.loads(KN.read_text(encoding="utf-8"))
    lc = kn.get("learned_classes", {})
    if not isinstance(lc, dict):
        return {"dropped": 0, "kept": 0}
    drop = []
    for k, v in list(lc.items()):
        if not isinstance(v, dict):
            drop.append(k)
            continue
        if v.get("verified"):  # flywheel-proven -> keep
            continue
        det, fix = str(v.get("detect", "")), str(v.get("fix", ""))
        if _quality_gate(det, fix) is not None:
            drop.append(k)
    for k in drop:
        lc.pop(k, None)
    KN.write_text(json.dumps(kn, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"dropped": len(drop), "kept": len(lc)}


_QUARANTINE_KEY = "learned_classes_quarantine_20260716"


def salvage_quarantine(apply: bool = False) -> dict:
    """Triage the 2026-07-16 quarantined learned_classes through the CURRENT quality gate (which now
    rejects the quarantine's dominant junk shapes: requirement-voice detects, vague requirement
    fixes, paraphrase loops). Default is a DRY-RUN report (counts by rejection reason + survivors);
    --apply readmits survivors into learned_classes as unverified hints (source preserved, tagged
    salvaged) and records the salvage inside the quarantine block. Never touches verified entries."""
    kn = json.loads(KN.read_text(encoding="utf-8"))
    q = kn.get(_QUARANTINE_KEY)
    entries = (q or {}).get("entries") if isinstance(q, dict) else None
    if not isinstance(entries, dict):
        return {"error": f"no quarantine entries under {_QUARANTINE_KEY}"}
    reasons: dict[str, int] = {}
    survivors: dict[str, dict] = {}
    for k, v in entries.items():
        if not isinstance(v, dict):
            reasons["malformed"] = reasons.get("malformed", 0) + 1
            continue
        det, fix = str(v.get("detect", "")).strip(), str(v.get("fix", "")).strip()
        # The quarantine's core finding: behavioral-spec files describe INTENDED behavior, so even
        # failure-shaped extractions from them are paraphrased requirements. Categorical exclusion.
        if "behavioral_spec" in str(v.get("source", "")):
            reasons["spec-sourced"] = reasons.get("spec-sourced", 0) + 1
            continue
        why = _quality_gate(det, fix) or "PASS"
        reasons[why] = reasons.get(why, 0) + 1
        if why == "PASS":
            survivors[k] = v
    res = {
        "quarantined": len(entries),
        "survivors": len(survivors),
        "by_reason": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        "applied": False,
        "sample_survivors": [
            {"detect": v["detect"][:100], "fix": v["fix"][:120]}
            for v in list(survivors.values())[:5]
        ],
    }
    if apply and survivors:
        lc = kn.setdefault("learned_classes", {})
        readmitted = 0
        for k, v in survivors.items():
            if k in lc:
                continue
            nv = dict(v)
            nv["verified"] = False
            nv["salvaged"] = time.strftime("%Y-%m-%d")
            lc[k] = nv
            entries.pop(k, None)  # moved out of quarantine, not duplicated
            readmitted += 1
        q["salvage_" + time.strftime("%Y%m%d")] = {
            "readmitted": readmitted,
            "gate": "requirement/vague-fix/paraphrase-aware _quality_gate",
            "note": "survivors moved to learned_classes as unverified hints; next use is oracle-gated",
        }
        q["count"] = len(entries)
        _bound_and_write(kn, lc, dry_run=False)
        res["applied"], res["readmitted"] = True, readmitted
    return res


def main() -> int:
    if "--salvage" in sys.argv:
        print(json.dumps(salvage_quarantine(apply="--apply" in sys.argv), indent=1))
        return 0
    if "--purge" in sys.argv:
        print(f"purge: {purge()}")
        return 0
    if "--fetch-urls" in sys.argv:
        print(f"fetch-urls: {fetch_urls()}")
        return 0
    if "--scan-drive" in sys.argv:
        print("scanning drive (bounded os.walk; T: archive + <repo-parent> codebases)...")
        print(f"drive scan: {scan_drive()}")
        return 0
    max_chunks = 400
    dry = "--dry-run" in sys.argv
    for i, a in enumerate(sys.argv):
        if a == "--max-chunks" and i + 1 < len(sys.argv):
            max_chunks = int(sys.argv[i + 1])
    allow_paid = "--allow-paid" in sys.argv
    sys.path.insert(0, str(ROOT / "scripts"))
    import determinex_providers as PV

    # FREE/LOCAL ONLY by default (operator: do not spend on paid APIs for bulk ingest). Only the
    # local model (Ollama) is used unless --allow-paid is passed.
    PAID = {"deepseek", "claude", "gemini", "codex", "groq", "openai", "openrouter", "anthropic"}
    avail = [n for n, ok in PV.available().items() if ok and (allow_paid or n not in PAID)]
    if not avail:
        print("absorb: no FREE/local provider available (pass --allow-paid to permit paid APIs)")
        return 1
    print(
        f"absorb: providers={avail} (free/local only) sources={len(_sources())} max_chunks={max_chunks}"
    )
    gen = PV.get_rotating_generator(avail)
    res = absorb(gen, max_chunks=max_chunks, dry_run=dry)
    print(f"absorb done: {res}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
