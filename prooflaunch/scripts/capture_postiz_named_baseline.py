#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REQUESTS = (
    ROOT
    / "artifacts/gtm-last-mile-pk-v1/postiz-dry-run-native-preview-v1/postiz-dry-run-requests.json"
)
DEFAULT_OUTPUT = (
    ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-inputs-v1/postiz"
)
CAPTURE_SLOT_ID = "pk-1cd7f6ecc915700e"
FROZEN_BRIEF_SHA256 = "20a7977c4ac72ffdc9a6f23dcda4d1cfada38148274148c8c064100218133a38"


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def seal(payload: dict[str, Any]) -> dict[str, Any]:
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    payload["content_sha256"] = hashlib.sha256(canonical_json_bytes(unsigned)).hexdigest()
    return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def redact(value: Any) -> Any:
    if isinstance(value, list):
        return [redact(item) for item in value]
    if not isinstance(value, dict):
        return value
    output: dict[str, Any] = {}
    for key, item in value.items():
        lowered = key.casefold()
        if any(token in lowered for token in ("apikey", "api_key", "password", "authorization", "token")):
            output[key] = "[REDACTED]" if item not in (None, "") else item
        else:
            output[key] = redact(item)
    return output


class LocalPostiz:
    def __init__(self, base_url: str) -> None:
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("Postiz capture refuses every non-local HTTP target")
        self.base_url = base_url.rstrip("/")
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.request_count = 0
        self.auth_cookie: str | None = None

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = canonical_json_bytes(payload)
        if api_key:
            headers["Authorization"] = api_key
        elif self.auth_cookie:
            headers["Cookie"] = f"auth={self.auth_cookie}"
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method=method,
        )
        self.request_count += 1
        try:
            with self.opener.open(request, timeout=30) as response:
                body = response.read()
                status = response.status
                response_headers = dict(response.headers.items())
        except urllib.error.HTTPError as error:
            body = error.read()
            status = error.code
            response_headers = dict(error.headers.items())
        set_cookie = response_headers.get("Set-Cookie", "")
        if set_cookie.startswith("auth="):
            self.auth_cookie = set_cookie.split(";", 1)[0].split("=", 1)[1]
        try:
            decoded: Any = json.loads(body.decode("utf-8")) if body else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            decoded = body.decode("utf-8", errors="replace")[:4000]
        return {
            "method": method,
            "path": path,
            "status": status,
            "response_headers": {
                key: value
                for key, value in response_headers.items()
                if key.casefold() in {"content-type", "content-length"}
            },
            "body": redact(decoded),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:4007")
    parser.add_argument("--requests", type=Path, default=DEFAULT_REQUESTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--email", default="prooflaunch-pk@localhost.invalid")
    parser.add_argument("--company", default="ProofLaunch PK")
    parser.add_argument("--postiz-image-digest", required=True)
    parser.add_argument("--postiz-version", default="v2.21.8")
    parser.add_argument("--official-compose-revision", required=True)
    args = parser.parse_args()

    password = os.environ.get("PROOFLAUNCH_POSTIZ_PK_PASSWORD", "")
    if len(password) < 12:
        raise SystemExit("PROOFLAUNCH_POSTIZ_PK_PASSWORD must be set for the local-only account")

    request_source = args.requests.resolve(strict=True)
    request_payload = json.loads(request_source.read_text(encoding="utf-8"))
    requests = request_payload.get("requests")
    if not isinstance(requests, list) or len(requests) != 4:
        raise SystemExit("expected the four sealed local dry-run requests")
    if request_payload.get("automatic_publish_enabled") is not False:
        raise SystemExit("source requests must keep automatic publication disabled")

    client = LocalPostiz(args.base_url)
    register = client.request(
        "POST",
        "/api/auth/register",
        payload={
            "email": args.email,
            "password": password,
            "company": args.company,
            "provider": "LOCAL",
        },
    )
    login = client.request(
        "POST",
        "/api/auth/login",
        payload={"email": args.email, "password": password, "provider": "LOCAL"},
    )
    if login["status"] != 200:
        raise SystemExit(f"local Postiz login failed with status {login['status']}")
    if not client.auth_cookie:
        raise SystemExit("local Postiz login did not return an auth cookie")
    # Read the API key only in memory. Persist only its SHA-256 fingerprint.
    raw_request = urllib.request.Request(
        args.base_url.rstrip("/") + "/api/user/api-key/rotate",
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "Cookie": f"auth={client.auth_cookie}",
        },
        method="POST",
    )
    client.request_count += 1
    with client.opener.open(raw_request, timeout=30) as response:
        api_key_rotation_status = response.status
        raw_api_key_body = json.loads(response.read().decode("utf-8"))
    api_key = raw_api_key_body.get("apiKey")
    if not isinstance(api_key, str) or len(api_key) < 32:
        raise SystemExit("local Postiz API key rotation failed")
    api_key_fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    integrations = client.request("GET", "/api/public/v1/integrations", api_key=api_key)
    if integrations["status"] != 200 or not isinstance(integrations["body"], list):
        raise SystemExit("local Postiz integration inventory could not be verified")
    if integrations["body"]:
        raise SystemExit("capture refuses to run while an external social integration is connected")

    executions: list[dict[str, Any]] = []
    for item in requests:
        postiz_request = item.get("postiz_request", {})
        payload = postiz_request.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "schedule":
            raise SystemExit("frozen request payload is invalid")
        response = client.request(
            "POST",
            "/api/public/v1/posts",
            payload=payload,
            api_key=api_key,
        )
        executions.append(
            {
                "slot_id": item.get("slot_id"),
                "channel": item.get("channel"),
                "provider": item.get("provider"),
                "scheduled_at_utc": item.get("scheduled_at_utc"),
                "approval_state": item.get("approval_state"),
                "request_payload": payload,
                "actual_local_product_response": response,
                "external_publish_attempted": False,
                "external_post_created": False,
            }
        )

    captured_at = datetime.now(timezone.utc).isoformat()
    artifact = {
        "schema": "ProofLaunchPostizRawNamedBaselineV1",
        "capture_slot_id": CAPTURE_SLOT_ID,
        "category_id": "content_scheduling_operations",
        "reference_product": "Postiz",
        "provider_version": args.postiz_version,
        "runtime": {
            "base_url": args.base_url,
            "local_only": True,
            "postiz_image_digest": args.postiz_image_digest,
            "official_compose_revision": args.official_compose_revision,
            "api_key_sha256": api_key_fingerprint,
            "api_key_persisted": False,
            "connected_integration_count": 0,
            "local_http_request_count": client.request_count,
            "external_network_calls_during_baseline_execution": 0,
        },
        "frozen_input": {
            "source_path": str(request_source.relative_to(ROOT)),
            "source_sha256": sha256_file(request_source),
            "same_frozen_brief_without_hidden_editing": True,
        },
        "authorization_boundary": {
            "human_release_owner_required": True,
            "automatic_publish_enabled": False,
            "external_social_integrations_connected": False,
            "external_publish_attempted": False,
            "external_post_created": False,
        },
        "product_observations": {
            "registration_status": register["status"],
            "login_status": login["status"],
            "api_key_rotation_status": api_key_rotation_status,
            "integrations_inventory": integrations,
            "executions": executions,
        },
        "evaluation_boundary": {
            "actual_product_execution_observed": True,
            "successful_schedule_observed": any(
                execution["actual_local_product_response"]["status"] in {200, 201}
                for execution in executions
            ),
            "failure_response_observed": any(
                execution["actual_local_product_response"]["status"] >= 400
                for execution in executions
            ),
            "best_time_evidence_observed": False,
            "cross_network_analytics_observed": False,
            "market_response_observed": False,
            "product_preference_observed": False,
            "named_human_review_observed": False,
            "known_limitations": [
                "No external social account was connected, so provider-native publication and analytics were not exercised.",
                "A local API response is product-runtime evidence, not evidence of publishability, preference, lift, virality, conversion or revenue.",
                "All four release requests remained behind the named-human approval boundary.",
            ],
        },
        "captured_at": captured_at,
    }
    artifact = seal(artifact)

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    artifact_path = output / "postiz-raw-baseline.json"
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt = {
        "schema": "ProofLaunchNamedProductBaselineCaptureV1",
        "capture_slot_id": CAPTURE_SLOT_ID,
        "category_id": "content_scheduling_operations",
        "reference_product": "Postiz",
        "reference_product_url": "https://postiz.com/",
        "frozen_brief_sha256": FROZEN_BRIEF_SHA256,
        "acquisition_method": "authorized_product_use",
        "operator_id": "codex-local-runner-20260804",
        "provider_model_or_version": (
            f"Postiz OSS {args.postiz_version} {args.postiz_image_digest[:31]} / "
            f"official compose {args.official_compose_revision[:12]}"
        ),
        "captured_at": captured_at,
        "rights_attestation": {
            "authorized_to_evaluate_and_retain": True,
            "same_frozen_brief_without_hidden_editing": True,
            "provider_and_version_recorded_truthfully": True,
        },
        "artifact": {
            "name": artifact_path.name,
            "mime_type": "application/json",
            "bytes": artifact_path.stat().st_size,
            "sha256": sha256_file(artifact_path),
        },
    }
    receipt = seal(receipt)
    capture_path = output / "capture.json"
    capture_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "artifact": str(artifact_path.relative_to(ROOT)),
                "artifact_sha256": receipt["artifact"]["sha256"],
                "capture": str(capture_path.relative_to(ROOT)),
                "connected_integrations": 0,
                "external_posts_created": 0,
                "responses": [item["actual_local_product_response"]["status"] for item in executions],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
