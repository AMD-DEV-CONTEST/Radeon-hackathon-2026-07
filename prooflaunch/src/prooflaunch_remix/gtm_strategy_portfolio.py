from __future__ import annotations

import hashlib
import itertools
import json
import re
from typing import Any, Mapping, Sequence

from .gtm_strategy_challenger import (
    GTMStrategyChallengerError,
    extract_strategy_candidate,
    strategy_candidate_failures,
)


class GTMStrategyPortfolioError(ValueError):
    """A scenario, candidate, or portfolio receipt violated the frozen contract."""


CASES_SCHEMA = "ProofLaunchZeroBudgetStrategyPortfolioCasesV1"
CANDIDATE_SCHEMA = "ProofLaunchZeroBudgetStrategyPortfolioCandidateV1"
RECEIPT_SCHEMA = "ProofLaunchLocalStrategyPortfolioReceiptV1"
QUALITY_AUDIT_SCHEMA = "ProofLaunchLocalStrategyPortfolioQualityAuditV1"
_SCENARIO_FIELDS = frozenset(
    {
        "case_id",
        "product_name",
        "product_characteristic",
        "business_model",
        "lifecycle",
        "industry",
        "industry_risk",
        "market",
        "required_primary_channel",
        "icp",
        "goal",
    }
)
_BINDING_FIELDS = frozenset(
    {
        "case_id",
        "product_name",
        "business_model",
        "lifecycle",
        "industry",
        "industry_risk",
        "market",
        "required_primary_channel",
        "icp",
    }
)
_CORE_FIELDS = frozenset(
    {
        "strategy",
        "primary_channel",
        "channel_rationale",
        "zero_budget_loop",
        "experiment",
        "human_gate",
        "unsupported_claims",
    }
)
_BUSINESS_MODELS = frozenset({"b2b", "b2c"})
_LIFECYCLES = frozenset({"pre_pmf", "launch", "growth", "mature"})
_RISKS = frozenset({"standard", "high_regulation"})
_CHANNELS = frozenset({"LinkedIn", "community", "partner", "owned"})
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _bounded_text(value: object, field: str, *, minimum: int, maximum: int) -> str:
    if not isinstance(value, str):
        raise GTMStrategyPortfolioError(f"{field} must be a string")
    normalized = re.sub(r"\s+", " ", value.strip())
    if not minimum <= len(normalized) <= maximum or "\x00" in normalized:
        raise GTMStrategyPortfolioError(
            f"{field} must contain {minimum}..{maximum} safe characters"
        )
    return normalized


