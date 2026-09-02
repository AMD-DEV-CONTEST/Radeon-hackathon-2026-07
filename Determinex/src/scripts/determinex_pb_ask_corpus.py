#!/usr/bin/env python3
"""
determinex_pb_ask_corpus.py -- ASK THE CORPUS what a single tool needs (corpus-first drive)
========================================================================================
For one tool, aggregate EVERYTHING the corpus knows -- so the system follows the corpus
verbatim instead of guessing. No duplication: it reads build_knowledge.json (per_tool +
class_patterns the tool is listed in) and runs the Impossibility Adjudicator over the
tool's freshest eval_report (per-failure prescribed technique). Returns one answer:
"here is what to do for this tool, and why."

The play (operator): ask_corpus(slug) -> apply its prescription (determinex_pb_autofix +
the named technique) -> eval -> record -> next tool. Evals are fast when compile.sh is
right; get each tool as high as it goes, then tackle the residual ceilings collectively.

Usage:
  python scripts/determinex_pb_ask_corpus.py <full_slug>
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PB = ROOT / "corpus" / "programbench"
sys.path.insert(0, str(ROOT / "scripts"))


def _short(slug: str) -> str:
    s = slug.split("__", 1)[1] if "__" in slug else slug
    return s.split(".")[0].replace("_native", "").replace("_model", "").lower()


_SRC_EXTS = (".go", ".rs", ".c", ".cc", ".cpp", ".h", ".hpp", ".py", ".js", ".ts")
_PRUNE_DIRS = {
    "test",
    "tests",
    "testdata",
    "fixtures",
    "fixture",
    "vendor",
    "node_modules",
    "target",
    ".git",
    "__pycache__",
}


def _source_shape(tool_dir: pathlib.Path) -> dict:
    if not tool_dir.is_dir():
        return {"class": "missing-override", "source_files": -1, "sample": []}
    srcs = []
    for root, dirs, files in __import__("os").walk(tool_dir):
        dirs[:] = [d for d in dirs if d.lower() not in _PRUNE_DIRS]
        for f in files:
            if f.lower().endswith(_SRC_EXTS):
                p = pathlib.Path(root) / f
                try:
                    srcs.append(str(p.relative_to(tool_dir)).replace("\\", "/"))
                except ValueError:
                    srcs.append(str(p))
    klass = "reimpl-candidate" if len(srcs) <= 8 else "upstream-source-prohibited"
    return {"class": klass, "source_files": len(srcs), "sample": srcs[:8]}


def _load_spec(full: str, short: str) -> dict | None:
    for name in (full, short):
        p = PB / "specs" / f"{name}.json"
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            return {"path": str(p), "error": str(e)}
        examples = data.get("n_examples", 0) or 0
        tests = data.get("n_tests_total", 0) or 0
        return {
            "path": str(p),
            "language": data.get("language") or "",
            "n_tests_total": tests,
            "n_examples": examples,
            "n_with_exact_stdout": data.get("n_with_exact_stdout", 0),
            "coverage": round(examples / max(tests, 1), 3),
        }
    return None


def _load_reimpl_skill(short: str) -> dict | None:
    base = PB / "reimpl_skills"
    p = base / f"{short}.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"path": str(p), "error": str(e)}
    probes = base / f"{short}_probes.json"
    n_probes = 0
    if probes.exists():
        try:
            n_probes = len(json.loads(probes.read_text(encoding="utf-8")))
        except Exception:
            n_probes = -1
    return {
        "path": str(p),
        "updated": data.get("updated", ""),
        "best_official": data.get("best_official"),
        "best_official_total": data.get("best_official_total"),
        "last_local": data.get("last_local", ""),
        "hard_behaviors": (data.get("hard_behaviors") or [])[:20],
        "probe_count": n_probes,
    }


def _pattern_applies(short_name: str, applies_to: list) -> bool:
    """Return whether a class-pattern applies to this tool.

    Most patterns list concrete tool names, but corpus-wide safety patterns need
    a global marker so every tool sees them during consultation.
    """
    sn = short_name.lower()
    for item in applies_to:
        raw = str(item).strip().lower()
        if raw in {"*", "all", "__all__"}:
            return True
        if sn == _short(raw) or sn in raw:
            return True
    return False


def _merge_knowledge(dst: dict, patch: dict) -> dict:
    for key, val in patch.items():
        if key == "_doc":
            continue
        if isinstance(val, dict) and isinstance(dst.get(key), dict):
            dst[key].update(val)
        else:
            dst[key] = val
    return dst


def _loads_knowledge_json(text: str) -> dict:
    """Load build_knowledge.json, tolerating one known corpus hygiene failure.

    Some box syncs have a valid JSON object followed by stray concatenated text.
    A strict json.loads crash makes every corpus consult fail. Salvage the first
    object and preserve a warning so the root cause can be folded back instead
    of silently ignored.
    """
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError as e:
        dec = json.JSONDecoder()
        obj, end = dec.raw_decode(text)
        if not isinstance(obj, dict):
            raise
        if text[end:].strip():
            obj["_load_warning"] = (
                f"build_knowledge.json had trailing data after byte {end}: {e.msg}"
            )
            return obj
        raise


def _load_build_knowledge() -> dict:
    kb = _loads_knowledge_json((PB / "build_knowledge.json").read_text(encoding="utf-8"))
    patch_dir = PB / "build_knowledge_patches"
    if patch_dir.is_dir():
        for patch_path in sorted(patch_dir.glob("*.json")):
            try:
                patch = json.loads(patch_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(patch, dict):
                _merge_knowledge(kb, patch)
    return kb


def ask_corpus(slug: str) -> dict:
    kb = _load_build_knowledge()
    sn = _short(slug)
    import determinex_pb_autofix as AF

    full = AF._resolve_full_slug(slug) or slug
    sn = _short(full)
    shape = _source_shape(PB / "per_tool_overrides" / full)
    spec = _load_spec(full, sn)
    skill = _load_reimpl_skill(sn)
    out: dict = {
        "slug": full,
        "short": sn,
        "per_tool": None,
        "class_patterns": [],
        "adjudication": None,
        "prescription": [],
        "source_shape": shape,
        "spec": spec,
        "reimpl_skill": skill,
        "recommended_engine": "",
    }

    # 1) per_tool entry (exact tool knowledge)
    per = kb.get("per_tool", {})
    for k, v in per.items():
        if _short(k) == sn or k == slug:
            out["per_tool"] = {k: v}
            break

    # 2) class_patterns this tool is explicitly listed in
    for cls, body in kb.get("class_patterns", {}).items():
        if not isinstance(body, dict):
            continue
        applies = body.get("applies_to", [])
        if _pattern_applies(sn, applies):
            out["class_patterns"].append(
                {
                    "class": cls,
                    "detect": body.get("detect", ""),
                    "fix": body.get("fix", ""),
                    "generalized_in": body.get("generalized_in", ""),
                }
            )

    # 3) adjudicator over the freshest eval_report (per-failure prescribed technique)
    rep = AF._find_eval_report(full, None)
    if rep and rep.exists():
        try:
            from determinex_adjudicator import Verdict, _base_nodeid, adjudicate_eval_report

            adjs = adjudicate_eval_report(rep, "", "")
            seen = {}
            for a in adjs:
                seen.setdefault(_base_nodeid(a.failure.test_id), a)
            uniq = list(seen.values())
            byv = collections.Counter(a.verdict.value for a in uniq)
            strat = collections.Counter(a.strategy for a in uniq)
            data = json.loads(rep.read_text(encoding="utf-8", errors="replace"))
            tr = data.get("test_results", [])
            cc = collections.Counter(r.get("status") for r in tr)
            out["adjudication"] = {
                "report": str(rep),
                "score": f"{cc.get('passed', 0)}/{len(tr)}",
                "verdicts": dict(byv),
                "top_strategies": dict(strat.most_common(6)),
                "ceiling_units": byv.get(Verdict.IMPOSSIBLE.value, 0),
                "reopenable_units": sum(n for v, n in byv.items() if v != Verdict.IMPOSSIBLE.value),
            }
        except Exception as e:
            out["adjudication"] = {"error": str(e)}

    # 4) synthesize a prescription (what to DO, corpus-ordered)
    rx = []
    if shape["class"] == "upstream-source-prohibited":
        out["recommended_engine"] = "native-reimpl-loop"
        lang = (spec or {}).get("language") or "<native-lang>"
        rx.append(
            "STOP: current override is upstream-source-prohibited; do not eval/autofix/pin it."
        )
        rx.append(
            f"Run reimpl path: determinex_io_extractor/spec -> determinex_local_oracle -> "
            f"determinex_reimpl_drive {full} --lang {lang} --models local/<available> --iters N; "
            "promote only a few-file source-only candidate."
        )
    elif skill:
        out["recommended_engine"] = "reimpl-skill-oracle"
        rx.append(
            f"Use reimpl skill {skill.get('path')} with {skill.get('probe_count')} saved probes; "
            "run determinex_local_oracle before official eval."
        )
    elif spec:
        out["recommended_engine"] = "spec-local-oracle"
        rx.append(
            f"Use harvested spec {spec.get('path')} ({spec.get('n_examples')}/"
            f"{spec.get('n_tests_total')} examples, coverage={spec.get('coverage')}); "
            "validate candidate with determinex_local_oracle before official eval."
        )
    else:
        out["recommended_engine"] = "extract-spec-first"
        rx.append(
            "No harvested spec/reimpl skill found; run determinex_io_extractor/pb_bulk_spec first."
        )

    if out["adjudication"] and out["adjudication"].get("reopenable_units", 0) > 0:
        for strat, n in out["adjudication"].get("top_strategies", {}).items():
            rx.append(f"adjudicator: {n}x {strat} (must be local-oracle gated before re-eval)")
    for c in out["class_patterns"]:
        rx.append(f"class[{c['class']}]: {c['fix'][:80]}")
    if out["per_tool"]:
        pt = list(out["per_tool"].values())[0]
        rx.append("per_tool: " + (pt.get("fix") or pt.get("note") or pt.get("status", ""))[:100])
    out["prescription"] = rx or ["no corpus signal -> adjudicate fresh eval / build_probe"]
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    ans = ask_corpus(sys.argv[1])
    shape = ans.get("source_shape") or {}
    print(
        f"source_shape: {shape.get('class')} src={shape.get('source_files')} "
        f"sample={shape.get('sample', [])[:3]}"
    )
    print("recommended_engine:", ans.get("recommended_engine", ""))
    if ans.get("spec"):
        s = ans["spec"]
        print(
            f"spec: {s.get('path')} examples={s.get('n_examples')}/"
            f"{s.get('n_tests_total')} coverage={s.get('coverage')} lang={s.get('language')}"
        )
    if ans.get("reimpl_skill"):
        sk = ans["reimpl_skill"]
        print(
            f"reimpl_skill: {sk.get('path')} probes={sk.get('probe_count')} "
            f"best={sk.get('best_official')}/{sk.get('best_official_total')} "
            f"last_local={sk.get('last_local')}"
        )
    print(f"\n=== CORPUS SAYS — {ans['slug']} ({ans['short']}) ===")
    if ans["adjudication"]:
        a = ans["adjudication"]
        print(
            f"score {a.get('score', '?')} | verdicts {a.get('verdicts', {})} | "
            f"ceiling={a.get('ceiling_units', 0)} reopenable={a.get('reopenable_units', 0)}"
        )
    print(
        "per_tool:",
        "yes" if ans["per_tool"] else "none",
        "| class_patterns:",
        [c["class"] for c in ans["class_patterns"]],
    )
    print("\nPRESCRIPTION (corpus-ordered):")
    for r in ans["prescription"]:
        print("  -", r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
