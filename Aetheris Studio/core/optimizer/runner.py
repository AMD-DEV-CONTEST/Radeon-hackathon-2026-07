"""
Manual Kernel Optimization Runner & Promotion.
Runs the full isolated correctness+benchmark pipeline for one or all untested transformations of a kernel, registering only genuinely measured, validated candidates, and promotes an already-validated candidate by re-rendering its deterministic transformation against the current official template.

Replaces the previous daemon.py: that subscribed to the EventBus
chat_turn_end topic to trigger optimization passes automatically during
GPU idle time, but its actual pass body was never implemented (a bare
`pass`) and it was never even instantiated/started from app.py -- dead
code end to end. Real Hyperloom (the AMD tool this subsystem takes its
core idea from) is not an idle-time daemon either: it's a long,
deliberately-triggered session, which this manual command matches
directly instead of re-attempting the idle-daemon design."""

import logging
from typing import Any, Dict, List, Optional, Tuple

from core.optimizer import is_optimizer_enabled
from core.optimizer.applier import TransformationApplier
from core.optimizer.benchmark import BenchmarkMetrology, GPUSafetyLock
from core.optimizer.catalog import TransformationCatalog
from core.optimizer.isolated_runner import REFERENCE_MODEL, IsolatedInstanceError, IsolatedInstancePair
from core.optimizer.registry import CandidateRegistry
from core.optimizer.sandbox import TemplateSandbox
from core.optimizer.validator import CandidateValidator

logger = logging.getLogger(__name__)

DEFAULT_MIN_SPEEDUP_PCT = 3.0


