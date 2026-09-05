from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ConfigDict, Field
from sqlmodel import SQLModel

from ..config import AppPaths
from ..exceptions import ValidationError


DEFAULT_ANALYSIS_LAMBDA_LIMITS = {
    "timeout_seconds": 20,
    "max_datasets": 3,
    "max_input_rows_per_dataset": 100_000,
    "max_output_json_bytes": 256 * 1024,
    "max_artifacts": 5,
    "max_artifact_bytes": 5 * 1024 * 1024,
    "max_dataframe_artifact_rows": 50_000,
    "max_code_bytes": 64 * 1024,
}


class AnalysisLambdaDataset(SQLModel):
    model_config = ConfigDict(extra="forbid")

    alias: str
    dataset_id: str
    dataset_name: str
    source_path: str


class AnalysisLambdaInput(SQLModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    datasets: list[AnalysisLambdaDataset]
    params: dict[str, Any] = Field(default_factory=dict)
    manifest: dict[str, Any] = Field(default_factory=dict)


class AnalysisLambdaArtifact(SQLModel):
    placeholder_id: str
    title: str
    absolute_path: str
    kind: str
    mime_type: str | None = None
    summary: str | None = None
    metadata_payload: dict[str, Any] = Field(default_factory=dict)


class AnalysisLambdaResult(SQLModel):
    output: dict[str, Any]
    artifacts: list[AnalysisLambdaArtifact] = Field(default_factory=list)
    manifest: dict[str, Any] = Field(default_factory=dict)
    code: str
    limits: dict[str, Any] = Field(default_factory=dict)


class AnalysisLambdaService:
    def __init__(self, paths: AppPaths, *, limits: dict[str, int] | None = None) -> None:
        self._paths = paths
        self._limits = {**DEFAULT_ANALYSIS_LAMBDA_LIMITS, **(limits or {})}

    def run_lambda(
        self,
        input_data: AnalysisLambdaInput,
        *,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> AnalysisLambdaResult:
        self._validate_input(input_data)
        job_id = uuid4().hex
        job_dir = self._paths.temp / "analysis-lambda" / job_id
        artifact_dir = self._paths.artifacts / "analysis" / "lambda" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        request_path = job_dir / "request.json"
        response_path = job_dir / "response.json"
        request = {
            "code": input_data.code,
            "datasets": [dataset.model_dump(mode="json") for dataset in input_data.datasets],
            "params": dict(input_data.params),
            "manifest": dict(input_data.manifest),
            "limits": self._limits,
            "artifact_output_dir": str(artifact_dir.resolve()),
        }
        request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")

        self._run_worker(request_path, response_path, cancel_requested=cancel_requested or (lambda: False))
        if not response_path.exists():
            raise ValidationError("analysis.lambda worker did not produce a response.")

        response_bytes = response_path.read_bytes()
        if len(response_bytes) > int(self._limits["max_output_json_bytes"]):
            raise ValidationError("analysis.lambda output exceeded the JSON size limit.")
        try:
            response = json.loads(response_bytes.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValidationError("analysis.lambda worker returned invalid JSON.") from exc

        if response.get("status") != "succeeded":
            raise ValidationError(str(response.get("error") or "analysis.lambda failed."))
        output = response.get("output")
        if not isinstance(output, dict):
            raise ValidationError("analysis.lambda output must be a dict.")
        artifacts = response.get("artifacts") or []
        if not isinstance(artifacts, list):
            raise ValidationError("analysis.lambda artifacts must be a list.")
        if len(artifacts) > int(self._limits["max_artifacts"]):
            raise ValidationError("analysis.lambda created too many artifacts.")

        return AnalysisLambdaResult(
            output=output,
            artifacts=[AnalysisLambdaArtifact.model_validate(artifact) for artifact in artifacts],
            manifest=dict(input_data.manifest),
            code=input_data.code,
            limits=dict(self._limits),
        )

    def _validate_input(self, input_data: AnalysisLambdaInput) -> None:
        code_bytes = input_data.code.encode("utf-8")
        if not input_data.code.strip():
            raise ValidationError("analysis.lambda code cannot be empty.")
        if len(code_bytes) > int(self._limits["max_code_bytes"]):
            raise ValidationError("analysis.lambda code exceeded the size limit.")
        if not input_data.datasets:
            raise ValidationError("analysis.lambda requires at least one dataset.")
        if len(input_data.datasets) > int(self._limits["max_datasets"]):
            raise ValidationError(f"analysis.lambda accepts at most {self._limits['max_datasets']} datasets.")
        seen_aliases: set[str] = set()
        for dataset in input_data.datasets:
            alias = dataset.alias.strip()
            if not alias:
                raise ValidationError("analysis.lambda dataset alias cannot be empty.")
            if alias in seen_aliases:
                raise ValidationError(f"Duplicate analysis.lambda dataset alias '{alias}'.")
            seen_aliases.add(alias)
            source_path = Path(dataset.source_path).expanduser()
            if not source_path.is_absolute() or not source_path.exists() or not source_path.is_file():
                raise ValidationError("analysis.lambda dataset source path must be an existing absolute file.")

    def _run_worker(
        self,
        request_path: Path,
        response_path: Path,
        *,
        cancel_requested: Callable[[], bool],
    ) -> None:
        if getattr(sys, "frozen", False):
            command = [
                sys.executable,
                "--analysis-lambda-worker",
                str(request_path),
                str(response_path),
            ]
        else:
            worker_script = Path(__file__).resolve().parents[3] / "scripts" / "run_dev.py"
            if worker_script.exists():
                command = [
                    sys.executable,
                    str(worker_script),
                    "--analysis-lambda-worker",
                    str(request_path),
                    str(response_path),
                ]
            else:
                command = [
                    sys.executable,
                    "-m",
                    "xenix.services.analysis_lambda_worker",
                    str(request_path),
                    str(response_path),
                ]
        env = dict(os.environ)
        source_root = str(Path(__file__).resolve().parents[2])
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = source_root if not existing_pythonpath else os.pathsep.join([source_root, existing_pythonpath])
        process = subprocess.Popen(
            command,
            cwd=str(request_path.parent),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + float(self._limits["timeout_seconds"])
        while process.poll() is None:
            if cancel_requested():
                process.kill()
                process.communicate(timeout=2)
                raise ValidationError("analysis.lambda was cancelled.")
            if time.monotonic() >= deadline:
                process.kill()
                process.communicate(timeout=2)
                raise ValidationError("analysis.lambda timed out.")
            time.sleep(0.05)

        stdout, stderr = process.communicate()
        if process.returncode != 0:
            details = (stderr or stdout or "").strip()
            suffix = f" {details}" if details else ""
            raise ValidationError(f"analysis.lambda worker failed.{suffix}")
        if not response_path.exists():
            details = (stderr or stdout or "").strip()
            suffix = f" Worker output: {details}" if details else ""
            raise ValidationError(f"analysis.lambda worker did not produce a response.{suffix}")
