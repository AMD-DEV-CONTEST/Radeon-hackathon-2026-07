from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

MAX_INPUT_BYTES = 50 * 1024 * 1024
FIELD_ALIASES = {
    "localization": ("localization", "root_cause_entity", "root_cause_service", "root_cause"),
    "identification": ("identification", "fault_type", "failure_type"),
    "reason": ("reason", "causal_chain", "evidence_checkpoints"),
}


class EvaluationError(ValueError):
    pass


def load_cases(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise EvaluationError(f"input file not found: {path}")
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise EvaluationError(f"input file exceeds {MAX_INPUT_BYTES} bytes: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"cannot read JSON input {path}: {exc}") from exc

    if isinstance(payload, dict) and "cases" in payload:
        raw_cases = payload["cases"]
    elif isinstance(payload, list):
        raw_cases = payload
    elif isinstance(payload, dict) and _case_id(payload) is not None:
        raw_cases = [payload]
    elif isinstance(payload, dict):
        raw_cases = [dict(value, case_id=key) for key, value in payload.items() if isinstance(value, dict)]
    else:
        raise EvaluationError("JSON must be a case object, a case list, a cases envelope, or an ID-to-case object")
    if not isinstance(raw_cases, list):
        raise EvaluationError("cases must be a list")

    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, value in enumerate(raw_cases):
        if not isinstance(value, dict):
            raise EvaluationError(f"case[{index}] must be an object")
        case_id = _case_id(value)
        if case_id is None:
            raise EvaluationError(f"case[{index}] requires case_id")
        if case_id in seen:
            raise EvaluationError(f"duplicate case_id: {case_id}")
        seen.add(case_id)
        cases.append({**value, "case_id": case_id})
    return cases


def evaluate(predictions: list[dict[str, Any]], ground_truth: list[dict[str, Any]]) -> dict[str, Any]:
    prediction_map = _index_cases(predictions, "prediction")
    truth_map = _index_cases(ground_truth, "ground truth")
    if not truth_map:
        raise EvaluationError("ground truth must contain at least one case")

    case_results: list[dict[str, Any]] = []
    for case_id, truth in truth_map.items():
        prediction = prediction_map.get(case_id, {})
        localization = _set_f1(_field(prediction, "localization"), _required_field(truth, "localization", case_id))
        identification = _set_f1(
            _field(prediction, "identification"), _required_field(truth, "identification", case_id)
        )
        reason = _checkpoint_recall(_field(prediction, "reason"), _required_field(truth, "reason", case_id))
        case_results.append(
            {
                "case_id": case_id,
                "prediction_present": case_id in prediction_map,
                "localization": round(localization, 4),
                "identification": round(identification, 4),
                "reason": round(reason, 4),
                "overall": round((localization + identification + reason) / 3, 4),
            }
        )

    count = len(case_results)
    aggregate = {
        "ground_truth_cases": count,
        "prediction_cases": len(prediction_map),
        "matched_cases": sum(item["prediction_present"] for item in case_results),
        "missing_predictions": sum(not item["prediction_present"] for item in case_results),
        "extra_predictions": len(set(prediction_map) - set(truth_map)),
        "localization": round(sum(item["localization"] for item in case_results) / count, 4),
        "identification": round(sum(item["identification"] for item in case_results) / count, 4),
        "reason": round(sum(item["reason"] for item in case_results) / count, 4),
        "overall": round(sum(item["overall"] for item in case_results) / count, 4),
    }
    return {
        "schema_version": 1,
        "evaluator": "agenticopseval-compatible-lightweight",
        "official_score": False,
        "metrics": {
            "localization": "normalized exact-set F1",
            "identification": "normalized exact-set F1",
            "reason": "ground-truth evidence-checkpoint recall at 70% token coverage",
        },
        "aggregate": aggregate,
        "cases": case_results,
    }


def _index_cases(cases: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(cases):
        if not isinstance(value, dict):
            raise EvaluationError(f"{label} case[{index}] must be an object")
        case_id = _case_id(value)
        if case_id is None:
            raise EvaluationError(f"{label} case[{index}] requires case_id")
        if case_id in indexed:
            raise EvaluationError(f"duplicate {label} case_id: {case_id}")
        indexed[case_id] = value
    return indexed


def _case_id(value: dict[str, Any]) -> str | None:
    for key in ("case_id", "caseId", "task_id", "id"):
        candidate = value.get(key)
        if isinstance(candidate, (str, int)) and str(candidate).strip():
            return str(candidate).strip()
    return None


def _field(case: dict[str, Any], dimension: str) -> list[str]:
    for key in FIELD_ALIASES[dimension]:
        if key in case:
            return _items(case[key], key)
    return []


def _required_field(case: dict[str, Any], dimension: str, case_id: str) -> list[str]:
    values = _field(case, dimension)
    if not values:
        raise EvaluationError(f"ground truth case {case_id} requires non-empty {dimension}")
    return values


def _items(value: Any, field: str) -> list[str]:
    values = value if isinstance(value, list) else [value]
    rendered: list[str] = []
    for item in values:
        if not isinstance(item, (str, int, float)) or isinstance(item, bool):
            raise EvaluationError(f"{field} must be a string or a list of scalar values")
        clean = str(item).strip()
        if clean:
            rendered.append(clean)
    return rendered


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold(), flags=re.UNICODE))


def _set_f1(predicted: list[str], expected: list[str]) -> float:
    predicted_set = {_normalize(value) for value in predicted if _normalize(value)}
    expected_set = {_normalize(value) for value in expected if _normalize(value)}
    if not expected_set:
        return 0.0
    if not predicted_set:
        return 0.0
    matched = len(predicted_set & expected_set)
    precision = matched / len(predicted_set)
    recall = matched / len(expected_set)
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def _checkpoint_recall(predicted: list[str], checkpoints: list[str]) -> float:
    normalized_prediction = _normalize(" ".join(predicted))
    prediction_tokens = set(normalized_prediction.split())
    if not prediction_tokens:
        return 0.0
    matched = 0
    for checkpoint in checkpoints:
        normalized_checkpoint = _normalize(checkpoint)
        checkpoint_tokens = set(normalized_checkpoint.split())
        if normalized_checkpoint and (
            normalized_checkpoint in normalized_prediction
            or len(checkpoint_tokens & prediction_tokens) / len(checkpoint_tokens) >= 0.7
        ):
            matched += 1
    return matched / len(checkpoints)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Score user-supplied incident predictions with lightweight AgenticOpsEval-compatible metrics."
    )
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--minimum-overall", type=float, default=0.0)
    args = parser.parse_args(argv)
    if not 0 <= args.minimum_overall <= 1:
        parser.error("--minimum-overall must be between 0 and 1")

    result = evaluate(load_cases(args.predictions), load_cases(args.ground_truth))
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if result["aggregate"]["overall"] >= args.minimum_overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