def validate_scenario(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or frozenset(value) != _SCENARIO_FIELDS:
        raise GTMStrategyPortfolioError("scenario fields must match the frozen schema exactly")
    case_id = _bounded_text(value.get("case_id"), "case_id", minimum=3, maximum=64)
    if not _SAFE_ID.fullmatch(case_id):
        raise GTMStrategyPortfolioError("case_id must be a lowercase hyphenated identifier")
    scenario = {
        "case_id": case_id,
        "product_name": _bounded_text(
            value.get("product_name"), "product_name", minimum=2, maximum=120
        ),
        "product_characteristic": _bounded_text(
            value.get("product_characteristic"),
            "product_characteristic",
            minimum=24,
            maximum=500,
        ),
        "business_model": str(value.get("business_model", "")),
        "lifecycle": str(value.get("lifecycle", "")),
        "industry": _bounded_text(
            value.get("industry"), "industry", minimum=3, maximum=160
        ),
        "industry_risk": str(value.get("industry_risk", "")),
        "market": _bounded_text(value.get("market"), "market", minimum=2, maximum=120),
        "required_primary_channel": str(value.get("required_primary_channel", "")),
        "icp": _bounded_text(value.get("icp"), "icp", minimum=16, maximum=300),
        "goal": _bounded_text(value.get("goal"), "goal", minimum=16, maximum=300),
    }
    if scenario["business_model"] not in _BUSINESS_MODELS:
        raise GTMStrategyPortfolioError("business_model must be b2b or b2c")
    if scenario["lifecycle"] not in _LIFECYCLES:
        raise GTMStrategyPortfolioError("lifecycle must use the frozen vocabulary")
    if scenario["industry_risk"] not in _RISKS:
        raise GTMStrategyPortfolioError("industry_risk must use the frozen vocabulary")
    if scenario["required_primary_channel"] not in _CHANNELS:
        raise GTMStrategyPortfolioError("required_primary_channel must use the frozen vocabulary")
    return scenario


def load_portfolio_cases(value: object) -> list[dict[str, str]]:
    if not isinstance(value, Mapping) or frozenset(value) != {"schema", "cases"}:
        raise GTMStrategyPortfolioError("portfolio case file fields are invalid")
    if value.get("schema") != CASES_SCHEMA:
        raise GTMStrategyPortfolioError("portfolio case file schema is invalid")
    raw_cases = value.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) != 8:
        raise GTMStrategyPortfolioError("portfolio requires exactly eight frozen cases")
    cases = [validate_scenario(case) for case in raw_cases]
    ids = [case["case_id"] for case in cases]
    if len(set(ids)) != len(ids):
        raise GTMStrategyPortfolioError("portfolio case IDs must be unique")
    if {case["business_model"] for case in cases} != _BUSINESS_MODELS:
        raise GTMStrategyPortfolioError("portfolio must cover B2B and B2C")
    if {case["lifecycle"] for case in cases} != _LIFECYCLES:
        raise GTMStrategyPortfolioError("portfolio must cover all four lifecycle stages")
    if {case["industry_risk"] for case in cases} != _RISKS:
        raise GTMStrategyPortfolioError("portfolio must cover standard and high-regulation work")
    channels = [case["required_primary_channel"] for case in cases]
    if set(channels) != _CHANNELS or max(channels.count(channel) for channel in _CHANNELS) > 2:
        raise GTMStrategyPortfolioError(
            "portfolio context router must cover all four primary channels without collapse"
        )
    return cases


def expected_binding(scenario: Mapping[str, str]) -> dict[str, str]:
    return {field: str(scenario[field]) for field in sorted(_BINDING_FIELDS)}


def portfolio_candidate_failures(
    value: object, scenario: Mapping[str, str]
) -> tuple[str, ...]:
    failures: list[str] = []
    if not isinstance(value, Mapping):
        return ("candidate must be an object",)
    if frozenset(value) != _CORE_FIELDS | {"scenario_binding"}:
        failures.append("candidate fields must match the portfolio schema exactly")
    binding = value.get("scenario_binding")
    if not isinstance(binding, Mapping) or frozenset(binding) != _BINDING_FIELDS:
        failures.append("scenario_binding fields must match the frozen schema exactly")
    elif dict(binding) != expected_binding(scenario):
        failures.append("scenario_binding must reproduce the supplied scenario exactly")
    core = {field: value.get(field) for field in _CORE_FIELDS}
    failures.extend(strategy_candidate_failures(core))
    if value.get("primary_channel") != scenario.get("required_primary_channel"):
        failures.append("primary_channel must match the deterministic context route")
    return tuple(dict.fromkeys(failures))


def validate_portfolio_candidate(
    value: object, scenario: Mapping[str, str]
) -> dict[str, Any]:
    failures = portfolio_candidate_failures(value, scenario)
    if failures:
        raise GTMStrategyPortfolioError("; ".join(failures))
    assert isinstance(value, Mapping)
    candidate = {"schema": CANDIDATE_SCHEMA, **dict(value)}
    candidate["content_sha256"] = digest(candidate)
    return candidate