def _decide(
    *,
    correctness_passed: bool,
    engaged: Optional[bool] = None,
    engagement_reason: str = "",
    speedup_pct: Optional[float] = None,
    significant: Optional[bool] = None,
    min_speedup_pct: float = DEFAULT_MIN_SPEEDUP_PCT,
    reasons: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Turn one candidate's evidence into a KEEP / NEEDS_REVIEW / REVERT
    decision plus the reasons behind it.

    Modelled on Hyperloom's `make_proposal`
    (agents/kernel/tools/kernel_optimization.py): a graded disposition
    rather than a boolean, so "wrong output" (REVERT), "we cannot tell"
    (NEEDS_REVIEW) and "measurably better" (KEEP) stay distinguishable
    instead of collapsing into one `validated: false`.

    Only KEEP is ever registered as a promotable candidate. `validated`
    is still emitted alongside it so existing readers keep working, but
    it is now derived from the decision rather than being the decision.
    """
    reasons = list(reasons or [])

    if not correctness_passed:
        return {"decision": "REVERT", "reasons": reasons or ["correctness failed"], "validated": False}

    # A change that never reached the GPU has no measurement to interpret:
    # its "0%" and a genuine 0% are the same number for opposite reasons.
    if engaged is False:
        return {"decision": "REVERT", "reasons": reasons + [engagement_reason], "validated": False}
    if engaged is None:
        reasons.append("engagement could not be verified")

    if speedup_pct is None:
        return {"decision": "NEEDS_REVIEW", "reasons": reasons + ["no speedup measured"], "validated": False}

    if speedup_pct <= 0.0:
        return {
            "decision": "REVERT",
            "reasons": reasons + [f"candidate regressed ({speedup_pct:.1f}%)"],
            "validated": False,
        }
    if speedup_pct < min_speedup_pct:
        reasons.append(f"speedup {speedup_pct:.1f}% is below the {min_speedup_pct:.1f}% promotion threshold")
    if significant is None:
        reasons.append("too few reps to judge statistical significance")
    elif significant is False:
        reasons.append(f"speedup {speedup_pct:.1f}% is within run-to-run noise (interquartile ranges overlap)")

    if reasons:
        return {"decision": "NEEDS_REVIEW", "reasons": reasons, "validated": False}
    return {"decision": "KEEP", "reasons": ["correct, engaged, and significantly faster"], "validated": True}


def run_optimization(
    kernel_name: str,
    transformation_id: Optional[str] = None,
    model_name: str = REFERENCE_MODEL,
    min_speedup_pct: float = DEFAULT_MIN_SPEEDUP_PCT,
    trials: int = 3,
    registry: Optional[CandidateRegistry] = None,
) -> List[Dict[str, Any]]:
    """Tests one (if transformation_id is given) or every not-yet-registered
    non-base transformation in the catalog for `kernel_name`: renders the
    candidate, validates it against the official kernel via two isolated
    vte-server instances, and -- only if correctness passes AND the
    measured median speedup clears min_speedup_pct -- registers it as a
    validated candidate with the number actually measured in this run.

    A rejected or below-threshold transformation is reported in the
    returned list but never written to the registry: promoting measurement
    noise as an "optimization" is exactly what the speedup threshold and
    this all-or-nothing registration are meant to prevent.

    Returns one dict per transformation attempted, in catalog order. Each
    has at least "transformation_id" and "params"; a transformation that
    couldn't even be attempted (busy GPU, isolated instance failed to
    start) has "skip_reason" instead of "validated"/"speedup_pct".

    `model_name` defaults to REFERENCE_MODEL (small, fast, already
    measured) -- pass any model `aetheris chat -m <name>` accepts to test
    a kernel path only exercised by that model, or under its real VRAM
    pressure. Both isolated instances load this same model.

    `registry` defaults to the real, persistent CandidateRegistry() -- pass
    a temp-file-backed one (tests do) to keep a test run's candidates out
    of the real registry.json."""
    if not is_optimizer_enabled():
        return [{
            "transformation_id": transformation_id or "*",
            "skip_reason": "Optimizer disabled: set AETHERIS_OPTIMIZER_ENABLED=true to run this (it spawns two "
                           "extra GPU-resident model instances and takes real GPU time).",
        }]

    lock = GPUSafetyLock()
    if not lock.acquire():
        return [{
            "transformation_id": transformation_id or "*",
            "skip_reason": "GPU busy: another optimizer run or generation already holds the lock.",
        }]

    registry = registry or CandidateRegistry()

    try:
        catalog = TransformationCatalog()
        all_transformations = catalog.get_transformations_for_kernel(kernel_name)
        if not all_transformations:
            return [{
                "transformation_id": transformation_id or "*",
                "skip_reason": f"No transformations registered for kernel '{kernel_name}'.",
            }]

        if transformation_id:
            to_test = [t for t in all_transformations if t.transformation_id == transformation_id]
            if not to_test:
                return [{
                    "transformation_id": transformation_id,
                    "skip_reason": f"Transformation '{transformation_id}' not found in catalog for '{kernel_name}'.",
                }]
        else:
            already_registered = {
                (c.get("kernel_name"), c.get("transformation_id"))
                for c in registry.get_candidates()
            }
            to_test = [
                t for t in all_transformations
                if t.transformation_id != "base"
                and (t.kernel_name, t.transformation_id) not in already_registered
            ]

        sandbox = TemplateSandbox()
        official_path = sandbox.vte_templates_dir / f"{kernel_name}.hip.template"
        applier = TransformationApplier()
        validator = CandidateValidator()
        bm = BenchmarkMetrology()

        results: List[Dict[str, Any]] = []
        for transformation in to_test:
            entry: Dict[str, Any] = {
                "transformation_id": transformation.transformation_id,
                "params": transformation.params,
            }
            try:
                candidate_code = applier.apply(official_path, transformation)
            except Exception as e:
                entry["skip_reason"] = f"Failed to render candidate: {e}"
                results.append(entry)
                continue

            try:
                with IsolatedInstancePair(kernel_name, candidate_code, model_name=model_name) as pair:
                    correct, correctness_reason = validator.validate_pair(pair, reference_model=model_name)
                    entry["correctness"] = correctness_reason
                    # Correctness is checked before the benchmark is even run,
                    # let alone trusted: a kernel that produces wrong output
                    # being "faster" is not a result worth measuring.
                    if not correct:
                        entry.update(_decide(correctness_passed=False, reasons=[correctness_reason]))
                        results.append(entry)
                        continue
                    bench = bm.run_interleaved_ab_benchmark_pair(pair, model_name=model_name, trials=trials)
                    # Only meaningful once generation has actually run, which
                    # validate_pair + the benchmark above guarantee.
                    engaged, engagement_reason = pair.verify_engagement()
            except IsolatedInstanceError as e:
                entry["skip_reason"] = f"Isolated instance failed to start: {e}"
                results.append(entry)
                continue

            entry["reference_tok_s"] = bench["reference_tok_s"]
            entry["candidate_tok_s"] = bench["candidate_tok_s"]
            entry["speedup_pct"] = bench["speedup_pct"]
            entry["significant"] = bench["significant"]
            entry["engaged"] = engaged
            entry["engagement"] = engagement_reason

            entry.update(_decide(
                correctness_passed=True,
                engaged=engaged,
                engagement_reason=engagement_reason,
                speedup_pct=bench["speedup_pct"],
                significant=bench["significant"],
                min_speedup_pct=min_speedup_pct,
            ))

            if entry["decision"] == "KEEP":
                entry["registered_id"] = registry.register_candidate({
                    "kernel_name": kernel_name,
                    "transformation_id": transformation.transformation_id,
                    "model_name": model_name,
                    "speedup_pct": bench["speedup_pct"],
                    "significant": bench["significant"],
                    "engaged": engaged,
                    "validated": True,
                })

            results.append(entry)

        return results
    finally:
        lock.release()


def format_result_line(entry: Dict[str, Any]) -> Tuple[str, str]:
    """Render one run_optimization result as (severity, text).

    `severity` is "ok" / "warn" / "bad" so the CLI and the in-chat command
    can colour it consistently without each re-deriving the meaning of a
    decision."""
    tid = entry.get("transformation_id", "?")
    if entry.get("skip_reason") and "speedup_pct" not in entry:
        return "warn", f"{tid}: SKIPPED -- {entry['skip_reason']}"

    decision = entry.get("decision", "NEEDS_REVIEW")
    reasons = "; ".join(entry.get("reasons") or []) or "no reason recorded"

    if decision == "KEEP":
        sig = entry.get("significant")
        sig_note = "significant" if sig else ("unverified significance" if sig is None else "within noise")
        return "ok", (
            f"{tid}: KEEP +{entry['speedup_pct']:.1f}% ({sig_note}) "
            f"-> registered as {entry.get('registered_id')}"
        )
    if "speedup_pct" in entry:
        return ("warn" if decision == "NEEDS_REVIEW" else "bad"), (
            f"{tid}: {decision} ({entry['speedup_pct']:+.1f}%) -- {reasons}"
        )
    return ("warn" if decision == "NEEDS_REVIEW" else "bad"), f"{tid}: {decision} -- {reasons}"


def apply_candidate(candidate_id: str, registry: Optional[CandidateRegistry] = None) -> Tuple[bool, str]:
    """Promotes an already-validated candidate: re-renders its exact
    deterministic transformation against whatever the official template
    currently contains (TransformationApplier.apply is a pure function of
    (official content, params), so this reproduces precisely what
    run_optimization validated as long as the official file hasn't changed
    since), refreshes the .orig backup, and writes the result into the
    official file.

    Does NOT reload the production vte-server itself -- that requires
    calling app.py's /api/optimizer/reload-vte over HTTP (see
    AetherisClient.reload_vte), which only the caller (chat.py/cli.py, both
    of which already hold an AetherisClient) can reach; this function only
    touches the filesystem so it stays usable/testable without a running
    backend.

    `registry` defaults to the real, persistent CandidateRegistry() -- pass
    the same temp-file-backed one a test used with run_optimization to look
    up a candidate that was never written to the real registry.json."""
    registry = registry or CandidateRegistry()
    candidates = [c for c in registry.get_candidates() if c.get("id") == candidate_id]
    if not candidates:
        return False, f"Candidate '{candidate_id}' not found in registry."
    cand = candidates[0]
    if not cand.get("validated"):
        return False, f"Candidate '{candidate_id}' is not marked validated; refusing to promote."

    kernel_name = cand.get("kernel_name", "")
    transformation_id = cand.get("transformation_id", "")
    catalog = TransformationCatalog()
    transformation = next(
        (t for t in catalog.get_transformations_for_kernel(kernel_name) if t.transformation_id == transformation_id),
        None,
    )
    if transformation is None:
        return False, f"Transformation '{transformation_id}' not found in catalog for kernel '{kernel_name}'."

    sandbox = TemplateSandbox()
    official_path = sandbox.vte_templates_dir / f"{kernel_name}.hip.template"
    applier = TransformationApplier()
    try:
        rendered_code = applier.apply(official_path, transformation)
    except Exception as e:
        return False, f"Failed to render candidate for promotion: {e}"

    sandbox.clone_official_template(kernel_name)  # refreshes .orig backup before we overwrite
    official_path.write_text(rendered_code, encoding="utf-8")

    return True, (
        f"Candidate '{candidate_id}' promoted: {kernel_name}.hip.template updated on disk "
        f"(backup at {kernel_name}.hip.template.orig)."
    )
