#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.safe_registry_manifest_record import (
    make_safe_registry_manifest_record,
    write_safe_registry_manifest_record,
)

ACCEPT_MANIFESTS = ", ".join(
    [
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.oci.image.index.v1+json",
    ]
)

ADMITTED_PROVIDERS = {"docker_hub_official"}
TOKEN_URL = "https://auth.docker.io/token"
REGISTRY_URL = "https://registry-1.docker.io"


class RegistryTransport(Protocol):
    def get_json(
        self, url: str, headers: dict[str, str], timeout: float
    ) -> tuple[int, dict[str, str], dict[str, Any]]: ...

    def get_bytes(
        self, url: str, headers: dict[str, str], timeout: float
    ) -> tuple[int, dict[str, str], bytes]: ...


class UrllibRegistryTransport:
    def get_json(
        self, url: str, headers: dict[str, str], timeout: float
    ) -> tuple[int, dict[str, str], dict[str, Any]]:
        status, response_headers, body = self.get_bytes(url, headers, timeout)
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            payload = {}
        return status, response_headers, payload

    def get_bytes(
        self, url: str, headers: dict[str, str], timeout: float
    ) -> tuple[int, dict[str, str], bytes]:
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - exact registry metadata only.
                return int(response.status), dict(response.headers.items()), response.read()
        except HTTPError as exc:
            return int(exc.code), dict(exc.headers.items()), exc.read()


@dataclass(slots=True)
class SafeRegistryManifestClient:
    provider: str = "docker_hub_official"
    timeout_seconds: float = 20.0
    transport: RegistryTransport | None = None

    def lookup(self, image_reference: str) -> dict[str, Any]:
        parsed = parse_image_reference(image_reference)
        blocked = _preflight_block(parsed, self.provider)
        if blocked:
            return blocked
        transport = self.transport or UrllibRegistryTransport()
        repository = parsed["repository"]
        tag = parsed["tag"]
        try:
            token = _request_bearer_token(transport, repository, self.timeout_seconds)
            if token["status"] != "TOKEN_READY":
                return _provider_status(
                    token["status"], parsed, token.get("http_status", 0), token.get("error", "")
                )
            manifest = _request_manifest(
                transport, repository, tag, token["token"], self.timeout_seconds
            )
            return _manifest_result(parsed, manifest)
        except TimeoutError:
            return _provider_status("REGISTRY_MANIFEST_LOOKUP_PROVIDER_ERROR", parsed, 0, "timeout")
        except (OSError, URLError) as exc:
            reason = getattr(exc, "reason", exc)
            return _provider_status(
                "REGISTRY_MANIFEST_LOOKUP_BLOCKED_NETWORK_DISABLED", parsed, 0, str(reason)
            )


def parse_image_reference(image_reference: str) -> dict[str, str]:
    image = image_reference.strip()
    if "@" in image:
        image = image.split("@", 1)[0]
    if ":" not in image.rsplit("/", 1)[-1]:
        return {
            "image_reference": image_reference,
            "repository": image,
            "tag": "",
            "status": "missing_tag",
        }
    repository, tag = image.rsplit(":", 1)
    return {
        "image_reference": image_reference,
        "repository": repository,
        "tag": tag,
        "status": "parsed",
    }


def is_broad_search_request(image_reference: str) -> bool:
    stripped = image_reference.strip()
    return (
        any(token in stripped for token in ("*", "?", " "))
        or stripped in {"", "programbench", "programbench/"}
        or stripped.endswith("/")
    )


def _preflight_block(parsed: dict[str, str], provider: str) -> dict[str, Any] | None:
    if provider not in ADMITTED_PROVIDERS:
        return _base_result(
            "REGISTRY_MANIFEST_LOOKUP_BLOCKED_UNADMITTED_PROVIDER",
            parsed,
            provider=provider,
            error="provider_not_admitted",
        )
    if is_broad_search_request(parsed["image_reference"]):
        return _base_result(
            "REGISTRY_MANIFEST_LOOKUP_BLOCKED_BROAD_SEARCH",
            parsed,
            error="broad_search_or_catalog_request_blocked",
        )
    if not parsed["tag"]:
        return _base_result(
            "REGISTRY_MANIFEST_LOOKUP_BLOCKED_BROAD_SEARCH", parsed, error="exact_tag_required"
        )
    if parsed["tag"].lower() == "latest":
        return _base_result(
            "REGISTRY_MANIFEST_LOOKUP_BLOCKED_LATEST_TAG", parsed, error="latest_tag_blocked"
        )
    if not parsed["repository"].startswith("programbench/"):
        return _base_result(
            "REGISTRY_MANIFEST_LOOKUP_BLOCKED_BROAD_SEARCH",
            parsed,
            error="exact_programbench_repository_required",
        )
    return None