def build_task_prompt(scenario: Mapping[str, str]) -> str:
    case = validate_scenario(scenario)
    binding = expected_binding(case)
    return f"""Design a zero-paid-media GTM experiment for this frozen scenario:
{json.dumps(case, ensure_ascii=False, sort_keys=True)}

Return exactly these eight top-level fields:
- scenario_binding: reproduce this object byte-for-value as JSON fields: {json.dumps(binding, ensure_ascii=False, sort_keys=True)}
- strategy: 80-600 characters; name the supplied ICP, product name and product characteristic differentiator, without an effect claim.
- primary_channel: exactly {case['required_primary_channel']}, selected by the deterministic context router for this frozen case.
- channel_rationale: 48-500 characters; describe audience behavior to investigate, not performance.
- zero_budget_loop: exactly four 40-420 character steps. Include at least two concrete earned mechanisms, a reusable evidence/diagnostic/checklist/benchmark/template/teardown/worksheet/proof artifact, and explicit qualified-conversation logging. No paid distribution, vanity-only final step, or case-study performance claim.
- experiment: object with exactly treatment, comparable_baseline, observation_window_days, primary_metric, decision_rule. The baseline must explicitly say that the same eligible account pool is randomly split 50/50 into a same-window treatment and holdout; comparing different communities or historical traffic is invalid. Use 7-30 days and primary_metric exactly qualified_conversations. The rule must preregister a non-zero minimum sample threshold but may not report an achieved effect.
- human_gate: object with exactly role, decision, artifact; decision exactly approve_or_reject, role must be named, and artifact must include the qualified-conversation ledger.
- unsupported_claims: array containing 1-8 claims the team explicitly rejects.

The experiment must be preregistered, rights-safe, executable without paid media, appropriate to the supplied business model, lifecycle and risk, and must not imply that any result has already occurred."""


