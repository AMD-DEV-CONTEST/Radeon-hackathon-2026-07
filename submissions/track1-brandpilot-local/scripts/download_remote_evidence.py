from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import ssl
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, Request, build_opener
from uuid import UUID

from PIL import Image

TOKEN_ENV = "BRANDPILOT_DEMO_TOKEN"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "evidence" / "radeon-session-2b"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
SAFE_FILES = {
    "system-status.json",
    "job-metadata.json",
    "generated-output.png",
    "result-metadata.json",
    "review-state.json",
    "hashes.json",
    "evidence-bundle.zip",
}
SYSTEM_FIELDS = {
    "enabled",
    "gpu_connected",
    "rocm_available",
    "inference_mode",
    "device",
    "model_id",
    "model_revision",
    "model_loaded",
    "pytorch_version",
    "hip_version",
    "message",
}
JOB_FIELDS = {
    "job_id",
    "project_id",
    "status",
    "stage",
    "current_step",
    "total_steps",
    "created_at",
    "started_at",
    "completed_at",
    "failure",
    "output_available",
    "model_id",
    "model_revision",
    "inference_mode",
    "gpu_confirmation",
}
RESULT_FIELDS = {
    "result_id",
    "job_id",
    "project_id",
    "mode",
    "experimental",
    "gpu_connected",
    "rocm_available",
    "model_id",
    "model_revision",
    "pipeline_class",
    "creative_style",
    "style",
    "output_format",
    "image_url",
    "prompt",
    "negative_prompt",
    "width",
    "height",
    "steps",
    "strength",
    "guidance_scale",
    "seed",
    "model_load_seconds",
    "generation_seconds",
    "total_seconds",
    "peak_allocated_vram_bytes",
    "peak_reserved_vram_bytes",
    "gpu_device_name",
    "pytorch_version",
    "hip_rocm_version",
    "input_sha256",
    "output_sha256",
    "generated_at",
    "disclosure",
    "human_review_status",
    "review_note",
    "reviewed_at",
    "created_at",
}
REVIEW_FIELDS = {
    "result_id",
    "project_id",
    "human_review_status",
    "review_note",
    "reviewed_at",
}


class EvidenceDownloadError(RuntimeError):
    pass


def safe_filename(filename: str) -> str:
    if (
        filename not in SAFE_FILES
        or Path(filename).name != filename
        or "/" in filename
        or "\\" in filename
        or ".." in filename
    ):
        raise EvidenceDownloadError("Unsafe evidence filename refused.")
    return filename


def validate_job_id(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise EvidenceDownloadError("Invalid job identifier.") from exc


def normalize_base_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
    except ValueError as exc:
        raise EvidenceDownloadError("Invalid backend URL.") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise EvidenceDownloadError("A clean HTTPS backend URL is required.")
    path = parsed.path.rstrip("/")
    return f"https://{parsed.netloc}{path}"


def allowlist(source: Mapping[str, Any], fields: set[str]) -> dict[str, Any]:
    return {key: source[key] for key in fields if key in source}


def _read_limited(response: Any, limit: int) -> bytes:
    body = response.read(limit + 1)
    if len(body) > limit:
        raise EvidenceDownloadError("Remote evidence exceeded the safe size limit.")
    return body


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _require_fields(payload: Mapping[str, Any], fields: set[str], label: str) -> None:
    if not fields <= payload.keys():
        raise EvidenceDownloadError(f"Remote {label} schema was incomplete.")


def _validate_png(content: bytes) -> None:
    try:
        from io import BytesIO

        with Image.open(BytesIO(content)) as image:
            image.verify()
            if image.format != "PNG":
                raise EvidenceDownloadError("Generated evidence image was not PNG.")
    except EvidenceDownloadError:
        raise
    except Exception:
        raise EvidenceDownloadError("Generated evidence image was invalid.") from None


class EvidenceClient:
    def __init__(self, base_url: str, token: str, opener: Any | None = None):
        self.base_url = normalize_base_url(base_url)
        self._token = token
        context = ssl.create_default_context()
        if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
            raise EvidenceDownloadError("TLS certificate verification is required.")
        self._opener = opener or build_opener(HTTPSHandler(context=context))

    def _request(
        self,
        path: str,
        *,
        accept: str,
        limit: int,
        optional: bool = False,
    ) -> tuple[bytes, str] | None:
        if not path.startswith("/") or ".." in path or re.match(r"^//", path):
            raise EvidenceDownloadError("Unsafe remote evidence path refused.")
        request = Request(
            f"{self.base_url}{path}",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": accept,
                "User-Agent": "BrandPilot-Evidence/1.0",
            },
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=30) as response:
                return _read_limited(response, limit), response.headers.get(
                    "Content-Type", ""
                ).split(";", 1)[0].lower()
        except HTTPError as exc:
            if optional and exc.code == 404:
                return None
            if exc.code in {401, 403}:
                raise EvidenceDownloadError("Authentication failed.") from None
            raise EvidenceDownloadError(
                f"Remote evidence request failed with HTTP {exc.code}."
            ) from None
        except (URLError, TimeoutError, OSError):
            raise EvidenceDownloadError(
                "Secure connection to the evidence endpoint failed."
            ) from None

    def json(self, path: str) -> dict[str, Any]:
        response = self._request(
            path, accept="application/json", limit=MAX_JSON_BYTES
        )
        assert response is not None
        body, content_type = response
        if content_type != "application/json":
            raise EvidenceDownloadError("Remote evidence was not JSON.")
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise EvidenceDownloadError("Remote evidence JSON was invalid.") from None
        if not isinstance(payload, dict):
            raise EvidenceDownloadError("Remote evidence JSON shape was invalid.")
        return payload

    def binary(
        self,
        path: str,
        *,
        content_type: str,
        limit: int,
        optional: bool = False,
    ) -> bytes | None:
        response = self._request(
            path, accept=content_type, limit=limit, optional=optional
        )
        if response is None:
            return None
        body, received_type = response
        if received_type != content_type:
            raise EvidenceDownloadError("Remote evidence content type was invalid.")
        return body


