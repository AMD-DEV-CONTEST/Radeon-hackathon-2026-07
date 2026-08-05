#!/usr/bin/env python3
"""sprint4_bulk_generate.py — generate factory scaffolds for ALL classifiable
ProgramBench base instances. Per user: 'lets get this all scaffolded'.

Discovery: scans T:/determinex-programbench/mass_run_v2_base/<instance_id>/ dirs.
Classification: uses programbench_classify_family.py logic inline.
Generation: invokes corpus/programbench/families/<wave>/<family>/scaffold_generator.py.
Packing: always (each generator emits submission.tar.gz when --pack).

Output dirs: T:/determinex-programbench/determinex_pb_factory_<instance>_v1/
Per-tool record: logs/mass_run_v2/sprint4_bulk_generation.json

Skipped (per user / structural):
  - Anything in QUARANTINE_TOOLS (hyperfine — Docker memory)
  - Anything in HAND_BUILT_INSTANCES (sprint 1/2/3 already exists with v2/v3
    that beats anything a generic generator can produce)
  - Anything in LOCKED_TOOLS (already at 100% — would waste eval time)
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus" / "programbench" / "families"
PBROOT = Path("T:/determinex-programbench")
BASE_RUN = PBROOT / "mass_run_v2_base"

sys.path.insert(0, str(ROOT / "scripts"))
from programbench_classify_family import (  # type: ignore[import-not-found]
    _classify_by_lang,
    _classify_by_name,
    _classify_by_tests,
)

# Subtype overrides — semantic behavior layer beneath broad family
sys.path.insert(0, str(CORPUS))
from generator_lib import INSTANCE_SUBTYPE_OVERRIDES  # type: ignore[import-not-found]

# Already locked at 100% upstream — no need to factory-generate
LOCKED_TOOLS = {
    "burntsushi__ripgrep",
    "ajeetdsouza__zoxide",
    "sclevine__yj",
    "sirwart__ripsecrets",
    "mgdm__htmlq",
}

# Hand-built sprint 1/2/3 — factory v1 cannot beat the carefully-tuned v2/v3
HAND_BUILT_INSTANCES = {
    "yaa110__nomino",
    "konradsz__igrep",
    "mookid__diffr",
    "sharkdp__hyperfine",
    "wgunderwood__tex-fmt",
    "cheat__cheat",
    "svenstaro__genact",
    "riquito__tuc",
    "rust-embedded__svd2rust",
    "foriequal0__git-trim",
}

# Structurally cannot eval — skip entirely
QUARANTINE_TOOLS = {"sharkdp__hyperfine"}

# Sprint 4 winners — already locked at current scaffold; don't regen (would
# wipe their eval JSONs and force re-eval). These are produced by the same
# factory generator; rerun them via the chain only if the generator changes
# in a way that improves THEIR scores.
SPRINT4_LOCKED = {
    "pls-rs__pls",
    "ggreer__the_silver_searcher",
    "git-bahn__git-graph",
    "ksxgithub__parallel-disk-usage",
    "clog-tool__clog-cli",
    "canop__rhit",
}

# Map family → wave directory
FAMILY_WAVE = {
    "rust_cli": "wave1",
    "go_cli": "wave1",
    "python_cli": "wave1",
    "node_cli": "wave1",
    "shell_coreutils": "wave1",
    "git_wrappers": "wave1",
    "file_renamers": "wave1",
    "search_grep": "wave1",
    "text_diff": "wave1",
    "formatters": "wave1",
    "json_yaml_toml": "wave2",
    "csv_table": "wave2",
    "regex_tools": "wave2",
    "archive_compression": "wave2",
    "network_http": "wave2",
    "database": "wave2",
    "config_env": "wave2",
    "tui_terminal": "wave2",
    "latex_document": "wave3",
    "codegen": "wave3",
    "compiler_wrappers": "wave3",
    "animation_output": "wave3",
    "benchmark_timing": "wave3",
    "editor_integrated": "wave3",
    "package_manager": "wave3",
    "security_scanner": "wave3",
    # Sprint-4 audit additions (formerly deferred families)
    "biosequence": "wave3",
    "image_terminal_render": "wave3",
    "docs_static_site": "wave3",
    "html_converter": "wave3",
    "binary_inspector": "wave3",
    "game_simulator": "wave3",
}


def _instance_stem(instance: str) -> str:
    return re.sub(r"\.[a-f0-9]+$", "", instance)


def _classify(instance: str, eval_json: Path | None) -> tuple[str | None, dict]:
    """Returns (primary_family, signals_dict)."""
    m = re.match(r"^[^_]+__([^.]+)\.[^.]+$", instance)
    tool = m.group(1) if m else instance
    by_name = _classify_by_name(tool)
    by_test = _classify_by_tests(eval_json) if eval_json else []
    by_lang = _classify_by_lang(instance)
    primary: str | None = None
    if by_name:
        primary = by_name[0]
    elif by_test:
        primary = by_test[0][0]
    elif by_lang:
        primary = by_lang
    return primary, {
        "tool": tool,
        "by_name": by_name,
        "by_test": [(f, n) for f, n in by_test[:3]],
        "by_lang": by_lang,
    }


def _factory_dir(instance: str) -> Path:
    return PBROOT / f"determinex_pb_factory_{instance}_v1"


def _generate(instance: str, family: str, eval_json: Path | None) -> dict:
    # Subtype override: if this instance has a per-instance subtype assignment,
    # use it. Wrapper still goes through the broad-family scaffold_generator.py,
    # but passes --family-override to route to the subtype FamilySpec.
    subtype = INSTANCE_SUBTYPE_OVERRIDES.get(_instance_stem(instance))
    effective_for_wrapper = family
    family_override: str | None = None
    if subtype:
        # Wrapper path lives at the broad-family dir (subtype is "<broad>.<sub>")
        broad = subtype.split(".", 1)[0]
        effective_for_wrapper = broad
        family_override = subtype

    wave = FAMILY_WAVE.get(effective_for_wrapper)
    if wave is None:
        return {"status": "UNKNOWN_FAMILY", "family": effective_for_wrapper}
    gen = CORPUS / wave / effective_for_wrapper / "scaffold_generator.py"
    if not gen.is_file():
        return {"status": "GENERATOR_MISSING", "gen_path": str(gen)}

    out_root = _factory_dir(instance)
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(gen),
        "--instance",
        instance,
        "--out",
        str(out_root),
        "--pack",
    ]
    if eval_json and eval_json.is_file():
        cmd += ["--probe-from", str(eval_json)]
    if family_override:
        cmd += ["--family-override", family_override]

    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        return {"status": "GEN_TIMEOUT", "elapsed_s": 120.0}
    elapsed = time.time() - t0

    inst_dir = out_root / instance
    main_py = inst_dir / "source" / "main.py"
    submission = inst_dir / "submission.tar.gz"
    ok = rc == 0 and main_py.is_file() and submission.is_file()
    return {
        "status": "OK" if ok else "GEN_FAIL",
        "rc": rc,
        "elapsed_s": round(elapsed, 3),
        "subtype": family_override,
        "main_py": str(main_py),
        "submission": str(submission),
        "submission_bytes": submission.stat().st_size if submission.is_file() else 0,
        "stderr_tail": (proc.stderr or "")[-200:] if rc != 0 else "",
    }


def _base_score(eval_json: Path) -> float | None:
    if not eval_json.is_file():
        return None
    try:
        d = json.loads(eval_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    tr = d.get("test_results", []) or []
    if not tr:
        return None
    p = sum(1 for t in tr if t.get("status") == "passed")
    return round(100.0 * p / len(tr), 2)


def main() -> int:
    if not BASE_RUN.is_dir():
        print(f"ERROR: base run dir not found: {BASE_RUN}")
        return 1

    instances = sorted(p.name for p in BASE_RUN.iterdir() if p.is_dir())
    print(f"Sprint 4 bulk generation — scanning {len(instances)} base instances")
    print(f"Generators root: {CORPUS}")
    print(f"Output root:     {PBROOT}/determinex_pb_factory_<instance>_v1/")
    print()

    records: list[dict] = []
    family_counts: Counter = Counter()
    t0_total = time.time()

    n_skipped_hand = 0
    n_skipped_locked = 0
    n_skipped_quarantine = 0
    n_unclassified = 0
    n_generated = 0
    n_failed = 0

    for inst in instances:
        stem = _instance_stem(inst)
        ej = BASE_RUN / inst / f"{inst}.eval.json"
        base_pct = _base_score(ej)

        # Skip rules
        if stem in HAND_BUILT_INSTANCES:
            records.append({"instance": inst, "skipped": "hand_built"})
            n_skipped_hand += 1
            continue
        if stem in LOCKED_TOOLS:
            records.append({"instance": inst, "skipped": "already_locked_100"})
            n_skipped_locked += 1
            continue
        if stem in QUARANTINE_TOOLS:
            records.append({"instance": inst, "skipped": "quarantined"})
            n_skipped_quarantine += 1
            continue
        if stem in SPRINT4_LOCKED:
            records.append({"instance": inst, "skipped": "sprint4_locked"})
            n_skipped_locked += 1
            continue

        primary, signals = _classify(inst, ej if ej.is_file() else None)
        if primary is None:
            # Fallback: generic rust_cli scaffold. v1 still emits help/version/
            # unknown-flag with sensible bones; eval will simply not lift much
            # but won't break smoke pass.
            primary = "rust_cli"
            signals["fallback"] = "no_match_default_rust_cli"

        rec = _generate(inst, primary, ej if ej.is_file() else None)
        rec["instance"] = inst
        rec["family"] = primary
        rec["base_score"] = base_pct
        rec["signals"] = signals
        records.append(rec)

        if rec.get("status") == "OK":
            n_generated += 1
            family_counts[primary] += 1
        else:
            n_failed += 1

    total_wall = time.time() - t0_total

    # Summary printing
    print("=== summary ===")
    print(f"  total instances:        {len(instances)}")
    print(f"  skipped (hand-built):   {n_skipped_hand}")
    print(f"  skipped (locked 100):   {n_skipped_locked}")
    print(f"  skipped (quarantined):  {n_skipped_quarantine}")
    print(f"  unclassified:           {n_unclassified}")
    print(f"  generated OK:           {n_generated}")
    print(f"  generation failed:      {n_failed}")
    print()
    print(f"  total wall time:        {round(total_wall, 1)}s")
    if n_generated:
        avg = sum(r.get("elapsed_s", 0) for r in records if r.get("status") == "OK") / n_generated
        print(f"  avg per-tool gen:       {round(avg, 3)}s")
    print()
    print("  by family (top 15):")
    for fam, n in family_counts.most_common(15):
        print(f"    {n:>4}  {fam}")

    out_log = ROOT / "logs" / "mass_run_v2" / "sprint4_bulk_generation.json"
    out_log.parent.mkdir(parents=True, exist_ok=True)
    out_log.write_text(
        json.dumps(
            {
                "records": records,
                "summary": {
                    "n_instances": len(instances),
                    "n_skipped_hand_built": n_skipped_hand,
                    "n_skipped_locked": n_skipped_locked,
                    "n_skipped_quarantined": n_skipped_quarantine,
                    "n_unclassified": n_unclassified,
                    "n_generated_ok": n_generated,
                    "n_generation_failed": n_failed,
                    "total_wall_s": round(total_wall, 1),
                    "by_family": dict(family_counts.most_common()),
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print()
    print(f"  log: {out_log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
