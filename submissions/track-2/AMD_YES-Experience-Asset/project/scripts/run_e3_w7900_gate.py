#!/usr/bin/env python3
"""Run the exact-commit E3 gate on the prepared W7900/ROCm/vLLM stack."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PERSISTENT_ROOT = Path("/workspace/amd-track2-agent")
DEFAULT_MODEL_PATH = (
    PERSISTENT_ROOT / "models" / "Qwen2.5-14B-Instruct-3957bf39753c"
)
DEFAULT_MODEL_MANIFEST = (
    ROOT / "config" / "models" / "qwen2.5-14b-instruct.modelscope.json"
)
FIXTURE_ID = "chair_public_complete"
FIXTURE_VERSION = "0.1.0"


@dataclass(frozen=True)
class Step:
    name: str
    argv: list[str]


def build_steps(
    *,
    python: str,
    vllm_python: str,
    base_url: str,
    model_id: str,
    model_path: Path,
    model_manifest: Path,
    output_dir: Path,
    code_commit: str,
) -> list[Step]:
    return [
        Step("remote-environment", ["bash", "scripts/verify_remote_dev.sh"]),
        Step("rocm-environment", ["bash", "scripts/verify_rocm_env.sh"]),
        Step(
            "w7900-environment-json",
            [
                vllm_python,
                "scripts/capture_w7900_environment.py",
                "--output",
                str(output_dir / "artifacts" / "w7900-environment.json"),
                "--code-commit",
                code_commit,
                "--model-id",
                model_id,
                "--model-path",
                str(model_path),
                "--model-manifest",
                str(model_manifest),
                "--base-url",
                base_url,
            ],
        ),
        Step(
            "model-snapshot-full-sha256",
            [
                vllm_python,
                "scripts/verify_model_snapshot.py",
                "--manifest",
                str(model_manifest),
                "--model-dir",
                str(model_path),
                "--full-sha256",
            ],
        ),
        Step("vllm-health", ["curl", "--fail", "--silent", "--show-error", f"{base_url}/models"]),
        Step(
            "native-tool-call",
            [
                python,
                "scripts/verify_vllm_tool_call.py",
                "--base-url",
                base_url,
                "--model",
                model_id,
            ],
        ),
        Step(
            "model-contract",
            [
                python,
                "scripts/verify_e1_model_contract.py",
                "--base-url",
                base_url,
                "--model-id",
                model_id,
            ],
        ),
        Step(
            "runtime-allow-deny-restart",
            [
                python,
                "scripts/verify_e1_runtime_gate.py",
                "--base-url",
                base_url,
                "--model-id",
                model_id,
            ],
        ),
        Step(
            "e3-m2-regressions",
            [
                python,
                "-m",
                "pytest",
                "tests/integration/test_m2_api.py",
                "tests/integration/test_m2_langgraph.py",
                "-q",
            ],
        ),
        Step(
            "e3-sanitized-artifacts",
            [
                python,
                "scripts/capture_e3_m2_evidence.py",
                "--output-dir",
                str(output_dir / "artifacts"),
                "--code-commit",
                code_commit,
            ],
        ),
        Step(
            "finalize-sanitized-packet",
            [
                python,
                "scripts/finalize_e3_w7900_packet.py",
                "--raw-dir",
                str(output_dir),
                "--packet-dir",
                str(output_dir.parent / "packet-candidate"),
            ],
        ),
    ]


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout.strip()


def _validate_sha(value: str) -> None:
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("expected commit must be a lowercase 40-character Git SHA")


def _validate_real_run(output_dir: Path, expected_commit: str, python: str) -> None:
    _validate_sha(expected_commit)
    current_commit = _git("rev-parse", "HEAD")
    if current_commit != expected_commit:
        raise RuntimeError(
            f"HEAD {current_commit} does not match expected commit {expected_commit}"
        )
    if _git("status", "--porcelain"):
        raise RuntimeError("W7900 evidence requires a clean exact-commit worktree")

    resolved_output = output_dir.resolve()
    evidence_root = (PERSISTENT_ROOT / "evidence").resolve()
    if not resolved_output.is_relative_to(evidence_root) or resolved_output.name != "raw":
        raise ValueError(
            "output-dir must be a raw directory under "
            "/workspace/amd-track2-agent/evidence"
        )
    resolved_python = Path(python).resolve()
    agent_environment = (PERSISTENT_ROOT / "venvs" / "agent").resolve()
    if not resolved_python.is_relative_to(agent_environment):
        raise RuntimeError(
            "activate /workspace/amd-track2-agent/venvs/agent before the W7900 run"
        )


def _write_result(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run_step(step: Step, output_dir: Path, environment: dict[str, str]) -> dict:
    started = datetime.now(UTC)
    log_path = output_dir / f"{step.name}.log"
    with log_path.open("w", encoding="utf-8") as log:
        completed = subprocess.run(
            step.argv,
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    finished = datetime.now(UTC)
    return {
        "name": step.name,
        "argv": step.argv,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "exit_code": completed.returncode,
        "log": log_path.name,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model-id", default="Qwen2.5-14B-Instruct")
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--model-manifest", type=Path, default=DEFAULT_MODEL_MANIFEST)
    parser.add_argument(
        "--vllm-python",
        default=str(PERSISTENT_ROOT / "venvs" / "vllm" / "bin" / "python"),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the immutable execution plan without checking W7900 or writing files.",
    )
    args = parser.parse_args()
    _validate_sha(args.expected_commit)
    steps = build_steps(
        python=sys.executable,
        vllm_python=args.vllm_python,
        base_url=args.base_url.rstrip("/"),
        model_id=args.model_id,
        model_path=args.model_path,
        model_manifest=args.model_manifest,
        output_dir=args.output_dir,
        code_commit=args.expected_commit,
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "result": "DRY_RUN",
                    "repo": str(ROOT),
                    "expected_commit": args.expected_commit,
                    "output_dir": str(args.output_dir),
                    "steps": [asdict(step) for step in steps],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    _validate_real_run(args.output_dir, args.expected_commit, sys.executable)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    environment = dict(os.environ)
    environment.update(
        {
            "ROOT": str(PERSISTENT_ROOT),
            "REPO": str(ROOT),
            "VLLM_PYTHON": args.vllm_python,
            "CODE_COMMIT": args.expected_commit,
            "OPENAI_BASE_URL": args.base_url.rstrip("/"),
            "SERVED_MODEL_NAME": args.model_id,
        }
    )
    result = {
        "schema_version": "e3-m2-w7900-gate/v1",
        "result": "RUNNING",
        "started_at": datetime.now(UTC).isoformat(),
        "source": {
            "git_commit": args.expected_commit,
            "branch": _git("branch", "--show-current"),
            "dirty_tree": False,
        },
        "fixture": {
            "id": FIXTURE_ID,
            "version": FIXTURE_VERSION,
            "data_class": "adapted_public_research",
        },
        "model": {
            "id": args.model_id,
            "base_url": args.base_url.rstrip("/"),
            "path": str(args.model_path),
            "manifest": str(args.model_manifest),
        },
        "steps": [],
        "claims": {
            "compatibility_only": True,
            "performance_claim": False,
            "raw_prompt_or_response_retained": False,
        },
    }
    result_path = args.output_dir / "run-result.json"
    _write_result(result_path, result)
    for step in steps[:-1]:
        observed = _run_step(step, args.output_dir, environment)
        result["steps"].append(observed)
        if observed["exit_code"] != 0:
            result["result"] = "FAIL"
            result["failed_step"] = step.name
            result["finished_at"] = datetime.now(UTC).isoformat()
            _write_result(result_path, result)
            return 1
        _write_result(result_path, result)
    result["result"] = "PASS"
    result["finished_at"] = datetime.now(UTC).isoformat()
    _write_result(result_path, result)
    finalizer = _run_step(steps[-1], args.output_dir, environment)
    result["steps"].append(finalizer)
    if finalizer["exit_code"] != 0:
        result["result"] = "FAIL"
        result["failed_step"] = steps[-1].name
        result["finished_at"] = datetime.now(UTC).isoformat()
        _write_result(result_path, result)
        return 1
    _write_result(result_path, result)
    print(json.dumps({"result": "PASS", "record": str(result_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