def _request_bearer_token(
    transport: RegistryTransport, repository: str, timeout: float
) -> dict[str, Any]:
    query = urlencode({"service": "registry.docker.io", "scope": f"repository:{repository}:pull"})
    status, headers, body = transport.get_json(
        f"{TOKEN_URL}?{query}", {"Accept": "application/json"}, timeout
    )
    if status == 429:
        return {"status": "REGISTRY_MANIFEST_LOOKUP_RATE_LIMITED", "http_status": status}
    if status >= 400:
        return {
            "status": "REGISTRY_MANIFEST_LOOKUP_PROVIDER_ERROR",
            "http_status": status,
            "error": _safe_error(body),
        }
    token = str(body.get("token") or body.get("access_token") or "")
    if not token:
        return {
            "status": "REGISTRY_MANIFEST_LOOKUP_PROVIDER_ERROR",
            "http_status": status,
            "error": "token_missing",
        }
    return {
        "status": "TOKEN_READY",
        "token": token,
        "http_status": status,
        "headers_hash": _hash_json(headers),
    }


def _request_manifest(
    transport: RegistryTransport,
    repository: str,
    tag: str,
    token: str,
    timeout: float,
) -> dict[str, Any]:
    path = f"{REGISTRY_URL}/v2/{quote(repository, safe='/')}/manifests/{quote(tag, safe='')}"
    headers = {"Accept": ACCEPT_MANIFESTS, "Authorization": f"Bearer {token}"}
    status, response_headers, body = transport.get_bytes(path, headers, timeout)
    return {"http_status": status, "headers": response_headers, "body": body}


def _manifest_result(parsed: dict[str, str], manifest: dict[str, Any]) -> dict[str, Any]:
    status = int(manifest.get("http_status") or 0)
    if status == 404:
        return _base_result(
            "REGISTRY_MANIFEST_METADATA_NOT_FOUND",
            parsed,
            http_status=status,
            error="manifest_not_found",
        )
    if status == 429:
        return _base_result(
            "REGISTRY_MANIFEST_LOOKUP_RATE_LIMITED",
            parsed,
            http_status=status,
            error="rate_limited",
        )
    if status >= 400 or status <= 0:
        return _base_result(
            "REGISTRY_MANIFEST_LOOKUP_PROVIDER_ERROR",
            parsed,
            http_status=status,
            error="provider_http_error",
        )

    headers = {str(k).lower(): str(v) for k, v in dict(manifest.get("headers") or {}).items()}
    body = bytes(manifest.get("body") or b"")
    digest = headers.get("docker-content-digest", "")
    body_hash = "sha256:" + hashlib.sha256(body).hexdigest()
    digest_source = (
        "Docker-Content-Digest" if digest.startswith("sha256:") else "manifest_body_hash"
    )
    if not digest.startswith("sha256:"):
        digest = body_hash
    try:
        body_json = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        body_json = {}
    platforms = _platforms(body_json)
    return {
        **_base_result("REGISTRY_MANIFEST_METADATA_FOUND", parsed, http_status=status),
        "digest": digest,
        "digest_source": digest_source,
        "media_type": str(body_json.get("mediaType") or headers.get("content-type", "")).split(";")[
            0
        ],
        "schema_version": body_json.get("schemaVersion"),
        "platforms": platforms,
        "manifest_body_hash": body_hash,
        "manifest_summary_hash": _hash_json(
            {
                "repository": parsed["repository"],
                "tag": parsed["tag"],
                "digest": digest,
                "media_type": str(
                    body_json.get("mediaType") or headers.get("content-type", "")
                ).split(";")[0],
                "schema_version": body_json.get("schemaVersion"),
                "platforms": platforms,
            }
        ),
        "metadata_only": True,
        "cache_ready": False,
        "executable": False,
        "training_eligible": False,
    }


