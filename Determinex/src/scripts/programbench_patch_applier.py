"""scripts/programbench_patch_applier.py — close the advisor → apply → gate loop.

The advisor proposes universal patches. The three-speed gate validates them
before a 6-hour full eval. This module is the bridge: take an advisor
recommendation, apply it to a scaffold-template variant, scaffold a fresh iter
dir, pack, optionally invoke the gate, and write ledger events for every
transition. The apply-loop the user has been building toward.

Idempotency contract:
  - If the recommendation's `before` text exists in target_file → APPLICABLE
  - If `after` text exists (already-applied state) → ALREADY_APPLIED, skip
  - If neither → CANNOT_APPLY (manual review needed; the profile drifted from
    the actual template)

Safety contract:
  - NEVER modifies the production scaffold file in place. Writes a variant
    file `<original_stem>__<scaffold_version>.py` next to it; scaffold runs
    against the variant via env override.
  - NEVER eval-launches without an explicit gate invocation. The default
    --gate=micro produces a 5-second smoke; --gate=up-to-shard adds ~15 min;
    --gate=full chains into the 3-6h full eval.

CLI:
    # Auto-pick the top recommendation from the advisor and apply it
    python scripts/programbench_patch_applier.py \\
        --from-advisor mass_run_v2_base \\
        --iter-run-id mass_run_v2_iter2 \\
        --dest T:/determinex-programbench/mass_run_v2_iter2 \\
        --gate micro

    # Apply a named family directly (skip advisor)
    python scripts/programbench_patch_applier.py \\
        --family help_text_mismatch \\
        --iter-run-id mass_run_v2_iter2 \\
        --dest T:/determinex-programbench/mass_run_v2_iter2 \\
        --gate up-to-shard --shard-tools tool1 tool2 ...

Returns nonzero exit if patch cannot be applied OR gate halts; zero on
successful applicable-and-gated outcome.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
from programbench_live_monitor import snapshot  # type: ignore[import-not-found]
from programbench_patch_advisor import (  # type: ignore[import-not-found]
    PROGRAMBENCH_PROFILE,
    UniversalPatch,
    propose,  # type: ignore[import-not-found]
)
from run_ledger import LedgerEvent, append_event, record_run_meta  # type: ignore[import-not-found]

# ---------------------------------------------------------------------------
# Apply status
# ---------------------------------------------------------------------------

APPLICABLE = "applicable"
ALREADY_APPLIED = "already_applied"
CANNOT_APPLY = "cannot_apply"


@dataclass
class PatchApplyResult:
    family: str
    status: str  # applicable | already_applied | cannot_apply | applied | gate_halted | gated_ok
    target_file: str  # absolute path of the template that was inspected
    variant_file: str | None = None  # absolute path of the patched variant (if applied)
    changes_made: int = 0  # number of CodeChange entries that took
    cannot_apply_reasons: list[str] = field(default_factory=list)
    gate_report: dict | None = None
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Status detection (idempotent)
# ---------------------------------------------------------------------------


def detect_status(patch: UniversalPatch, repo_root: Path) -> tuple[str, list[str]]:
    """Determine whether `patch` is applicable, already applied, or unable.

    Returns (status, reasons). Reasons are populated only for CANNOT_APPLY
    so the caller can surface them to the human.
    """
    if not patch.scaffold_changes:
        return CANNOT_APPLY, ["patch has no scaffold_changes — advisor entry is informational only"]

    reasons: list[str] = []
    any_applicable = False
    any_already_applied = False
    for change in patch.scaffold_changes:
        target = repo_root / change.file
        if not target.is_file():
            reasons.append(f"{change.file}: target file not found")
            continue
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            reasons.append(f"{change.file}: {type(e).__name__}: {e}")
            continue

        before_present = change.before and change.before in text
        after_present = change.after and change.after in text

        if before_present:
            any_applicable = True
        elif after_present:
            any_already_applied = True
        else:
            reasons.append(
                f"{change.file}: neither `before` nor `after` text present — "
                f"profile may have drifted from the actual template"
            )

    if any_applicable:
        return APPLICABLE, []
    if any_already_applied and not any_applicable:
        return ALREADY_APPLIED, []
    return CANNOT_APPLY, reasons


# ---------------------------------------------------------------------------
# Variant writer — writes a patched copy next to the original
# ---------------------------------------------------------------------------


def _variant_path(target: Path, scaffold_version: str) -> Path:
    """`scripts/mass_run_v2_scaffold.py` + `clap_v1` → `scripts/mass_run_v2_scaffold__clap_v1.py`."""
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in scaffold_version)
    return target.with_name(f"{target.stem}__{safe}{target.suffix}")


def apply_patch_to_variant(
    patch: UniversalPatch, repo_root: Path, scaffold_version: str
) -> tuple[Path, int]:
    """Apply every CodeChange in patch to a fresh copy of each target file.

    The original file is NEVER modified. A variant file
    `<stem>__<scaffold_version><suffix>` is written next to it. If multiple
    CodeChanges target the same file, they're all applied to the same
    variant file. Returns (last_variant_path, total_changes_applied).
    """
    if not patch.scaffold_changes:
        raise ValueError("no scaffold_changes to apply")

    # Group changes by target file so we make ONE variant per target
    by_file: dict[Path, list] = {}
    for change in patch.scaffold_changes:
        by_file.setdefault((repo_root / change.file).resolve(), []).append(change)

    last_variant: Path | None = None
    total_changes = 0
    for target, changes in by_file.items():
        text = target.read_text(encoding="utf-8")
        for change in changes:
            if change.before in text:
                text = text.replace(change.before, change.after, 1)
                total_changes += 1
        variant = _variant_path(target, scaffold_version)
        variant.write_text(text, encoding="utf-8", newline="\n")
        last_variant = variant

    if last_variant is None:
        raise RuntimeError("no variant file written")
    return last_variant, total_changes


# ---------------------------------------------------------------------------
# Scaffold + pack the iter dir using the patched variant
# ---------------------------------------------------------------------------


def run_scaffold_with_variant(
    variant: Path, dest: Path, env_overrides: dict | None = None
) -> tuple[bool, str]:
    """Run the variant scaffold script with DETERMINEX_PB_SCAFFOLD_OUT=dest.

    The variant file shares the same CLI as the original mass_run_v2_scaffold
    (same `_cli`), so we just invoke it directly.
    """
    env = os.environ.copy()
    env["DETERMINEX_PB_SCAFFOLD_OUT"] = str(dest)
    env.setdefault("PYTHONUTF8", "1")
    if env_overrides:
        env.update({k: str(v) for k, v in env_overrides.items()})
    try:
        proc = subprocess.run(
            [sys.executable, str(variant)],
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return False, "scaffold run timed out after 300s"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-1500:]
        return False, f"scaffold rc={proc.returncode}\n{tail}"
    return True, proc.stdout[-1500:]


def run_pack_for_dest(dest: Path) -> tuple[bool, str]:
    """Invoke mass_run_v2_pack.py against the dest dir via env override."""
    env = os.environ.copy()
    env["DETERMINEX_PB_SCAFFOLD_OUT"] = str(dest)
    env.setdefault("PYTHONUTF8", "1")
    try:
        proc = subprocess.run(
            [sys.executable, str(_SCRIPTS / "mass_run_v2_pack.py")],
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return False, "pack timed out after 600s"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-1500:]
        return False, f"pack rc={proc.returncode}\n{tail}"
    return True, proc.stdout[-1500:]


# ---------------------------------------------------------------------------
# Driver — the apply-loop
# ---------------------------------------------------------------------------


def apply_recommended(
    *,
    iter_run_id: str,
    dest: Path,
    base_run_id: str = "mass_run_v2_base",
    family: str | None = None,
    gate: str | None = None,
    shard_tools: list[str] | None = None,
    repo_root: Path = Path(__file__).resolve().parents[1],
) -> PatchApplyResult:
    """Run the full apply-loop.

    1. If family is None, pull the top recommendation from the advisor for
       base_run_id; otherwise use the named family directly.
    2. Detect applicability.
    3. If applicable, write a patched scaffold variant.
    4. Record provenance meta for iter_run_id (before any I/O on dest).
    5. Run scaffold + pack against dest with the variant.
    6. Optionally invoke the three-speed gate.
    7. Write ledger events for each transition.
    """
    # Pick the patch
    if family is None:
        snap = snapshot(base_run_id, expected_total=None)
        recs = propose(snap, top_k=5)
        if not recs:
            return PatchApplyResult(
                family="(none)",
                status=CANNOT_APPLY,
                target_file="(advisor has no recommendation)",
                cannot_apply_reasons=["advisor returned 0 recommendations for run"],
            )
        patch = recs[0].patch
        family = patch.family
    else:
        patch = PROGRAMBENCH_PROFILE.get(family)
        if patch is None:
            return PatchApplyResult(
                family=family,
                status=CANNOT_APPLY,
                target_file="(profile)",
                cannot_apply_reasons=[f"no profile entry for family {family!r}"],
            )

    # First target file (for the result's target_file field)
    if patch.scaffold_changes:
        first_target = str((repo_root / patch.scaffold_changes[0].file).resolve())
    else:
        first_target = "(no scaffold_changes)"

    status, reasons = detect_status(patch, repo_root)
    if status != APPLICABLE:
        # Ledger event for the no-op so the cockpit shows we tried
        append_event(
            LedgerEvent(
                run_id=iter_run_id,
                phase="patch_apply",
                status="skipped" if status == ALREADY_APPLIED else "failed",
                extra={
                    "family": family,
                    "detection": status,
                    "reasons": reasons,
                    "scaffold_version": patch.title[:80],
                },
            )
        )
        return PatchApplyResult(
            family=family,
            status=status,
            target_file=first_target,
            cannot_apply_reasons=reasons,
        )

    # Pre-record iter meta BEFORE any disk modification so the run is anchored
    # even if scaffold/pack/gate fails partway.
    scaffold_version = f"applied_{family}_{int(time.time())}"
    record_run_meta(
        run_id=iter_run_id,
        base_run_id=base_run_id,
        scaffold_version=scaffold_version,
        patch_family=family,
        output_root=str(dest),
        notes=f"patch applier auto-recommended from {base_run_id}: {patch.title}",
    )

    # Apply
    variant, n_changes = apply_patch_to_variant(patch, repo_root, scaffold_version)
    append_event(
        LedgerEvent(
            run_id=iter_run_id,
            phase="patch_apply",
            status="completed",
            extra={
                "family": family,
                "variant_file": str(variant),
                "changes_made": n_changes,
                "scaffold_version": scaffold_version,
            },
        )
    )

    # Scaffold + pack
    dest.mkdir(parents=True, exist_ok=True)
    ok, msg = run_scaffold_with_variant(variant, dest)
    append_event(
        LedgerEvent(
            run_id=iter_run_id,
            phase="scaffold",
            status="completed" if ok else "failed",
            extra={"variant_file": str(variant), "msg_tail": msg[-300:]},
        )
    )
    if not ok:
        return PatchApplyResult(
            family=family,
            status="applied",
            target_file=first_target,
            variant_file=str(variant),
            changes_made=n_changes,
            error=f"scaffold failed: {msg}",
        )

    ok, msg = run_pack_for_dest(dest)
    append_event(
        LedgerEvent(
            run_id=iter_run_id,
            phase="pack",
            status="completed" if ok else "failed",
            extra={"msg_tail": msg[-300:]},
        )
    )
    if not ok:
        return PatchApplyResult(
            family=family,
            status="applied",
            target_file=first_target,
            variant_file=str(variant),
            changes_made=n_changes,
            error=f"pack failed: {msg}",
        )

    # Optional gate
    gate_report = None
    if gate:
        import three_speed_gate as gate_mod

        # Pick the first packaged instance as the micro-test executable
        candidates = list(dest.glob("*/source/executable"))
        if not candidates:
            return PatchApplyResult(
                family=family,
                status="applied",
                target_file=first_target,
                variant_file=str(variant),
                changes_made=n_changes,
                error="no <inst>/source/executable available for micro gate",
            )
        try:
            gate_report = gate_mod.run_gate(
                gate=gate,
                executable=candidates[0],
                scaffold_root=dest,
                shard_tools=shard_tools,
                run_id=iter_run_id,
            )
        except Exception as e:
            return PatchApplyResult(
                family=family,
                status="applied",
                target_file=first_target,
                variant_file=str(variant),
                changes_made=n_changes,
                gate_report={"error": f"{type(e).__name__}: {e}"},
                error=f"gate failed: {e}",
            )
        if gate_report.get("verdict", "").endswith("_passed"):
            final_status = "gated_ok"
        else:
            final_status = "gate_halted"
        return PatchApplyResult(
            family=family,
            status=final_status,
            target_file=first_target,
            variant_file=str(variant),
            changes_made=n_changes,
            gate_report=gate_report,
        )

    return PatchApplyResult(
        family=family,
        status="applied",
        target_file=first_target,
        variant_file=str(variant),
        changes_made=n_changes,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli() -> int:
    ap = argparse.ArgumentParser(description="ProgramBench patch applier — close the apply-loop")
    ap.add_argument(
        "--from-advisor",
        default=None,
        help="auto-pick top recommendation from advisor for this base run_id",
    )
    ap.add_argument(
        "--family", default=None, help="override the family to apply (skip the advisor)"
    )
    ap.add_argument(
        "--iter-run-id",
        required=True,
        help="run_id for the iter being launched (e.g. mass_run_v2_iter2)",
    )
    ap.add_argument(
        "--dest",
        type=Path,
        required=True,
        help="output dir for the patched scaffold (e.g. T:/determinex-programbench/mass_run_v2_iter2)",
    )
    ap.add_argument(
        "--gate",
        choices=["micro", "up-to-shard", "full"],
        default=None,
        help="invoke three_speed_gate after scaffold + pack",
    )
    ap.add_argument("--shard-tools", nargs="+", default=None)
    ap.add_argument(
        "--detect-only", action="store_true", help="report applicability + skip actually applying"
    )
    args = ap.parse_args()

    if not args.from_advisor and not args.family:
        print("ERROR: must specify --from-advisor RUN_ID or --family NAME", file=sys.stderr)
        return 2

    if args.detect_only:
        family = args.family
        if family is None:
            snap = snapshot(args.from_advisor, expected_total=None)
            recs = propose(snap, top_k=1)
            if not recs:
                print(json.dumps({"status": "no_recommendation"}, indent=2))
                return 1
            family = recs[0].family
            patch = recs[0].patch
        else:
            patch = PROGRAMBENCH_PROFILE.get(family)
            if patch is None:
                print(json.dumps({"status": "no_profile_entry", "family": family}, indent=2))
                return 1
        repo_root = Path(__file__).resolve().parents[1]
        status, reasons = detect_status(patch, repo_root)
        print(
            json.dumps(
                {
                    "family": family,
                    "title": patch.title,
                    "detection_status": status,
                    "reasons": reasons,
                    "scaffold_changes": [
                        {"file": c.file, "locator": c.locator} for c in patch.scaffold_changes
                    ],
                },
                indent=2,
            )
        )
        return 0 if status == APPLICABLE else 1

    result = apply_recommended(
        iter_run_id=args.iter_run_id,
        dest=args.dest,
        base_run_id=args.from_advisor or "mass_run_v2_base",
        family=args.family,
        gate=args.gate,
        shard_tools=args.shard_tools,
    )

    print(json.dumps(result.to_dict(), indent=2, default=str))
    if result.status in ("applied", "gated_ok"):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(_cli())