def download_evidence(
    base_url: str,
    job_id: str,
    output_dir: Path,
    *,
    environ: dict[str, str] | os._Environ[str] = os.environ,
    opener: Any | None = None,
) -> list[Path]:
    token = environ.get(TOKEN_ENV, "")
    if not token:
        raise EvidenceDownloadError(
            f"{TOKEN_ENV} is required and must be supplied through the environment."
        )
    try:
        safe_job_id = validate_job_id(job_id)
        client = EvidenceClient(base_url, token, opener=opener)
        target = output_dir.expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)

        status = allowlist(client.json("/experimental/rocm/status"), SYSTEM_FIELDS)
        _require_fields(
            status,
            {
                "enabled",
                "gpu_connected",
                "rocm_available",
                "model_id",
                "model_revision",
            },
            "system status",
        )
        job_raw = client.json(f"/experimental/rocm/jobs/{safe_job_id}")
        job = allowlist(job_raw, JOB_FIELDS)
        _require_fields(
            job,
            {"job_id", "project_id", "status", "output_available"},
            "job metadata",
        )
        if job.get("job_id") != safe_job_id:
            raise EvidenceDownloadError("Remote job identifier did not match.")
        if job.get("status") != "completed" or not job.get("output_available"):
            raise EvidenceDownloadError("The requested job is not complete.")
        project_id = str(job.get("project_id", ""))
        try:
            project_id = str(UUID(project_id))
        except ValueError as exc:
            raise EvidenceDownloadError("Remote project identifier was invalid.") from exc

        project = client.json(f"/projects/{project_id}")
        results = project.get("results")
        if not isinstance(results, list):
            raise EvidenceDownloadError("Remote project results were invalid.")
        matching = next(
            (
                item
                for item in results
                if isinstance(item, dict) and item.get("job_id") == safe_job_id
            ),
            None,
        )
        if matching is None:
            raise EvidenceDownloadError("Completed result metadata was unavailable.")
        result = allowlist(matching, RESULT_FIELDS)
        review = allowlist(matching, REVIEW_FIELDS)
        _require_fields(
            result,
            {
                "result_id",
                "job_id",
                "project_id",
                "model_id",
                "model_revision",
                "output_sha256",
            },
            "result metadata",
        )
        if result.get("project_id") != project_id:
            raise EvidenceDownloadError("Remote result project did not match.")

        image = client.binary(
            f"/experimental/rocm/jobs/{safe_job_id}/output",
            content_type="image/png",
            limit=MAX_IMAGE_BYTES,
        )
        assert image is not None
        _validate_png(image)
        image_hash = hashlib.sha256(image).hexdigest()
        if result.get("output_sha256") != image_hash:
            raise EvidenceDownloadError("Generated image hash did not match metadata.")

        with tempfile.TemporaryDirectory(
            dir=target.parent, prefix=".brandpilot-evidence-"
        ) as staging_name:
            staging = Path(staging_name)
            staged: list[Path] = []
            payloads = {
                "system-status.json": _json_bytes(status),
                "job-metadata.json": _json_bytes(job),
                "result-metadata.json": _json_bytes(result),
                "review-state.json": _json_bytes(review),
                "generated-output.png": image,
            }
            for filename, content in payloads.items():
                destination = staging / safe_filename(filename)
                _atomic_write(destination, content)
                staged.append(destination)

            bundle = client.binary(
                f"/experimental/rocm/jobs/{safe_job_id}/evidence?format=zip",
                content_type="application/zip",
                limit=MAX_BUNDLE_BYTES,
                optional=True,
            )
            if bundle is not None:
                bundle_path = staging / safe_filename("evidence-bundle.zip")
                _atomic_write(bundle_path, bundle)
                staged.append(bundle_path)

            hashes = {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in staged
            }
            hashes["api_reported_output_sha256"] = result.get("output_sha256")
            hashes_path = staging / safe_filename("hashes.json")
            _atomic_write(hashes_path, _json_bytes(hashes))
            staged.append(hashes_path)

            files: list[Path] = []
            for staged_path in staged:
                destination = target / staged_path.name
                staged_path.replace(destination)
                files.append(destination)
            return files
    finally:
        environ.pop(TOKEN_ENV, None)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download whitelisted BrandPilot Radeon evidence over verified HTTPS."
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        files = download_evidence(args.base_url, args.job_id, args.output_dir)
    except EvidenceDownloadError as exc:
        print(f"Evidence retrieval failed: {exc}", file=sys.stderr)
        return 1
    print(f"Saved {len(files)} sanitised evidence files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
