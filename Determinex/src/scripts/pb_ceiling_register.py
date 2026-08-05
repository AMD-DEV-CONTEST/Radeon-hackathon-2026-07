"""Generate corpus/programbench/ceiling_register.json — the per-tool honest-ceiling ledger.

The register answers, for every tool that cannot (or may not) reach a strict
official lock (passed==total, 0 skipped, 0 not_run): what is the proven max,
why, and is the gap recoverable.

Skip classification (from eval-report skip reasons):
  env_conditional     — container is missing a toolchain/lib/command; recoverable
                        via compile.sh provisioning (e.g. "rust is not available",
                        "zstd not available", "jsonschema not installed", man).
  dependency_cascade  — pytest-dependency skipped because its parent failed or ran
                        on another xdist worker; recovers when parent passes.
  root_container      — test needs a non-root user; PB containers run as root.
                        Structurally hard (sharkdp__fd ceiling class).
  hard_upstream       — unconditional @pytest.mark.skip written into the eval
                        tests ("Too slow", "gold-env-limitation", "Known bug",
                        external/live tests, "behavior varies"). Reference
                        binary skips these too: reference-parity ceiling.
  unverified          — no reason string recoverable from the eval report;
                        needs a per-tool probe before the ceiling is final.

Re-run after every wave: python scripts/pb_ceiling_register.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL_INDEX = os.path.join(ROOT, "corpus", "programbench", "eval_index.json")
OUT = os.path.join(ROOT, "corpus", "programbench", "ceiling_register.json")

# Reason-substring -> class. First match wins; order matters.
REASON_RULES: list[tuple[str, str]] = [
    ("pytest_dependency", "dependency_cascade"),
    ("depends on", "dependency_cascade"),
    ("not available", "env_conditional"),
    ("not installed", "env_conditional"),
    ("not fully functional on this system", "env_conditional"),
    ("man command", "env_conditional"),
    ("shared library not built", "env_conditional"),
    ("compilation not available", "env_conditional"),
    ("non-root", "root_container"),
    ("as root", "root_container"),
    ("root container", "root_container"),
    ("root bypasses", "root_container"),
    ("running as root", "root_container"),
    ("gold-env-limitation", "hard_upstream"),
    ("known bug", "hard_upstream"),
    ("too slow", "hard_upstream"),
    ("takes too long", "hard_upstream"),
    ("external test", "hard_upstream"),
    ("live external", "hard_upstream"),
    ("behavior varies", "hard_upstream"),
    ("incompatible flags", "hard_upstream"),
    ("no-regex builds", "hard_upstream"),
    ("may crash worker", "hard_upstream"),
    ("wait for proper colorization", "hard_upstream"),
    ("toolchain workaround failed", "hard_upstream"),
    ("doesn't support", "hard_upstream"),
]

# Tools whose impossibility is established by per-tool structural analysis,
# not by skip markers. Ceilings quoted from the audited per-tool findings
# (CLAUDE.md / docs/audits/pb_measurement_audit_2026_06_06.md era notes).
CEILING_CONFIRMED: dict[str, dict] = {
    "dalance__amber": {
        "ceiling": "~587/600 (97.8%)",
        "blocker": "Camp A branches assert rc=1 on no-TTY pipe; Camp B asserts rc=0+file-modify "
        "for the same invocation. No single binary satisfies both.",
    },
    "sharkdp__hexyl": {
        "ceiling": "~940/946 (99.37%)",
        "blocker": "--panels=1 row-width conflict with passing golden snapshot; decimal/octal "
        "zero-pad regex mismatch ({i:03} vs \\b10\\b).",
    },
    "sharkdp__fd": {
        "ceiling": "~1263/1271 (99.37%)",
        "blocker": "Root user makes all files executable (defeats chmod tests); subprocess "
        "FileNotFoundError on deleted cwd; \\Ac literal in Rust regex.",
    },
    "johanneskaufmann__html-to-markdown": {
        "ceiling": "971/974 (99.69%)",
        "blocker": "Three branches assert conflicting --version strings for identical "
        "invocations. 4 independent evals all land at 971/974.",
    },
    "doxygen__doxygen": {
        "ceiling": "~250/394 (63.6%)",
        "blocker": "tests.json for 2 of 3 branches carries duplicate test IDs with both "
        "eval.tests. and tests. prefixes; JUnit XML only ever emits one prefix — "
        "the other half is permanently not_run.",
    },
    "orf__gping": {
        "ceiling": "649/655 (99.08%)",
        "blocker": "2 ping-missing ENXIO failures irreconcilable with ping-present branches; "
        "4 upstream skips.",
    },
    "kyoh86__richgo": {
        "ceiling": "~787/823 (95.6%)",
        "blocker": "@go_test phantom test IDs in tests.json never appear in JUnit XML.",
    },
}


def classify(reason: str) -> str:
    r = reason.lower()
    for pat, cls in REASON_RULES:
        if pat in r:
            return cls
    return "unverified" if not r.strip() else "hard_upstream"


def extract_skips(report_path: str) -> list[dict]:
    try:
        rep = json.load(open(report_path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    trs = rep.get("test_results")
    if trs is None and isinstance(rep, dict):
        for v in rep.values():
            if isinstance(v, dict) and "test_results" in v:
                trs = v["test_results"]
                break
    if trs is None:
        return []
    items = trs.items() if isinstance(trs, dict) else enumerate(trs)
    out = []
    for k, v in items:
        if not isinstance(v, dict):
            continue
        if str(v.get("status", "")).lower() not in ("skipped", "skip"):
            continue
        reason = ""
        ex = v.get("extra") or {}
        if isinstance(ex, dict):
            reason = (ex.get("text") or "").strip()
        # strip "path:line: " prefix pytest puts in front of the reason
        reason = re.sub(r"^\S+:\d+:\s*", "", reason.replace("\n", " "))[:200]
        out.append({"test": str(v.get("name") or k), "reason": reason, "class": classify(reason)})
    return out


def main() -> int:
    ei = json.load(open(EVAL_INDEX, encoding="utf-8"))
    register: dict = {
        "generated": date.today().isoformat(),
        "generator": "scripts/pb_ceiling_register.py",
        "metric": "official ProgramBench: score = passed / total(incl. not_run, skipped)",
        "ledger_definitions": {
            "strict_lock": "passed==total, 0 skipped, 0 not_run, no eval_override, guard-clean",
            "reference_parity": "every non-passing test is a hard_upstream/root_container skip "
            "the reference binary also cannot pass; failed==0, not_run==0",
            "ceiling_confirmed": "structurally impossible; proof recorded per tool",
        },
        "tools": {},
    }

    summary = Counter()
    for e in ei:
        slug = e["slug"]
        sk = e.get("official_skipped") or 0
        entry = None
        if slug in CEILING_CONFIRMED:
            c = CEILING_CONFIRMED[slug]
            entry = {
                "ledger": "ceiling_confirmed",
                "ceiling": c["ceiling"],
                "blocker": c["blocker"],
                "strict_eligible": False,
            }
        elif sk > 0:
            skips = extract_skips(e.get("eval_report_path") or "")
            classes = Counter(s["class"] for s in skips)
            if len(skips) != sk:
                classes["unverified"] += sk - len(skips)
            recoverable = classes.get("env_conditional", 0) + classes.get("dependency_cascade", 0)
            hard = classes.get("hard_upstream", 0) + classes.get("root_container", 0)
            entry = {
                "ledger": "strict_candidate_after_env_fix"
                if hard == 0 and classes.get("unverified", 0) == 0
                else (
                    "reference_parity_ceiling"
                    if recoverable == 0 and classes.get("unverified", 0) == 0
                    else "mixed_needs_probe"
                ),
                "official": f"{e.get('official_passed')}/{e.get('official_total')}",
                "skip_classes": dict(classes),
                "skips": skips,
                "strict_eligible": hard == 0,
                "parity_ceiling_if_hard_stand": f"{(e.get('official_total') or 0) - hard}"
                f"/{e.get('official_total')}",
            }
        if entry:
            entry["status_at_generation"] = e.get("status")
            register["tools"][slug] = entry
            summary[entry["ledger"]] += 1

    register["summary"] = dict(summary)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(register, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {OUT}")
    print("summary:", dict(summary))
    for slug, t in register["tools"].items():
        if t["ledger"] != "ceiling_confirmed":
            print(f"  {slug:38} {t['ledger']:32} classes={t.get('skip_classes')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
