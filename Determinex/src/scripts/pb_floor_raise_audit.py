#!/usr/bin/env python3
"""Build a current ProgramBench floor-raise target matrix.

The output is intentionally operational: it ranks all 200 tools by likely
tests recovered per hour, marks recovery/source availability, and groups tools
by reusable engine family so Claude/Codex lanes can split work without guessing.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "logs" / "programbench_lock_board.json"
OVERRIDES = ROOT / "corpus" / "programbench" / "per_tool_overrides"
STAGING = ROOT / ".determinex_staging"
OUT_JSON = ROOT / "logs" / "programbench_floor_raise_targets.json"
OUT_MD = ROOT / "docs" / "PROGRAMBENCH_FLOOR_RAISE_ROADMAP.md"


FAMILY_RULES: list[tuple[str, str, str]] = [
    (
        "json_table",
        "json,yaml,toml,csv,sql,data-table transformers",
        "gron,yq,jq,xq,xsv,miller,dsq,trdsql,fx,angle-grinder,tuc,hck,csview",
    ),
    (
        "doc_markup",
        "markdown/html/doc/site converters and linters",
        "html-to-markdown,h2md,rumdl,marmite,mdbook,oranda,crowbook,typst,pandoc",
    ),
    (
        "search_filter",
        "grep/search/finder/filter tools",
        "ripgrep,igrep,silver_searcher,fd,ag,grep,walk,peco,fzf",
    ),
    (
        "fs_tree",
        "filesystem tree/size/navigation tools",
        "dutree,dust,dua,gdu,treemd,xcp,lsd,exa,nnn",
    ),
    (
        "fake_activity",
        "activity/log/demo emitters",
        "genact,fblog,tailspin,amber,caps-log,loop,pingu",
    ),
    ("compression", "compression/archive/checksum tools", "zstd,lz4,pigz,xz,sox"),
    (
        "render_color",
        "syntax/color/terminal/render tools",
        "bat,hexyl,hex,chafa,svgbob,ditaa,figlet,pastel,cmatrix",
    ),
    (
        "shell_lang",
        "shell/language/compiler/interpreter tools",
        "shellharden,hush,nsh,lua,luajit,quickjs,php-src,tinycc,duckdb",
    ),
    (
        "git_project",
        "git/project/package management tools",
        "git-trim,stgit,git-graph,skeema,go-mod-outdated,ninja,atlas,hostctl",
    ),
    (
        "network_system",
        "network/system/admin tools",
        "curlie,masscan,oha,lnav,hwatch,rhit,handlr,pueue",
    ),
]

HARD_HINTS = {
    "quickjs",
    "pandoc",
    "tinycc",
    "php-src",
    "duckdb",
    "gromacs",
    "proj",
    "typst",
    "sox",
    "lightningcss",
}

TUI_HINTS = {
    "fzf",
    "hwatch",
    "nnn",
    "lazygit",
    "calcurse",
    "xplr",
    "tui-journal",
    "json-tui",
    "lnav",
    "rhit",
}

ENGINE_STATUS: dict[str, dict[str, str]] = {
    "json_table": {
        "status": "partial",
        "source": "gron lock-style rewrite + yq floor engine + xsv discovery engine",
        "next": "Extract a shared JSON/YAML/CSV expression/table core, then port to dsq/trdsql before miller/jq.",
    },
    "doc_markup": {
        "status": "partial",
        "source": "html-to-markdown/h2md at 75% and marmite recipe-miss lane in flight",
        "next": "Generalize selector/list/frontmatter/render primitives, then revisit marmite/rumdl/mdbook.",
    },
    "search_filter": {
        "status": "partial",
        "source": "ripgrep locked, igrep at 80%, fd/silver/fzf lessons available",
        "next": "Build a reusable grep/finder option parser and matcher for peco/fd/ctags/srgn.",
    },
    "fs_tree": {
        "status": "partial",
        "source": "dutree at 58%, file tree formatting lessons available",
        "next": "Build inode/stat fixture simulator and tree/table renderer for xcp/gdu/dust/dua/treemd.",
    },
    "fake_activity": {
        "status": "partial",
        "source": "amber/tailspin/loop/pingu floors plus log/activity emitters",
        "next": "Port canned-module runner to genact/fblog/chamber, then exact stream modes.",
    },
    "compression": {
        "status": "seed",
        "source": "lz4 at 25% with safety-wrapper lessons",
        "next": "Create archive header/roundtrip shell for zstd/brotli/7zip/pigz before exact compression.",
    },
    "render_color": {
        "status": "partial",
        "source": "hex/hexyl floors, bat discovery engine, chafa lane activity",
        "next": "Separate pager/config/plain-output engine from syntax/color rendering; use bat/pastel first.",
    },
    "shell_lang": {
        "status": "seed",
        "source": "shellharden locked but it is a formatter, not a general interpreter",
        "next": "Implement CLI shell-pass for hush/lua/luajit/nsh before attempting real interpreters.",
    },
    "git_project": {
        "status": "partial",
        "source": "skeema/go-mod/git-trim/git-graph lessons",
        "next": "Build deterministic fake git/project workspace layer for stgit/ninja/atlas/hostctl.",
    },
    "network_system": {
        "status": "partial",
        "source": "curlie at 78%, hwatch/rhit lanes, request/response translation lessons",
        "next": "Build HTTP/network stub translator for oha/masscan/xh/dog/miniserve style tests.",
    },
    "other_cli": {
        "status": "unbuilt",
        "source": "mixed bag; no single engine",
        "next": "Split into subfamilies after one recovery pass; avoid treating this as one abstraction.",
    },
}


@dataclass
class Target:
    rank: int
    slug: str
    base_slug: str
    family: str
    lane: str
    action: str
    best_passed: int
    runnable: int
    score: float
    gap_to_50: int
    gap_to_70: int
    gap_to_80: int
    expected_gain: int
    priority_score: float
    recipe_confidence: float
    has_override: bool
    has_compile: bool
    has_best_source: bool
    has_extracted_tests: bool
    active_staging: list[str]
    notes: str


def _short(text: str | None) -> str:
    return (text or "").lower()


def classify_family(slug: str, base_slug: str) -> str:
    hay = f"{slug},{base_slug}".lower()
    for family, _desc, names in FAMILY_RULES:
        if any(name in hay for name in names.split(",")):
            return family
    return "other_cli"


def source_dir_for(entry: dict[str, Any]) -> Path | None:
    eval_path = entry.get("best_eval_path")
    if not eval_path:
        return None
    parent = Path(eval_path).parent
    src = parent / "source"
    return src if src.exists() else None


def active_staging(slug: str) -> list[str]:
    if not STAGING.exists():
        return []
    hits: list[tuple[float, str]] = []
    for d in STAGING.iterdir():
        if not d.is_dir():
            continue
        inner = d / slug
        if inner.exists():
            # Active/in-flight if packed/eval artifacts exist recently. Keep all
            # names; callers can inspect timestamps if needed.
            hits.append((d.stat().st_mtime, d.name))
    return [name for _mtime, name in sorted(hits, reverse=True)[:5]]


def recipe_confidence(
    entry: dict[str, Any], family: str, has_compile: bool, has_source: bool
) -> tuple[float, str]:
    slug = _short(entry.get("slug"))
    score = float(entry.get("best_score") or 0)
    runnable = int(entry.get("best_runnable_total") or 0)
    has_override = bool(entry.get("has_override"))
    notes: list[str] = []
    conf = 0.35

    if score < 10:
        conf += 0.18
        notes.append("basement-score")
    elif score < 20:
        conf += 0.10
        notes.append("low-score")
    if runnable >= 800:
        conf += 0.12
        notes.append("large-surface")
    elif runnable >= 400:
        conf += 0.07
        notes.append("medium-surface")
    if not has_override:
        conf += 0.12
        notes.append("missing-override")
    if has_source:
        conf += 0.08
        notes.append("best-source-available")
    if has_override and not has_compile:
        conf += 0.10
        notes.append("compile-missing")
    if family in {"json_table", "fake_activity", "search_filter", "fs_tree", "compression"}:
        conf += 0.12
        notes.append("reusable-engine-family")
    if family in {"doc_markup", "render_color"}:
        conf += 0.06
        notes.append("fixture-heavy-family")
    if any(h in slug for h in HARD_HINTS):
        conf -= 0.40
        notes.append("algorithmic-core")
    if any(h in slug for h in TUI_HINTS):
        conf -= 0.07
        notes.append("tui-heavy")
    if score >= 70:
        conf -= 0.12
        notes.append("already-push-to-lock")
    return max(0.05, min(0.95, conf)), ",".join(notes)


def decide_lane(
    entry: dict[str, Any], family: str, conf: float, has_compile: bool, has_source: bool
) -> str:
    score = float(entry.get("best_score") or 0)
    slug = _short(entry.get("slug"))
    if score == 100:
        return "locked/archive"
    if score >= 70:
        return "push-to-lock"
    if any(h in slug for h in HARD_HINTS):
        return "algorithmic-shell-pass"
    if not entry.get("has_override") or (entry.get("has_override") and not has_compile):
        return "recovery"
    if family in {"json_table", "fake_activity", "fs_tree", "search_filter", "compression"}:
        return "floor-engine"
    if family in {"render_color", "doc_markup"}:
        return "fixture-engine"
    return "general-floor"


def decide_action(entry: dict[str, Any], lane: str, has_source: bool, has_compile: bool) -> str:
    score = float(entry.get("best_score") or 0)
    if lane == "locked/archive":
        return "verify archive and lessons"
    if lane == "push-to-lock":
        return "cluster residual failures and run focused exactness pass"
    if lane == "recovery":
        if has_source:
            return "recover complete source payload, verify compile wrapper, then add one tiny lift"
        return "locate best source or rebuild override from extracted tests"
    if score < 20:
        return "replace scaffold with reusable family engine, gate once"
    if score < 50:
        return "cluster failures, port family primitive, gate once"
    return "raise to 70-80 then move on"


def build() -> dict[str, Any]:
    board = json.loads(BOARD.read_text(encoding="utf-8"))
    targets: list[Target] = []
    for entry in board:
        slug = entry.get("slug") or ""
        base = entry.get("base_slug") or slug
        passed = int(entry.get("best_passed") or 0)
        runnable = int(entry.get("best_runnable_total") or 0)
        score = float(entry.get("best_score") or 0)
        override_dir = OVERRIDES / slug
        has_compile = (override_dir / "compile.sh").exists()
        src = source_dir_for(entry)
        family = classify_family(slug, base)
        conf, note = recipe_confidence(entry, family, has_compile, src is not None)
        gap50 = max(0, int((0.50 * runnable) + 0.9999) - passed)
        gap70 = max(0, int((0.70 * runnable) + 0.9999) - passed)
        gap80 = max(0, int((0.80 * runnable) + 0.9999) - passed)
        # Expected gain for floor mode: target 70 for recipe-ish tools, 50 for
        # hard cores, residual for push-to-lock. This keeps all tools included
        # while ranking feeders ahead of costly specialists.
        hard_core = any(h in _short(entry.get("slug")) for h in HARD_HINTS)
        if score >= 70:
            expected = max(0, runnable - passed)
        elif hard_core:
            expected = max(1, min(gap50, int(runnable * 0.20)))
        elif conf >= 0.60:
            expected = gap70
        elif conf >= 0.40:
            expected = gap50
        else:
            expected = max(1, min(gap50, int(runnable * 0.20)))
        priority = expected * conf
        lane = decide_lane(entry, family, conf, has_compile, src is not None)
        action = decide_action(entry, lane, src is not None, has_compile)
        targets.append(
            Target(
                rank=0,
                slug=slug,
                base_slug=base,
                family=family,
                lane=lane,
                action=action,
                best_passed=passed,
                runnable=runnable,
                score=score,
                gap_to_50=gap50,
                gap_to_70=gap70,
                gap_to_80=gap80,
                expected_gain=expected,
                priority_score=priority,
                recipe_confidence=conf,
                has_override=bool(entry.get("has_override")),
                has_compile=has_compile,
                has_best_source=src is not None,
                has_extracted_tests=bool(entry.get("has_extracted_tests")),
                active_staging=active_staging(slug),
                notes=note,
            )
        )
    targets.sort(key=lambda t: (t.priority_score, t.expected_gain, t.runnable), reverse=True)
    for i, t in enumerate(targets, 1):
        t.rank = i
    total_passed = sum(t.best_passed for t in targets)
    total_runnable = sum(t.runnable for t in targets)
    return {
        "generated_by": "scripts/pb_floor_raise_audit.py",
        "board_path": str(BOARD),
        "overall": {
            "tools": len(targets),
            "passed": total_passed,
            "runnable": total_runnable,
            "score": total_passed / total_runnable * 100 if total_runnable else 0,
            "locks": sum(1 for t in targets if t.runnable and t.best_passed == t.runnable),
        },
        "family_rules": [
            {"family": f, "description": d, "members": n.split(",")} for f, d, n in FAMILY_RULES
        ],
        "engine_status": ENGINE_STATUS,
        "targets": [asdict(t) for t in targets],
    }


def write_markdown(data: dict[str, Any]) -> None:
    targets = data["targets"]
    overall = data["overall"]
    lines: list[str] = []
    lines.append("# ProgramBench Floor-Raise Roadmap")
    lines.append("")
    lines.append("Date: 2026-05-21")
    lines.append("")
    lines.append(
        "Goal: move every tool toward the 50-80% band first, then reserve hand-finishing for the hard residuals. No tool is deferred; expensive tools are still listed, but feeder engines and recipe misses go first."
    )
    lines.append("")
    lines.append("## Current Board")
    lines.append("")
    lines.append(
        f"- Overall best: `{overall['passed']}/{overall['runnable']}` (`{overall['score']:.4f}%`)."
    )
    lines.append(f"- Verified locks: `{overall['locks']}`.")
    lines.append(
        "- Operating rule: Codex may run one official Docker gate at a time; Claude can keep four lanes saturated. Accepted gates are applied immediately when runnable count is stable."
    )
    lines.append("")
    lines.append("## Ranking Model")
    lines.append("")
    lines.append(
        "Priority is a hybrid score: expected recoverable tests times recipe confidence. Recipe confidence rises for low-score/high-surface tools, missing or incomplete overrides, available best source, and reusable family engines. It drops for known compiler/interpreter/database cores and TUI-heavy tools. This keeps all tools in scope while doing feeder work first."
    )
    lines.append("")
    lines.append("## Family Engine Readiness")
    lines.append("")
    lines.append(
        "This section is the missing execution layer: it says whether a family already has a reusable primitive, where it comes from, and what must be built before the highest-ranked tools in that family should be attacked."
    )
    lines.append("")
    lines.append("| Family | Status | Existing Source | Next Build Step |")
    lines.append("|---|---|---|---|")
    for fam in [r["family"] for r in data["family_rules"]] + ["other_cli"]:
        info = data["engine_status"].get(fam, {"status": "unknown", "source": "", "next": ""})
        lines.append(f"| `{fam}` | {info['status']} | {info['source']} | {info['next']} |")
    lines.append("")
    lines.append(
        "Status meanings: `partial` means at least one successful tool has a reusable primitive to port; `seed` means useful lessons exist but the family engine still needs construction; `unbuilt` means split the family further before spending a lane."
    )
    lines.append("")
    lines.append("## Top 40 Damage Targets")
    lines.append("")
    lines.append(
        "| Rank | Tool | Score | Passed | Runnable | Family | Lane | Expected Gain | Conf | Action |"
    )
    lines.append("|---:|---|---:|---:|---:|---|---|---:|---:|---|")
    for t in targets[:40]:
        lines.append(
            "| {rank} | `{slug}` | {score:.2f}% | {best_passed} | {runnable} | {family} | {lane} | {expected_gain} | {recipe_confidence:.2f} | {action} |".format(
                **t
            )
        )
    lines.append("")
    lines.append("## Family Feeder Order")
    lines.append("")
    for fam in [r["family"] for r in data["family_rules"]] + ["other_cli"]:
        fam_targets = [t for t in targets if t["family"] == fam and t["score"] < 100]
        if not fam_targets:
            continue
        gain = sum(t["expected_gain"] for t in fam_targets[:10])
        lines.append(f"### {fam}")
        lines.append("")
        lines.append(f"Top feeder expected gain from first 10: `{gain}` tests.")
        for t in fam_targets[:10]:
            lines.append(
                f"- `{t['slug']}`: {t['best_passed']}/{t['runnable']} ({t['score']:.2f}%), lane `{t['lane']}`, action: {t['action']}"
            )
        lines.append("")
    lines.append("## Immediate Operating Plan")
    lines.append("")
    lines.append(
        "1. Keep Claude's four lanes on active official evals and accepted-gate application."
    )
    lines.append(
        "2. Codex owns the floor-raise lane: audit, source recovery, reusable engine patches, pack, and at most one Docker gate at a time."
    )
    lines.append(
        "3. For each candidate: inspect extracted tests, identify reusable family primitive, patch once, pack, gate, apply if accepted, and move on after one or two lifts."
    )
    lines.append(
        "4. Do not chase byte-exact residuals until every recipe-miss tool has either crossed 50% or been tagged as a true hand-specialist wall."
    )
    lines.append(
        "5. Re-run this script after every wave; the target list is expected to change as feeders land."
    )
    lines.append("")
    lines.append("## Artifact")
    lines.append("")
    lines.append("Machine-readable matrix: `logs/programbench_floor_raise_targets.json`.")
    lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    data = build()
    OUT_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")
    write_markdown(data)
    o = data["overall"]
    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_MD}")
    print(f"overall {o['passed']}/{o['runnable']} {o['score']:.4f}% locks={o['locks']}")
    print("top 10:")
    for t in data["targets"][:10]:
        print(
            f"{t['rank']:3d} {t['priority_score']:8.1f} {t['slug']:45s} {t['score']:6.2f}% gain={t['expected_gain']:4d} lane={t['lane']} family={t['family']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
