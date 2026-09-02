#!/usr/bin/env python3
"""backfill_verdict_language.py -- dimensional tagging backfill for code_verdict rows.

Originally scoped to just the 3 tools (tree-sitter/ninja/ditaa, 4,206 rows) whose language was
stamped a literal "unknown" by a since-removed writer. Extended 2026-07-18 to also tag
`build_system` for ALL 94,266 active-corpus rows -- the 2026-07-18 coverage audit found
by_build_system was 100% "unknown" across the whole corpus, the same generality gap as the
language finding but corpus-wide instead of 3 tools.

Ground truth, not guessing:
  - language: canonical_tasks.json via determinex_corpus_api.task_provenance (already proven).
  - build_system: derived from language via a verified mapping (rust->cargo, go->go,
    haskell->cabal cross-checked against pandoc's real compile.sh, java->per-tool sniff since
    Java has no single dominant tool -- ditaa verified uses lein), refined for c/cpp by sniffing
    the tool's own corpus/programbench/per_tool_overrides/<slug>/compile.sh for cmake vs make
    (verified against all 45 c/cpp tools: 45/45 resolved cleanly except cmatrix/lz4/pigz, which
    have neither wrapper in their compile.sh and are left as build_system="unknown" rather than
    guessed).

SAFETY: only rows whose CURRENT signature verifies are touched (a row that fails verification is
already broken by something else and is left for the signature-heal path, not silently patched
here). Every row's task_id must resolve via task_provenance before any field changes.

Usage:  python scripts/corpus/backfill_verdict_language.py [--apply]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import determinex_corpus_api as api  # noqa: E402

from corpus.corpus_manager import _verify_signature, resign_record  # noqa: E402

CODE_VERDICT_DIR = Path("T:/determinex_corpus/code_verdict")
TASK_ID_RE = re.compile(r"^pb_(.+?)_(?:eval\.tests|tests)\.")
OVERRIDES_DIR = ROOT / "corpus" / "programbench" / "per_tool_overrides"

# language (as stored in canonical_tasks.json) -> fixed build_system, EXCEPT "c"/"cpp"/"java"
# which need per-tool refinement (see _build_system_for below).
_LANG_TO_BUILD: dict[str, str] = {
    "rs": "cargo",
    "go": "go",
    "hs": "cabal",
}


def _slug_for(task_id: str) -> str | None:
    m = TASK_ID_RE.match(task_id)
    return m.group(1) if m else None


_cmake_make_cache: dict[str, str] = {}
_JAVA_BUILD_OVERRIDES = {
    "stathissideris__ditaa.f2286c4": "lein"
}  # verified per-tool (no single Java default)


def _build_system_for(slug: str, language: str) -> str | None:
    if language in _LANG_TO_BUILD:
        return _LANG_TO_BUILD[language]
    if language == "java":
        return _JAVA_BUILD_OVERRIDES.get(slug)  # unresolved Java tools stay untagged, not guessed
    if language in ("c", "cpp"):
        if slug in _cmake_make_cache:
            return _cmake_make_cache[slug] or None
        p = OVERRIDES_DIR / slug / "compile.sh"
        result = ""
        if p.exists():
            txt = p.read_text(encoding="utf-8", errors="replace")
            if re.search(r"\bcmake\b", txt):
                result = "cmake"
            elif re.search(r"\bmake\b", txt):
                result = "make"
        _cmake_make_cache[slug] = result
        return result or None
    return None


def run(apply: bool = False) -> dict:
    canonical = api.load_canonical_tasks()
    lang_cache: dict[str, str | None] = {}
    unresolvable: set[str] = set()
    results: dict = {
        "scanned": 0,
        "language_corrected": 0,
        "build_system_tagged": 0,
        "sig_invalid_skipped": [],
        "by_tool": {},
    }
    files = sorted(CODE_VERDICT_DIR.glob("*.jsonl"))
    for f in files:
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        out_lines = []
        touched = False
        for line in lines:
            if not line.strip():
                out_lines.append(line)
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                out_lines.append(line)
                continue
            results["scanned"] += 1
            slug = _slug_for(str(rec.get("task_id", "")))
            if slug is None:
                # NOT a gap: SWE-bench rows (task_id shaped "<repo>__<repo>-<issue>", e.g.
                # "django__django-10914") don't match the PB task_id pattern by design -- this
                # tagger is PB-specific (canonical_tasks.json only covers PB). SWE-bench rows
                # already carry source_benchmark="SWE-bench_Lite" correctly; they need their own
                # tagger if ever backfilled, not this one.
                unresolvable.add(rec.get("task_id"))
                out_lines.append(line)
                continue
            if slug not in lang_cache:
                prov = api.task_provenance(slug, canonical)
                lang_cache[slug] = prov.language if prov else None
            real_lang = lang_cache[slug]
            if not real_lang:
                unresolvable.add(rec.get("task_id"))
                out_lines.append(line)
                continue

            cur_lang = rec.get("language") or rec.get("lang")
            fix_lang = cur_lang == "unknown" and real_lang
            build_sys = _build_system_for(slug, real_lang)
            fix_build = build_sys and rec.get("build_system") != build_sys
            if not (fix_lang or fix_build):
                out_lines.append(line)
                continue

            if not _verify_signature(rec):
                results["sig_invalid_skipped"].append(rec.get("task_id"))
                out_lines.append(line)
                continue
            if fix_lang:
                rec["language"] = real_lang
                rec["lang"] = real_lang
                results["language_corrected"] += 1
            if fix_build:
                rec["build_system"] = build_sys
                results["build_system_tagged"] += 1
            rec = resign_record(rec)
            results["by_tool"][slug] = results["by_tool"].get(slug, 0) + 1
            out_lines.append(json.dumps(rec, ensure_ascii=True))
            touched = True
        if touched and apply:
            f.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    results["applied"] = apply
    results["unresolvable_slug"] = sorted(unresolvable)
    return results


def main() -> int:
    res = run(apply="--apply" in sys.argv)
    print(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
