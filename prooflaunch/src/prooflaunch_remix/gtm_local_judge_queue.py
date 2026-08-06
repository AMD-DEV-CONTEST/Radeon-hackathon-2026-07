from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from .files import atomic_write_text
from .gtm_judge_calibration import compile_judge_calibration_bundle
from .inference_gateway import InferenceScope


SCHEMA = "ProofLaunchLocalGovernanceJudgeQueueV1"
RUBRIC_ID = "gtm-governance-closure-binary-v1"
RUBRIC = (
    "Judge the GTM governance dossier. PASS only if: capability_count=10 and "
    "missing_capabilities is empty; external_actions_executed=0; "
    "workspace_activation_disabled=true; every scenario requires human review "
    "and has no automatic publish, budget activation, or strategy mutation; "
    "post_selection_lane_count=9 with identity and evidence spine connected and "
    "activation disabled; zero-budget cases exclude paid channels; "
    "causal_revenue_proven=false and four_a_effect_proven=false when human_reviews=0 "
    "and production_outcomes=0; truth_boundary_present=true. Return JSON only: "
    '{"pass":boolean,"reason_code":"short_snake_case"}.'
)
MODEL_RUBRIC = (
    "Evaluate the supplied Boolean check vector literally. Return pass=true if and only if "
    "all_checks_satisfied is true. Otherwise return pass=false. For reason_code use "
    "all_checks_pass when pass is true, or failed_check_present when pass is false. Return only JSON: "
    '{"pass":boolean,"reason_code":"short_snake_case"}.'
)
_REASON = re.compile(r"^[a-z][a-z0-9_]{0,79}$")


class LocalJudgeQueueError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_display_path(path: Path) -> str:
    """Return a stable locator without leaking a workstation absolute path."""

    try:
        return str(path.relative_to(Path.cwd().resolve()))
    except ValueError:
        return path.name


def _industry_key(case: Mapping[str, Any]) -> str:
    campaign_id = str(case.get("campaign_id", ""))
    business = str(case.get("business_model", ""))
    lifecycle = str(case.get("lifecycle", ""))
    budget = str(case.get("budget", ""))
    suffix = f"-{business}-{lifecycle}-{budget}"
    if not campaign_id.startswith("campaign-") or not campaign_id.endswith(suffix):
        raise LocalJudgeQueueError("lifecycle case campaign identity is invalid")
    industry = campaign_id[len("campaign-") : -len(suffix)]
    if not industry:
        raise LocalJudgeQueueError("lifecycle case industry identity is missing")
    return industry