def _attempt_record(
    attempt: Mapping[str, Any],
    *,
    scenario: Mapping[str, str],
    index: int,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    raw_output = str(attempt.get("raw_output", ""))
    parsed: dict[str, Any] | None
    try:
        parsed = extract_strategy_candidate(raw_output)
        failures = portfolio_candidate_failures(parsed, scenario)
    except (GTMStrategyChallengerError, GTMStrategyPortfolioError) as error:
        parsed = None
        failures = (str(error),)
    accepted = not failures
    candidate = validate_portfolio_candidate(parsed, scenario) if accepted else None
    return (
        {
            "attempt": index,
            "kind": "draft" if index == 1 else "bounded_repair",
            "elapsed_seconds": round(float(attempt.get("elapsed_seconds", 0.0)), 6),
            "generated_token_count": int(attempt.get("generated_token_count", 0)),
            "raw_output_sha256": hashlib.sha256(raw_output.encode("utf-8")).hexdigest(),
            "json_complete": parsed is not None,
            "candidate_snapshot": parsed,
            "accepted": accepted,
            "failures": list(failures),
        },
        candidate,
    )


def compile_strategy_portfolio_receipt(
    *,
    model_id: str,
    model_revision: str,
    model_manifest_sha256: str,
    device_family: str,
    cases: Sequence[Mapping[str, str]],
    case_attempts: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    normalized_cases = [validate_scenario(case) for case in cases]
    if len(normalized_cases) != 8 or not _SHA256.fullmatch(model_manifest_sha256):
        raise GTMStrategyPortfolioError("model identity or portfolio size is invalid")
    results: list[dict[str, Any]] = []
    accepted_count = 0
    for scenario in normalized_cases:
        attempts = case_attempts.get(scenario["case_id"])
        if not isinstance(attempts, Sequence) or isinstance(attempts, (str, bytes)):
            raise GTMStrategyPortfolioError("every portfolio case requires attempts")
        if not 1 <= len(attempts) <= 2:
            raise GTMStrategyPortfolioError("each case permits one draft and one repair")
        normalized_attempts: list[dict[str, Any]] = []
        accepted_candidate = None
        for index, attempt in enumerate(attempts, start=1):
            record, candidate = _attempt_record(attempt, scenario=scenario, index=index)
            normalized_attempts.append(record)
            if candidate is not None:
                accepted_candidate = candidate
            if candidate is not None and index != len(attempts):
                raise GTMStrategyPortfolioError("execution continued after an accepted case")
        if accepted_candidate is not None:
            accepted_count += 1
        prompt = build_task_prompt(scenario)
        results.append(
            {
                "case_id": scenario["case_id"],
                "scenario": scenario,
                "scenario_sha256": digest(scenario),
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "attempts": normalized_attempts,
                "accepted": accepted_candidate is not None,
                "accepted_candidate": accepted_candidate,
            }
        )
    axes = {
        "business_models": sorted({case["business_model"] for case in normalized_cases}),
        "lifecycles": sorted({case["lifecycle"] for case in normalized_cases}),
        "industry_risks": sorted({case["industry_risk"] for case in normalized_cases}),
        "industries": sorted({case["industry"] for case in normalized_cases}),
        "markets": sorted({case["market"] for case in normalized_cases}),
        "primary_channels": sorted(
            {case["required_primary_channel"] for case in normalized_cases}
        ),
    }
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "status": "completed_all_accepted" if accepted_count == len(results) else "completed_with_rejections",
        "execution": {
            "provider": "mlx_local",
            "device_family": device_family,
            "model_id": model_id,
            "model_revision": model_revision,
            "model_manifest_sha256": model_manifest_sha256,
            "model_load_count": 1,
            "network_download_performed": False,
            "cloud_api_calls": 0,
            "training_observed": False,
            "radeon_local_inference_observed": False,
        },
        "case_count": len(results),
        "accepted_case_count": accepted_count,
        "all_cases_accepted": accepted_count == len(results),
        "coverage_axes": axes,
        "results": results,
        "automatic_release_authority": False,
        "automatic_training_admission": False,
        "four_a_claim_eligible": False,
        "top1_claim_eligible": False,
        "causal_effect_claim_eligible": False,
        "any_industry_generalization_claim_eligible": False,
        "truth_boundary": (
            "This receipt proves bounded offline local candidate generation and deterministic "
            "contract validation on eight frozen representative scenarios. It is not training, "
            "Radeon execution, independent human preference, production effect, causal lift, "
            "revenue, 4A quality, Top-1 standing, or universal industry generalization."
        ),
    }
    receipt["content_sha256"] = digest(receipt)
    return receipt


def validate_strategy_portfolio_receipt(value: object) -> None:
    if not isinstance(value, Mapping) or value.get("schema") != RECEIPT_SCHEMA:
        raise GTMStrategyPortfolioError("portfolio receipt schema is invalid")
    unsigned = dict(value)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != digest(unsigned):
        raise GTMStrategyPortfolioError("portfolio receipt digest is invalid")
    execution = value.get("execution")
    if not isinstance(execution, Mapping) or execution.get("model_load_count") != 1:
        raise GTMStrategyPortfolioError("portfolio execution identity is invalid")
    for field in (
        "network_download_performed",
        "training_observed",
        "radeon_local_inference_observed",
    ):
        if execution.get(field) is not False:
            raise GTMStrategyPortfolioError(f"portfolio execution boundary {field} is invalid")
    if execution.get("cloud_api_calls") != 0:
        raise GTMStrategyPortfolioError("portfolio cloud call boundary is invalid")
    for field in (
        "automatic_release_authority",
        "automatic_training_admission",
        "four_a_claim_eligible",
        "top1_claim_eligible",
        "causal_effect_claim_eligible",
        "any_industry_generalization_claim_eligible",
    ):
        if value.get(field) is not False:
            raise GTMStrategyPortfolioError(f"portfolio authority boundary {field} is invalid")
    results = value.get("results")
    if not isinstance(results, list) or len(results) != 8:
        raise GTMStrategyPortfolioError("portfolio result count is invalid")
    accepted = 0
    for result in results:
        if not isinstance(result, Mapping):
            raise GTMStrategyPortfolioError("portfolio result must be an object")
        scenario = validate_scenario(result.get("scenario"))
        if result.get("case_id") != scenario["case_id"]:
            raise GTMStrategyPortfolioError("portfolio result case binding is invalid")
        if result.get("scenario_sha256") != digest(scenario):
            raise GTMStrategyPortfolioError("portfolio scenario digest is invalid")
        prompt = build_task_prompt(scenario)
        if result.get("prompt_sha256") != hashlib.sha256(prompt.encode("utf-8")).hexdigest():
            raise GTMStrategyPortfolioError("portfolio prompt digest is invalid")
        candidate = result.get("accepted_candidate")
        if result.get("accepted") is True:
            if not isinstance(candidate, Mapping) or candidate.get("schema") != CANDIDATE_SCHEMA:
                raise GTMStrategyPortfolioError("accepted portfolio candidate is invalid")
            candidate_unsigned = dict(candidate)
            candidate_digest = candidate_unsigned.pop("content_sha256", None)
            if candidate_digest != digest(candidate_unsigned):
                raise GTMStrategyPortfolioError("portfolio candidate digest is invalid")
            candidate_unsigned.pop("schema", None)
            validate_portfolio_candidate(candidate_unsigned, scenario)
            accepted += 1
        elif candidate is not None:
            raise GTMStrategyPortfolioError("rejected portfolio case retained a candidate")
    if value.get("accepted_case_count") != accepted:
        raise GTMStrategyPortfolioError("portfolio accepted count is invalid")
    if value.get("all_cases_accepted") is not (accepted == len(results)):
        raise GTMStrategyPortfolioError("portfolio completion flag is invalid")


def _candidate_token_set(candidate: Mapping[str, Any]) -> set[str]:
    text = " ".join(
        [
            str(candidate.get("strategy", "")),
            str(candidate.get("channel_rationale", "")),
            *[str(step) for step in candidate.get("zero_budget_loop", [])],
        ]
    ).casefold()
    return set(re.findall(r"[a-z0-9]+", text))


def compile_strategy_portfolio_quality_audit(
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    validate_strategy_portfolio_receipt(receipt)
    results = receipt["results"]
    candidates = [
        result["accepted_candidate"]
        for result in results
        if result.get("accepted") is True
    ]
    channel_distribution = {
        channel: sum(candidate["primary_channel"] == channel for candidate in candidates)
        for channel in sorted(_CHANNELS)
    }
    token_rows = [
        (result["case_id"], _candidate_token_set(result["accepted_candidate"]))
        for result in results
        if result.get("accepted") is True
    ]
    pairwise: list[dict[str, Any]] = []
    for (left_id, left), (right_id, right) in itertools.combinations(token_rows, 2):
        union = left | right
        score = len(left & right) / len(union) if union else 1.0
        pairwise.append(
            {
                "left_case_id": left_id,
                "right_case_id": right_id,
                "jaccard": round(score, 6),
            }
        )
    pairwise.sort(key=lambda row: (-row["jaccard"], row["left_case_id"], row["right_case_id"]))
    maximum_jaccard = pairwise[0]["jaccard"] if pairwise else 1.0
    unique_strategy_count = len({candidate["strategy"] for candidate in candidates})
    channel_gate = channel_distribution == {
        "LinkedIn": 2,
        "community": 2,
        "owned": 2,
        "partner": 2,
    }
    distinctive_gate = maximum_jaccard <= 0.60 and unique_strategy_count == 8
    gate_passed = (
        receipt.get("all_cases_accepted") is True
        and len(candidates) == 8
        and channel_gate
        and distinctive_gate
    )
    audit: dict[str, Any] = {
        "schema": QUALITY_AUDIT_SCHEMA,
        "status": "passed" if gate_passed else "failed",
        "source_receipt_content_sha256": receipt["content_sha256"],
        "case_count": len(results),
        "accepted_case_count": len(candidates),
        "channel_distribution": channel_distribution,
        "required_channel_distribution": {
            "LinkedIn": 2,
            "community": 2,
            "owned": 2,
            "partner": 2,
        },
        "channel_diversity_gate_passed": channel_gate,
        "unique_strategy_count": unique_strategy_count,
        "maximum_pairwise_content_jaccard": maximum_jaccard,
        "maximum_allowed_pairwise_content_jaccard": 0.60,
        "most_similar_pair": pairwise[0] if pairwise else None,
        "distinctiveness_gate_passed": distinctive_gate,
        "portfolio_quality_gate_passed": gate_passed,
        "human_preference_observed": False,
        "production_effect_observed": False,
        "automatic_release_authority": False,
        "truth_boundary": (
            "This audit proves contract acceptance, deterministic channel-distribution and "
            "token-set distinctiveness gates for eight frozen local outputs. It is not a human "
            "quality judgment, production effect, causal lift, 4A quality, Top-1 standing, or "
            "universal industry generalization."
        ),
    }
    audit["content_sha256"] = digest(audit)
    return audit


def validate_strategy_portfolio_quality_audit(
    audit: Mapping[str, Any], receipt: Mapping[str, Any]
) -> None:
    unsigned = dict(audit)
    supplied = unsigned.pop("content_sha256", None)
    if audit.get("schema") != QUALITY_AUDIT_SCHEMA or supplied != digest(unsigned):
        raise GTMStrategyPortfolioError("portfolio quality audit digest is invalid")
    expected = compile_strategy_portfolio_quality_audit(receipt)
    if dict(audit) != expected:
        raise GTMStrategyPortfolioError("portfolio quality audit does not match the source receipt")