def _provider_status(
    status: str, parsed: dict[str, str], http_status: int, error: str
) -> dict[str, Any]:
    return _base_result(status, parsed, http_status=http_status, error=error)


def _base_result(
    status: str,
    parsed: dict[str, str],
    *,
    provider: str = "docker_hub_official",
    http_status: int = 0,
    error: str = "",
) -> dict[str, Any]:
    return {
        "status": status,
        "provider": provider,
        "image_reference": parsed.get("image_reference", ""),
        "repository": parsed.get("repository", ""),
        "tag": parsed.get("tag", ""),
        "http_status": http_status,
        "error": error,
        "digest": "",
        "digest_source": "",
        "media_type": "",
        "schema_version": None,
        "platforms": [],
        "manifest_body_hash": "",
        "manifest_summary_hash": "",
        "metadata_only": True,
        "docker_cli_used": False,
        "docker_daemon_used": False,
        "layer_downloaded": False,
        "image_imported": False,
        "docker_run_performed": False,
        "cache_ready": False,
        "executable": False,
        "training_eligible": False,
    }


def _platforms(body_json: dict[str, Any]) -> list[dict[str, str]]:
    manifests = body_json.get("manifests")
    if not isinstance(manifests, list):
        return []
    rows = []
    for item in manifests:
        if not isinstance(item, dict):
            continue
        platform = item.get("platform")
        if not isinstance(platform, dict):
            continue
        rows.append(
            {
                "os": str(platform.get("os") or ""),
                "architecture": str(platform.get("architecture") or ""),
                "variant": str(platform.get("variant") or ""),
                "digest": str(item.get("digest") or ""),
                "media_type": str(item.get("mediaType") or ""),
            }
        )
    return rows


def _safe_error(body: Any) -> str:
    if isinstance(body, dict):
        errors = body.get("errors")
        if isinstance(errors, list) and errors:
            return str(errors[0])[:200]
    return str(body)[:200]


def _hash_json(data: Any) -> str:
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _closed_auth() -> dict[str, bool]:
    return {
        "docker_execution_authorized": False,
        "docker_pull_authorized": False,
        "layer_download_authorized": False,
        "image_import_authorized": False,
        "programbench_rerun_authorized": False,
        "rebuild_authorized": False,
        "remediation_authorized": False,
        "policy_exception_granted": False,
        "training_rows_written": False,
        "training_eligible": False,
        "cache_ready": False,
        "executable": False,
    }


def client_lock_record() -> dict[str, Any]:
    record = make_safe_registry_manifest_record(
        record_type="programbench_safe_registry_manifest_client",
        schema_version="determinex-programbench-safe-registry-manifest-client-v1",
        status="SAFE_REGISTRY_MANIFEST_CLIENT_WRITTEN",
        payload={
            "record_id": "programbench_safe_registry_manifest_client_run_20260528",
            "supported_provider": "docker_hub_official",
            "supported_media_types": ACCEPT_MANIFESTS.split(", "),
            "blocks_latest": True,
            "blocks_broad_search": True,
            "blocks_catalog_or_tag_listing": True,
            "uses_docker_cli": False,
            "uses_docker_daemon": False,
            "downloads_layers": False,
            "imports_images": False,
            "metadata_only": True,
            "result_cannot_mark_cache_ready_executable_or_training_eligible": True,
            "authorization": _closed_auth(),
        },
    )
    return record


def write_client_lock_record(root: Path = Path(".")) -> Path:
    return write_safe_registry_manifest_record(
        client_lock_record(),
        root / "assurance" / "evidence" / "programbench_safe_registry_manifest_client",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Exact metadata-only registry manifest lookup for ProgramBench images."
    )
    parser.add_argument("image_reference", nargs="?")
    parser.add_argument("--write-lock-record", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.write_lock_record:
        path = write_client_lock_record()
        payload: dict[str, Any] = {"record_path": str(path)}
    elif args.image_reference:
        payload = SafeRegistryManifestClient().lookup(args.image_reference)
    else:
        payload = client_lock_record()
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