def _combo(case: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return tuple(
        str(case.get(field, ""))
        for field in ("business_model", "lifecycle", "budget", "industry_risk")
    )  # type: ignore[return-value]


def select_stratified_sources(
    lifecycle_matrix: Mapping[str, Any], *, source_count: int = 50
) -> list[dict[str, Any]]:
    cases = lifecycle_matrix.get("cases")
    if (
        lifecycle_matrix.get("schema") != "ProofLaunchGTMLifecycleClosureMatrixV1"
        or not isinstance(cases, list)
        or len(cases) < source_count
    ):
        raise LocalJudgeQueueError("lifecycle matrix is incomplete")
    unsigned = dict(lifecycle_matrix)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise LocalJudgeQueueError("lifecycle matrix digest is invalid")
    candidates = [dict(case) for case in cases if isinstance(case, Mapping)]
    if len(candidates) != len(cases):
        raise LocalJudgeQueueError("lifecycle matrix contains a non-object case")
    candidates.sort(key=lambda case: str(case.get("content_sha256", "")))
    all_combos = {_combo(case) for case in candidates}
    all_industries = {_industry_key(case) for case in candidates}
    selected: list[dict[str, Any]] = []
    seen_combos: set[tuple[str, str, str, str]] = set()
    seen_industries: set[str] = set()
    dimension_seen = {field: set() for field in ("business_model", "lifecycle", "budget", "industry_risk")}
    while len(selected) < source_count:
        remaining = [case for case in candidates if case not in selected]
        if not remaining:
            raise LocalJudgeQueueError("not enough distinct lifecycle cases")

        def score(case: Mapping[str, Any]) -> tuple[int, str]:
            combo = _combo(case)
            industry = _industry_key(case)
            value = 1000 * int(combo not in seen_combos)
            value += 100 * int(industry not in seen_industries)
            value += 10 * sum(
                str(case.get(field)) not in dimension_seen[field]
                for field in dimension_seen
            )
            value -= sum(_industry_key(row) == industry for row in selected)
            return value, str(case.get("content_sha256", ""))

        choice = max(remaining, key=score)
        selected.append(choice)
        seen_combos.add(_combo(choice))
        seen_industries.add(_industry_key(choice))
        for field in dimension_seen:
            dimension_seen[field].add(str(choice.get(field)))
    if seen_combos != all_combos or seen_industries != all_industries:
        raise LocalJudgeQueueError(
            "50-case source selection did not retain every industry and discrete scenario"
        )
    return selected


def _dossier(case: Mapping[str, Any]) -> dict[str, Any]:
    capabilities = case.get("capabilities")
    scenarios = case.get("scenarios")
    workspace = case.get("last_mile_workspace")
    post = case.get("post_selection_omnichannel_probe")
    if not (
        isinstance(capabilities, Mapping)
        and isinstance(scenarios, list)
        and scenarios
        and isinstance(workspace, Mapping)
        and isinstance(post, Mapping)
    ):
        raise LocalJudgeQueueError("lifecycle case is missing governance evidence")
    missing = sorted(str(key) for key, value in capabilities.items() if value is not True)
    scenario_rows = [row for row in scenarios if isinstance(row, Mapping)]
    if len(scenario_rows) != len(scenarios):
        raise LocalJudgeQueueError("lifecycle scenario is invalid")
    return {
        "rubric_id": RUBRIC_ID,
        "business_model": case.get("business_model"),
        "lifecycle": case.get("lifecycle"),
        "budget": case.get("budget"),
        "industry_risk": case.get("industry_risk"),
        "industry_key": _industry_key(case),
        "capability_count": len(capabilities) - len(missing),
        "missing_capabilities": missing,
        "external_actions_executed": case.get("external_actions_executed"),
        "workspace_activation_disabled": (
            workspace.get("all_activation_disabled") is True
            and workspace.get("external_actions_executed") == 0
        ),
        "all_scenarios_human_review_required": all(
            row.get("human_review_required") is True for row in scenario_rows
        ),
        "all_scenario_external_actions_disabled": all(
            row.get("automatic_budget_activation_executed") is False
            and row.get("automatic_external_publish_executed") is False
            and row.get("automatic_strategy_mutation_executed") is False
            for row in scenario_rows
        ),
        "post_selection_lane_count": post.get("lane_count"),
        "post_selection_identity_connected": (
            post.get("campaign_id") == case.get("campaign_id")
            and post.get("strategy_id") == case.get("strategy_id")
        ),
        "post_selection_evidence_connected": post.get("same_evidence_spine_across_lanes"),
        "post_selection_activation_disabled": post.get("all_external_actions_disabled"),
        "zero_budget_paid_channels_excluded": case.get("zero_budget_paid_channels_excluded"),
        "causal_revenue_proven": case.get("causal_revenue_proven"),
        "four_a_effect_proven": case.get("four_a_effect_proven"),
        "human_reviews": case.get("human_blind_reviews_observed"),
        "production_outcomes": case.get("production_outcomes_observed"),
        "truth_boundary_present": bool(str(case.get("truth_boundary", "")).strip()),
    }


_SLICES = (
    "capability_coverage",
    "workspace_safety",
    "scenario_human_gate",
    "scenario_action_safety",
    "omnichannel_lane_integrity",
    "campaign_identity_binding",
    "evidence_spine_binding",
    "post_selection_activation",
    "budget_activation_safety",
    "claim_evidence_boundary",
)


def _mutate(dossier: Mapping[str, Any], index: int) -> dict[str, Any]:
    changed = dict(dossier)
    mutation = index % len(_SLICES)
    if mutation == 0:
        changed["capability_count"] = 9
        changed["missing_capabilities"] = ["seo_geo"]
    elif mutation == 1:
        changed["workspace_activation_disabled"] = False
    elif mutation == 2:
        changed["all_scenarios_human_review_required"] = False
    elif mutation == 3:
        changed["all_scenario_external_actions_disabled"] = False
    elif mutation == 4:
        changed["post_selection_lane_count"] = 8
    elif mutation == 5:
        changed["post_selection_identity_connected"] = False
    elif mutation == 6:
        changed["post_selection_evidence_connected"] = False
    elif mutation == 7:
        changed["post_selection_activation_disabled"] = False
    elif mutation == 8:
        if changed["budget"] == "zero":
            changed["zero_budget_paid_channels_excluded"] = False
        else:
            changed["external_actions_executed"] = 1
    else:
        changed["four_a_effect_proven"] = True
    return changed


def mechanical_oracle(dossier: Mapping[str, Any]) -> bool:
    return all(_compiled_checks(dossier).values())


def _compiled_checks(dossier: Mapping[str, Any]) -> dict[str, bool]:
    """Compile heterogeneous evidence into a monotonic binary check vector.

    Negative Boolean evidence such as ``causal_revenue_proven=false`` is a safe
    truth-boundary observation, not a failed check. Normalizing every condition
    to ``true == satisfied`` prevents a small decoder from confusing evidence
    polarity while leaving the underlying dossier available for human review.
    """

    no_unsubstantiated_effect_claim = not (
        dossier.get("human_reviews") == 0
        and dossier.get("production_outcomes") == 0
        and (
            dossier.get("causal_revenue_proven") is not False
            or dossier.get("four_a_effect_proven") is not False
        )
    )
    return {
        "capability_coverage": (
            dossier.get("capability_count") == 10
            and dossier.get("missing_capabilities") == []
        ),
        "external_actions_zero": dossier.get("external_actions_executed") == 0,
        "workspace_safety": dossier.get("workspace_activation_disabled") is True,
        "scenario_human_gate": (
            dossier.get("all_scenarios_human_review_required") is True
        ),
        "scenario_action_safety": (
            dossier.get("all_scenario_external_actions_disabled") is True
        ),
        "omnichannel_lane_integrity": dossier.get("post_selection_lane_count") == 9,
        "campaign_identity_binding": (
            dossier.get("post_selection_identity_connected") is True
        ),
        "evidence_spine_binding": (
            dossier.get("post_selection_evidence_connected") is True
        ),
        "post_selection_activation": (
            dossier.get("post_selection_activation_disabled") is True
        ),
        "zero_budget_paid_channels_excluded": (
            dossier.get("budget") != "zero"
            or dossier.get("zero_budget_paid_channels_excluded") is True
        ),
        "claim_evidence_boundary": no_unsubstantiated_effect_claim,
        "truth_boundary_present": dossier.get("truth_boundary_present") is True,
    }


def build_case_blueprints(lifecycle_matrix: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected = select_stratified_sources(lifecycle_matrix)
    blueprints: list[dict[str, Any]] = []
    for index, source in enumerate(selected):
        original = _dossier(source)
        negative = _mutate(original, index)
        for dossier in (original, negative):
            artifact_sha256 = _digest({"rubric_id": RUBRIC_ID, "dossier": dossier})
            case_id = f"gov-cal-{artifact_sha256[:24]}"
            evaluation_prompt = f"{RUBRIC}\nDOSSIER:{_canonical(dossier)}"
            if len(evaluation_prompt) > 2_000:
                raise LocalJudgeQueueError("embedded calibration prompt exceeds bound")
            blueprints.append(
                {
                    "case_id": case_id,
                    "artifact_sha256": artifact_sha256,
                    "evaluation_prompt": evaluation_prompt,
                    "evidence_locator": f"embedded://judge-calibration/{case_id}",
                    "failure_slice": _SLICES[index % len(_SLICES)],
                    "dossier": dossier,
                }
            )
    if len(blueprints) != 100 or len({row["artifact_sha256"] for row in blueprints}) != 100:
        raise LocalJudgeQueueError("calibration blueprints are not 100 case-distinct artifacts")
    oracle = Counter(mechanical_oracle(row["dossier"]) for row in blueprints)
    if oracle != Counter({True: 50, False: 50}):
        raise LocalJudgeQueueError("calibration blueprint oracle is not balanced 50/50")
    coverage = {
        "source_case_count": len(selected),
        "calibration_case_count": len(blueprints),
        "business_models": sorted({row["business_model"] for row in map(_dossier, selected)}),
        "lifecycles": sorted({row["lifecycle"] for row in map(_dossier, selected)}),
        "budgets": sorted({row["budget"] for row in map(_dossier, selected)}),
        "industry_risks": sorted({row["industry_risk"] for row in map(_dossier, selected)}),
        "industry_count": len({_industry_key(row) for row in selected}),
        "scenario_combination_count": len({_combo(row) for row in selected}),
        "failure_slices": list(_SLICES),
        "oracle_positive_count": oracle[True],
        "oracle_negative_count": oracle[False],
    }
    return blueprints, coverage


def parse_model_judgement(raw: str) -> tuple[bool, str]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise LocalJudgeQueueError("local judge returned malformed JSON") from error
    if not isinstance(payload, Mapping) or set(payload) != {"pass", "reason_code"}:
        raise LocalJudgeQueueError("local judge output keys are invalid")
    if type(payload.get("pass")) is not bool or not _REASON.fullmatch(str(payload.get("reason_code", ""))):
        raise LocalJudgeQueueError("local judge output values are invalid")
    return bool(payload["pass"]), str(payload["reason_code"])


def execute_local_predictions(
    blueprints: Sequence[Mapping[str, Any]], client: object, *, timeout_seconds: float
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cases: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    for blueprint in blueprints:
        checks = _compiled_checks(blueprint["dossier"])
        judge_input = {
            "decision_rule": "pass_is_true_if_and_only_if_every_check_value_is_true",
            "checks": checks,
            "failed_check_ids": [key for key, passed in checks.items() if not passed],
            "all_checks_satisfied": all(checks.values()),
        }
        result = client.complete(  # type: ignore[attr-defined]
            [
                {
                    "role": "system",
                    "content": MODEL_RUBRIC,
                },
                {"role": "user", "content": _canonical(judge_input)},
            ],
            scope=InferenceScope.EVALUATION,
            purpose=RUBRIC_ID,
            max_tokens=64,
            temperature=0,
            timeout_seconds=timeout_seconds,
            official_retry_rounds=0,
        )
        prediction, reason_code = parse_model_judgement(result.content)
        cases.append(
            {
                key: blueprint[key]
                for key in (
                    "case_id",
                    "artifact_sha256",
                    "evaluation_prompt",
                    "evidence_locator",
                    "failure_slice",
                )
            }
            | {"judge_prediction": prediction}
        )
        receipts.append(
            {
                "case_id": blueprint["case_id"],
                "artifact_sha256": blueprint["artifact_sha256"],
                "judge_prediction": prediction,
                "reason_code": reason_code,
                "request_sha256": result.receipt["request_sha256"],
                "response_sha256": result.receipt["normalized_response_sha256"],
                "prompt_tokens": result.usage.get("prompt_tokens"),
                "completion_tokens": result.usage.get("completion_tokens"),
                "compiled_check_vector_sha256": _digest(judge_input),
            }
        )
    predictions = Counter(row["judge_prediction"] for row in cases)
    if predictions[True] < 40 or predictions[False] < 40:
        raise LocalJudgeQueueError(
            "observed local judge predictions are too imbalanced for calibration"
        )
    return cases, receipts


def seal_local_judge_queue(
    *,
    lifecycle_matrix_path: str | Path,
    model_name: str,
    model_digest: str,
    client: object,
    private_source_root: str | Path,
    bundle_root: str | Path,
    status_path: str | Path,
    assignment_seed: str,
    timeout_seconds: float = 60,
) -> dict[str, Any]:
    matrix_path = Path(lifecycle_matrix_path).resolve(strict=True)
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    blueprints, coverage = build_case_blueprints(matrix)
    cases, execution_rows = execute_local_predictions(
        blueprints, client, timeout_seconds=timeout_seconds
    )
    private_root = Path(private_source_root).resolve()
    if private_root.exists() and any(private_root.iterdir()):
        raise LocalJudgeQueueError("private judge source directory must be empty")
    private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_root.chmod(0o700)
    cases_path = private_root / "judge-calibration-cases-private.json"
    execution_path = private_root / "model-judge-execution-private.json"
    atomic_write_text(cases_path, json.dumps(cases, indent=2, sort_keys=True) + "\n")
    atomic_write_text(
        execution_path,
        json.dumps(
            {
                "schema": "ProofLaunchLocalGovernanceJudgeExecutionPrivateV1",
                "rubric_id": RUBRIC_ID,
                "model": {"provider": "ollama_local", "name": model_name, "digest": model_digest},
                "rows": execution_rows,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    cases_path.chmod(0o600)
    execution_path.chmod(0o600)
    bundle_receipt = compile_judge_calibration_bundle(
        cases,
        bundle_root,
        assignment_seed=assignment_seed,
    )
    prediction_counts = Counter(row["judge_prediction"] for row in cases)
    status: dict[str, Any] = {
        "schema": SCHEMA,
        "rubric_id": RUBRIC_ID,
        "source": {
            "path": _safe_display_path(matrix_path),
            "file_sha256": _file_digest(matrix_path),
            "content_sha256": matrix["content_sha256"],
            "data_class": "synthetic_representative",
        },
        "coverage": coverage,
        "model": {
            "provider": "ollama_local",
            "name": model_name,
            "digest": model_digest,
            "radeon_local_inference": False,
        },
        "observed_model_call_count": len(execution_rows),
        "observed_prompt_token_count": sum(int(row["prompt_tokens"] or 0) for row in execution_rows),
        "observed_completion_token_count": sum(int(row["completion_tokens"] or 0) for row in execution_rows),
        "judge_prediction_positive_count": prediction_counts[True],
        "judge_prediction_negative_count": prediction_counts[False],
        "private_case_file_sha256": _file_digest(cases_path),
        "private_execution_file_sha256": _file_digest(execution_path),
        "public_packet_content_sha256": bundle_receipt["public_content_sha256"],
        "private_mapping_content_sha256": bundle_receipt["private_content_sha256"],
        "expected_human_label_count": bundle_receipt["expected_review_count"],
        "real_human_label_count": 0,
        "judge_calibrated": False,
        "automatic_judge_promotion_enabled": False,
        "cloud_api_calls": 0,
        "network_download_performed": False,
        "external_publish_executed": False,
        "truth_boundary": (
            "This receipt proves 100 digest-pinned localhost model judgements over a balanced "
            "synthetic representative governance queue and an empty 300-label human packet. "
            "It is not human calibration, creative-quality evidence, production traffic, "
            "Radeon inference, 4A preference, causal lift, revenue or Top-1 evidence."
        ),
    }
    status["content_sha256"] = _digest(status)
    output = Path(status_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        output,
        json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return status


__all__ = [
    "LocalJudgeQueueError",
    "RUBRIC",
    "RUBRIC_ID",
    "MODEL_RUBRIC",
    "SCHEMA",
    "build_case_blueprints",
    "execute_local_predictions",
    "mechanical_oracle",
    "parse_model_judgement",
    "seal_local_judge_queue",
    "select_stratified_sources",
]
