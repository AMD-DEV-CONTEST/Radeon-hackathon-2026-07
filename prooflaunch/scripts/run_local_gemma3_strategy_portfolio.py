#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.gtm_strategy_portfolio import (  # noqa: E402
    build_task_prompt,
    canonical_json,
    compile_strategy_portfolio_receipt,
    digest,
    load_portfolio_cases,
    portfolio_candidate_failures,
    validate_strategy_portfolio_receipt,
)


RUNNER_PATH = ROOT / "scripts/run_local_gemma3_strategy_challenger.py"
SPEC = importlib.util.spec_from_file_location("prooflaunch_local_strategy_runner", RUNNER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("failed to load the local strategy runner")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def _failures(raw_output: str, scenario: dict[str, str]) -> tuple[str, ...]:
    try:
        parsed = RUNNER.extract_strategy_candidate(raw_output)
        return portfolio_candidate_failures(parsed, scenario)
    except Exception as error:
        return (str(error),)


def _repair_prompt(
    task_prompt: str, raw_output: str, failures: tuple[str, ...]
) -> str:
    mechanical_literals = ""
    if any("comparable_baseline" in failure for failure in failures):
        mechanical_literals += (
            "\nFor experiment.comparable_baseline, use one sentence containing these exact "
            "literal phrases: 'same eligible account pool', 'randomly split 50/50', "
            "'same-window treatment', and 'holdout'."
        )
    if any("unproven effect claim" in failure for failure in failures):
        mechanical_literals += (
            "\nRemove all outcome verbs such as improve, increase, reduce, boost, grow, or "
            "guarantee from every field except unsupported_claims."
        )
    return (
        task_prompt
        + "\n\nThe draft failed the deterministic Harness for exactly these reasons:\n- "
        + "\n- ".join(failures)
        + mechanical_literals
        + "\n\nRewrite the full JSON from scratch. Reproduce scenario_binding exactly and "
        + "preserve no unsupported performance claim. The previous draft was:\n"
        + raw_output[:7_000]
    )


def _load_prior_results(
    path: Path,
    *,
    cases: list[dict[str, str]],
    revision: str,
    manifest_sha256: str,
) -> dict[str, dict[str, Any]]:
    prior = json.loads(path.read_text(encoding="utf-8"))
    validate_strategy_portfolio_receipt(prior)
    execution = prior["execution"]
    if (
        execution.get("model_id") != RUNNER.MODEL_ID
        or execution.get("model_revision") != revision
        or execution.get("model_manifest_sha256") != manifest_sha256
    ):
        raise SystemExit("--resume-from model identity differs from the current snapshot")
    expected = {case["case_id"]: digest(case) for case in cases}
    results = {str(result["case_id"]): result for result in prior["results"]}
    if set(results) != set(expected):
        raise SystemExit("--resume-from portfolio case IDs differ from the frozen cases")
    for case_id, scenario_sha256 in expected.items():
        if results[case_id].get("scenario_sha256") != scenario_sha256:
            raise SystemExit("--resume-from scenario identity differs from the frozen cases")
    return results


def _prior_candidate_as_attempt(result: dict[str, Any]) -> dict[str, Any]:
    candidate = result.get("accepted_candidate")
    if isinstance(candidate, dict):
        candidate = dict(candidate)
        candidate.pop("schema", None)
        candidate.pop("content_sha256", None)
        source = "verified_prior_accepted_candidate"
    else:
        attempts = result.get("attempts")
        snapshot = attempts[-1].get("candidate_snapshot") if isinstance(attempts, list) and attempts else None
        if not isinstance(snapshot, dict):
            raise SystemExit("--resume-from rejected case has no repairable candidate snapshot")
        candidate = snapshot
        source = "verified_prior_rejected_candidate"
    return {
        "raw_output": canonical_json(candidate),
        "elapsed_seconds": 0.0,
        "generated_token_count": 0,
        "source": source,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run eight frozen zero-budget GTM scenarios through one offline MLX Gemma 3 load."
    )
    parser.add_argument("--model-path", required=True)
    parser.add_argument(
        "--cases",
        default=str(ROOT / "config/local-gemma3-zero-budget-strategy-portfolio-v1.json"),
    )
    parser.add_argument(
        "--output",
        default=str(ROOT / "evidence/v10/local-gemma3-12b-strategy-portfolio-v1.json"),
    )
    parser.add_argument(
        "--resume-from",
        help="Verified prior portfolio receipt; accepted cases are revalidated and only rejected cases receive one new repair.",
    )
    args = parser.parse_args()
    snapshot = Path(args.model_path).expanduser().resolve(strict=True)
    if not snapshot.is_dir():
        raise SystemExit("--model-path must be a local snapshot directory")
    revision, manifest_sha256 = RUNNER._model_manifest(snapshot)
    cases_path = Path(args.cases).expanduser().resolve(strict=True)
    cases = load_portfolio_cases(json.loads(cases_path.read_text(encoding="utf-8")))
    prior_results = (
        _load_prior_results(
            Path(args.resume_from).expanduser().resolve(strict=True),
            cases=cases,
            revision=revision,
            manifest_sha256=manifest_sha256,
        )
        if args.resume_from
        else {}
    )
    output = Path(args.output).expanduser().resolve()
    try:
        output.relative_to(ROOT)
    except ValueError as error:
        raise SystemExit("--output must remain inside the project root") from error

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    from mlx_lm import load

    model, tokenizer = load(str(snapshot), lazy=False)
    case_attempts: dict[str, list[dict[str, Any]]] = {}
    for index, scenario in enumerate(cases, start=1):
        task_prompt = build_task_prompt(scenario)
        prior_result = prior_results.get(scenario["case_id"])
        if prior_result is not None:
            attempts = [_prior_candidate_as_attempt(prior_result)]
            if prior_result.get("accepted") is True:
                print(
                    f"[{index}/{len(cases)}] {scenario['case_id']} carry verified accepted case",
                    flush=True,
                )
                case_attempts[scenario["case_id"]] = attempts
                continue
            print(
                f"[{index}/{len(cases)}] {scenario['case_id']} resume rejected case",
                flush=True,
            )
        else:
            print(f"[{index}/{len(cases)}] {scenario['case_id']} draft", flush=True)
            attempts = [RUNNER._generate(model, tokenizer, task_prompt, max_tokens=768)]
        failures = _failures(attempts[0]["raw_output"], scenario)
        if failures:
            print(
                f"[{index}/{len(cases)}] {scenario['case_id']} repair: "
                + " | ".join(failures),
                flush=True,
            )
            attempts.append(
                RUNNER._generate(
                    model,
                    tokenizer,
                    _repair_prompt(task_prompt, attempts[0]["raw_output"], failures),
                    max_tokens=896,
                )
            )
        case_attempts[scenario["case_id"]] = attempts

    receipt = compile_strategy_portfolio_receipt(
        model_id=RUNNER.MODEL_ID,
        model_revision=revision,
        model_manifest_sha256=manifest_sha256,
        device_family="Apple Metal",
        cases=cases,
        case_attempts=case_attempts,
    )
    validate_strategy_portfolio_receipt(receipt)
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        output,
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "status": receipt["status"],
                "case_count": receipt["case_count"],
                "accepted_case_count": receipt["accepted_case_count"],
                "content_sha256": receipt["content_sha256"],
                "model_load_count": 1,
                "network_download_performed": False,
                "cloud_api_calls": 0,
                "training_observed": False,
                "radeon_local_inference_observed": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if receipt["all_cases_accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
