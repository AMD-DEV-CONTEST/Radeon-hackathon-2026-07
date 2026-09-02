#!/usr/bin/env python3
"""Exercise fail-closed Radeon boundaries without copying private bodies into the aggregate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_case(
    *,
    case_id: str,
    command: list[str],
    cwd: Path,
    output_directory: Path,
    environment: dict[str, str],
) -> dict:
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    elapsed_ms = round((time.monotonic() - started) * 1000, 3)
    result_path = output_directory / "cases" / f"{case_id}.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
    return {
        "exit_code": completed.returncode,
        "elapsed_ms": elapsed_ms,
        "result_present": bool(result),
        "runtime_passed": result.get("runtime_passed"),
        "contract_passed": result.get("contract_passed"),
        "failure_code": result.get("failure_code", ""),
    }


def evaluate(results: dict[str, dict]) -> dict[str, bool]:
    api = results["api_loss"]
    model = results["model_loss"]
    retrieval = results["retrieval_loss"]
    return {
        "api_loss_fell_back_locally": (
            api["exit_code"] == 0
            and api["runtime_passed"] is True
            and api["contract_passed"] is True
        ),
        "model_loss_failed_closed": (
            model["exit_code"] == 0
            and model["result_present"] is True
            and model["runtime_passed"] is False
            and model["contract_passed"] is False
            and bool(model["failure_code"])
        ),
        "retrieval_loss_was_rejected": (
            retrieval["exit_code"] != 0 and retrieval["result_present"] is False
        ),
    }


def evaluator_command(args: argparse.Namespace, output: Path, base_url: str, financials: Path) -> list[str]:
    return [
        str(args.evaluator),
        "-case-id",
        args.case_id,
        "-suite",
        str(args.suite),
        "-catalog",
        str(args.catalog),
        "-peers",
        str(args.peers),
        "-financial-directory",
        str(financials),
        "-output-directory",
        str(output),
        "-base-url",
        base_url,
        "-model",
        args.model,
        "-context-concurrency",
        "4",
        "-timeout-per-case",
        args.timeout,
        "-source-commit",
        args.source_commit,
        "-resume=false",
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluator", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--financial-directory", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--suite", type=Path, default=Path("fixtures/productscope/technology20-standalone-development.json"))
    parser.add_argument("--catalog", type=Path, default=Path("fixtures/productscope/technology20-catalog.json"))
    parser.add_argument("--peers", type=Path, default=Path("fixtures/productscope/technology20-peer-evaluation.json"))
    parser.add_argument("--case-id", default="ADBE-risk-monitoring")
    parser.add_argument("--model", default="signalforge-gemma4-26b-q4")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--dead-model-url", default="http://127.0.0.1:65534/v1")
    parser.add_argument("--timeout", default="4m")
    parser.add_argument("--source-commit", default="working-tree")
    args = parser.parse_args()

    args.repo_root = args.repo_root.resolve()
    args.evaluator = args.evaluator.resolve()
    args.financial_directory = args.financial_directory.resolve()
    args.output_directory = args.output_directory.resolve()
    for attribute in ("suite", "catalog", "peers"):
        path = getattr(args, attribute)
        if not path.is_absolute():
            setattr(args, attribute, (args.repo_root / path).resolve())
    if not args.evaluator.is_file() or not args.financial_directory.is_dir():
        raise SystemExit("evaluator and financial authority directory must exist")
    args.output_directory.mkdir(parents=True, exist_ok=True)

    base_environment = os.environ.copy()
    for key in tuple(base_environment):
        if key.startswith("SIGNALFORGE_SPECIALIST_API_"):
            base_environment.pop(key)

    results: dict[str, dict] = {}
    api_output = args.output_directory / "api-loss"
    api_environment = {
        **base_environment,
        "SIGNALFORGE_SPECIALIST_API_ENABLED": "true",
        "SIGNALFORGE_SPECIALIST_API_PROVIDER": "radeon-vllm",
        "SIGNALFORGE_SPECIALIST_API_BASE_URL": "https://127.0.0.1:1/v1",
        "SIGNALFORGE_SPECIALIST_API_KEY": "injected-failure-test-key",
        "SIGNALFORGE_SPECIALIST_TEXT_MODEL": "DeepSeek-V4-Flash",
        "SIGNALFORGE_SPECIALIST_API_TIMEOUT": "2s",
    }
    results["api_loss"] = run_case(
        case_id=args.case_id,
        command=evaluator_command(args, api_output, args.base_url, args.financial_directory),
        cwd=args.repo_root,
        output_directory=api_output,
        environment=api_environment,
    )

    model_output = args.output_directory / "model-loss"
    results["model_loss"] = run_case(
        case_id=args.case_id,
        command=evaluator_command(args, model_output, args.dead_model_url, args.financial_directory),
        cwd=args.repo_root,
        output_directory=model_output,
        environment=base_environment,
    )

    retrieval_output = args.output_directory / "retrieval-loss"
    missing_financials = args.output_directory / "intentionally-absent-financial-authority"
    results["retrieval_loss"] = run_case(
        case_id=args.case_id,
        command=evaluator_command(args, retrieval_output, args.base_url, missing_financials),
        cwd=args.repo_root,
        output_directory=retrieval_output,
        environment=base_environment,
    )

    gates = evaluate(results)
    report = {
        "schema_version": "signalforge/radeon-failure-matrix/v1",
        "evaluator_sha256": sha256(args.evaluator),
        "source_commit": args.source_commit,
        "case_id": args.case_id,
        "model": args.model,
        "results": results,
        "gates": gates,
        "passed": all(gates.values()),
        "privacy": {
            "prompts_retained": False,
            "answers_retained_in_report": False,
            "credentials_retained": False,
        },
        "scope": (
            "Exact evaluator transport and fail-closed behavior. This report does not measure "
            "factual accuracy, sealed quality, or universal infrastructure resilience."
        ),
    }
    report_path = args.output_directory / "failure-matrix.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "gates": gates}, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
