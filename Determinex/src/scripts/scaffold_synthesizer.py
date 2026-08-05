#!/usr/bin/env python3
"""scaffold_synthesizer.py - take each tool's inspection report + (optionally)
its tests, and auto-select/generate the highest-yield scaffold for it.

Flow:
  inspect (already done)  →  THIS  →  generate scaffold  →  eval  →  measure

Output:
  logs/mass_run_v2/scaffold_plan.json   - one entry per tool with:
    - chosen_family
    - chosen_subtype (or null)
    - reason
    - expected_ceiling (rough estimate)
    - needs_new_subtype (bool — flags subtypes that don't exist yet)
    - actions: list of {generate | manual_subtype_needed}

Run order:
  1. python scripts/programbench_inspect_tool.py --all
  2. python scripts/scaffold_synthesizer.py
  3. python scripts/scaffold_synthesizer.py --execute  (regen scaffolds)
  4. queue + eval via pool
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSPECT = ROOT / "logs" / "mass_run_v2" / "inspection_report.json"
PLAN_OUT = ROOT / "logs" / "mass_run_v2" / "scaffold_plan.json"
MINER_FILE = ROOT / "logs" / "mass_run_v2" / "argv_miner.json"
ORACLE_FILE = ROOT / "logs" / "mass_run_v2" / "oracle_memos.json"
FIXTURE_FILE = ROOT / "logs" / "mass_run_v2" / "fixture_bank.json"
PB_ROOT = Path("T:/determinex-programbench")

sys.path.insert(0, str(ROOT / "corpus" / "programbench" / "families"))
try:
    from generator_lib import (
        FAMILY_SPECS,
        INSTANCE_SUBTYPE_OVERRIDES,
        ProbeSummary,
        load_probe,
        write_scaffold,
    )

    EXISTING_FAMILIES = set(FAMILY_SPECS.keys())
except Exception as e:
    print(f"WARN: could not import generator_lib ({e})")
    EXISTING_FAMILIES = set()
    INSTANCE_SUBTYPE_OVERRIDES = {}
    FAMILY_SPECS = {}
    write_scaffold = None  # type: ignore
    load_probe = None  # type: ignore
    ProbeSummary = None  # type: ignore


# Decision rules: map inspection signature → scaffold choice
# Order matters: first match wins
DECISION_RULES = [
    # (predicate, family_or_subtype, reason, expected_ceiling, needs_new)
    (
        lambda r: r.get("fixtures_total", {}).get("tmux", 0) > 0,
        "tui_pexpect",
        "tests drive via tmux — need PTY scaffold",
        50,
        True,
    ),
    (
        lambda r: r.get("fixtures_total", {}).get("pty", 0) > 0,
        "tui_pexpect",
        "tests use pty — need PTY scaffold",
        50,
        True,
    ),
    (
        lambda r: r.get("fixtures_total", {}).get("network_server", 0) > 0,
        "network_http.fixture_server",
        "tests bind sockets — need network harness",
        40,
        True,
    ),
    (
        lambda r: "structured_output (json" in r.get("scaffold_hint", ""),
        "json_yaml_toml.structured_output_json",
        "tests parse JSON output",
        60,
        True,
    ),
    (
        lambda r: "structured_output (csv" in r.get("scaffold_hint", ""),
        "csv_table.structured_output_csv",
        "tests parse CSV output",
        60,
        True,
    ),
    (
        lambda r: r.get("fixtures_total", {}).get("git_init", 0) > 0,
        "git_wrappers",
        "tests init git repos",
        70,
        False,
    ),
    (
        lambda r: r.get("fixtures_total", {}).get("mkfifo", 0) > 0,
        "search_grep",
        "FIFO tests (walk_files fix already shipped)",
        50,
        False,
    ),
    # Golden-file heavy = byte-exact; ceiling is bounded
    (
        lambda r: r.get("verdict") == "golden_file_ceiling (per-tool byte-exact impl needed)",
        "golden_file_specialized",
        "byte-exact golden files; needs per-tool generator",
        40,
        True,
    ),
    # needs_specific_subtype with no specific signal → tag for manual review
    (
        lambda r: r.get("verdict") == "needs_specific_subtype",
        "MANUAL_REVIEW",
        "inspection flagged subtype need without clear pattern",
        30,
        True,
    ),
    # feasible_with_generic → use existing family selection from queue/state
    (
        lambda r: r.get("verdict") == "feasible_with_generic",
        "USE_EXISTING_FAMILY",
        "scaffold's existing family is appropriate",
        60,
        False,
    ),
]


def existing_family_for(inst: str) -> str | None:
    """Look up the family currently assigned to this tool from queue/audit data."""
    queue = ROOT / "logs" / "mass_run_v2" / "sprint4_eval_queue.json"
    if queue.is_file():
        try:
            data = json.loads(queue.read_text(encoding="utf-8"))
            for r in data.get("ranked", []):
                if r.get("instance") == inst:
                    fam = r.get("family")
                    if fam:
                        return fam
        except Exception:
            pass
    return None


def plan_for(inst: str, report: dict) -> dict:
    chosen, reason, ceiling, new_needed = None, "no rule matched", 20, False
    for pred, choice, why, c, n in DECISION_RULES:
        try:
            if pred(report):
                chosen, reason, ceiling, new_needed = choice, why, c, n
                break
        except Exception:
            continue

    # Resolve USE_EXISTING_FAMILY to the actual family name
    if chosen == "USE_EXISTING_FAMILY":
        ef = existing_family_for(inst)
        chosen = ef or "rust_cli"
        reason = f"feasible-with-generic; using existing family={chosen}"

    # Does the chosen family/subtype exist in our generator?
    exists = chosen in EXISTING_FAMILIES or chosen.split(".", 1)[0] in EXISTING_FAMILIES
    if not exists and "MANUAL_REVIEW" not in chosen:
        new_needed = True

    return {
        "instance": inst,
        "chosen": chosen,
        "reason": reason,
        "expected_ceiling": ceiling,
        "needs_new_subtype": new_needed,
        "scaffold_exists": exists,
        "test_count": report.get("test_count_total", 0),
        "risks": report.get("risks", []),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="actually regenerate scaffolds per plan")
    ap.add_argument(
        "--force-overwrite-locked",
        action="store_true",
        help="overwrite scaffolds for tools already scoring >=70% on eval.json",
    )
    args = ap.parse_args()

    if not INSPECT.is_file():
        print("ERROR: inspection_report.json missing; run programbench_inspect_tool.py --all first")
        return 1
    reports = json.loads(INSPECT.read_text(encoding="utf-8"))

    plans = []
    counts = Counter()
    new_subtypes_needed: dict[str, list[str]] = defaultdict(list)
    for inst, rep in reports.items():
        p = plan_for(inst, rep)
        plans.append(p)
        counts[p["chosen"]] += 1
        if p["needs_new_subtype"]:
            new_subtypes_needed[p["chosen"]].append(inst)

    PLAN_OUT.parent.mkdir(parents=True, exist_ok=True)
    PLAN_OUT.write_text(json.dumps(plans, indent=2), encoding="utf-8")
    print(f"plan written: {PLAN_OUT}")
    print()
    print("=== chosen scaffolds (by frequency) ===")
    for k, n in counts.most_common():
        marker = " [NEW SUBTYPE NEEDED]" if k in new_subtypes_needed else ""
        print(f"  {n:>4}  {k}{marker}")
    print()
    print(f"=== new subtypes that need building: {len(new_subtypes_needed)} ===")
    for subtype, tools in new_subtypes_needed.items():
        print(f"  {subtype}  ({len(tools)} tools)")
        for t in tools[:3]:
            print(f"    - {t}")
        if len(tools) > 3:
            print(f"    ... ({len(tools) - 3} more)")

    if args.execute:
        print()
        print("--execute: regenerating scaffolds...")
        if write_scaffold is None or load_probe is None:
            print("ERROR: generator_lib failed to import; cannot execute")
            return 1
        miner = {}
        if MINER_FILE.is_file():
            miner = json.loads(MINER_FILE.read_text(encoding="utf-8"))
            print(f"  miner: {len(miner)} tools loaded from {MINER_FILE.name}")
        else:
            print(f"  miner: no {MINER_FILE.name} found; scaffolds will be flag-only")
        oracle_data = {}
        if ORACLE_FILE.is_file():
            oracle_data = json.loads(ORACLE_FILE.read_text(encoding="utf-8"))
            total_memos = sum(len(v.get("memos", [])) for v in oracle_data.values())
            print(
                f"  oracle: {len(oracle_data)} tools, {total_memos} memos loaded from {ORACLE_FILE.name}"
            )
        else:
            print(f"  oracle: no {ORACLE_FILE.name} found; scaffolds will skip oracle lookup")
        fixture_data = {}
        if FIXTURE_FILE.is_file():
            fixture_data = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))
            total_files = sum(len(v) for v in fixture_data.values())
            print(
                f"  fixtures: {len(fixture_data)} tools, {total_files} files loaded from {FIXTURE_FILE.name}"
            )
        else:
            print(f"  fixtures: no {FIXTURE_FILE.name} found; scaffolds will skip fixture bank")

        # SAFETY GUARD: never overwrite a scaffold whose existing eval.json
        # shows the tool is already locked above LOCK_THRESHOLD. Hand-tuned
        # high-scoring scaffolds are PRECIOUS — losing one (e.g. igrep v2b at
        # 73%) takes hours to rebuild. Override with --force-overwrite-locked.
        LOCK_THRESHOLD = 70.0

        def existing_score(inst: str) -> float | None:
            import glob as _g

            cands = _g.glob(
                f"T:/determinex-programbench/determinex_pb_*_v*/{inst}/{inst}.eval.json"
            )
            best = None
            for ej in cands:
                try:
                    j = json.loads(Path(ej).read_text(encoding="utf-8"))
                    r = j.get("test_results") or []
                    if not r:
                        continue
                    passed = sum(1 for x in r if x.get("status") == "passed")
                    pct = 100.0 * passed / len(r)
                    if best is None or pct > best:
                        best = pct
                except Exception:
                    continue
            return best

        regen = skipped = protected = errors = 0
        for p in plans:
            inst = p["instance"]
            chosen = p["chosen"]
            # MANUAL_REVIEW tools still get a generic scaffold IF there's a
            # per-tool override (we can hand-tune them via the override mechanism).
            override_path = (
                ROOT / "corpus" / "programbench" / "per_tool_overrides" / inst / "main.py"
            )
            if chosen == "MANUAL_REVIEW":
                if not override_path.is_file():
                    skipped += 1
                    continue
                # Use rust_cli as base spec; override will replace main.py anyway
                chosen = "rust_cli"
            if chosen not in FAMILY_SPECS:
                print(f"  SKIP {inst}: family '{chosen}' not in FAMILY_SPECS")
                skipped += 1
                continue
            score = existing_score(inst)
            if score is not None and score >= LOCK_THRESHOLD and not args.force_overwrite_locked:
                print(
                    f"  PROTECT {inst}: existing eval scores {score:.1f}% >= {LOCK_THRESHOLD}% (pass --force-overwrite-locked to override)"
                )
                protected += 1
                continue
            spec = FAMILY_SPECS[chosen]
            factory = PB_ROOT / f"determinex_pb_factory_{inst}_v1"
            factory.mkdir(parents=True, exist_ok=True)
            ej = factory / inst / f"{inst}.eval.json"
            probe = load_probe(ej if ej.is_file() else None)
            mined = miner.get(inst) or None
            oracle_entry = oracle_data.get(inst) or {}
            oracle_memos = oracle_entry.get("memos") or []
            tool_fixtures = fixture_data.get(inst) or {}
            try:
                write_scaffold(
                    instance_id=inst,
                    spec=spec,
                    probe=probe,
                    out=factory,
                    pack=True,
                    mined=mined,
                    oracle=oracle_memos,
                    fixtures=tool_fixtures,
                )
                # Per-tool override: if corpus/programbench/per_tool_overrides/<inst>/main.py
                # exists, overwrite the generated main.py with the hand-tuned version.
                # This lets us push bottom-15 tools above the generic scaffold ceiling.
                override = (
                    ROOT / "corpus" / "programbench" / "per_tool_overrides" / inst / "main.py"
                )
                if override.is_file():
                    target = factory / inst / "source" / "main.py"
                    target.write_text(
                        override.read_text(encoding="utf-8"), encoding="utf-8", newline="\n"
                    )
                    # Re-pack the submission.tar.gz since main.py changed
                    try:
                        import tarfile
                        from io import BytesIO

                        sub_dir = factory / inst / "source"
                        sub_tar = factory / inst / "submission.tar.gz"
                        epoch = 1_767_225_600
                        with tarfile.open(sub_tar, "w:gz") as tf:
                            for f in sorted(sub_dir.iterdir(), key=lambda p: p.name):
                                if not f.is_file():
                                    continue
                                data = f.read_bytes()
                                info = tarfile.TarInfo(f.name)
                                info.size = len(data)
                                info.mtime = epoch
                                info.uid = info.gid = 0
                                info.uname = info.gname = ""
                                info.mode = 0o755 if f.name.endswith((".py", ".sh")) else 0o644
                                tf.addfile(info, BytesIO(data))
                        print(f"  OVERRIDE {inst}: per-tool main.py applied")
                    except Exception as ex:
                        print(
                            f"  WARN {inst}: override main.py written but tar repack failed: {ex}"
                        )
                regen += 1
            except Exception as ex:
                print(f"  ERR  {inst}: {ex}")
                errors += 1
        print()
        print(f"regenerated: {regen}, protected: {protected}, skipped: {skipped}, errors: {errors}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
