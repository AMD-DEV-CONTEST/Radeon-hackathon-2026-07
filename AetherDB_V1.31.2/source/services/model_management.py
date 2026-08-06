"""Controlled provider/model diagnostics for the AI management API."""

from __future__ import annotations

import ipaddress
import json
import socket
import time
import uuid
from urllib.parse import urlparse

import requests

from services.database_registry import _get_registry_conn
from services.model_registry import (
    ALWAYS_BLOCKED_HOSTS,
    LOCAL_PROVIDER_TYPES,
    get_model_profile,
    get_provider,
)
from services.model_routing import CredentialResolver


MAX_RESPONSE_BYTES = 2 * 1024 * 1024
FIXED_TEST_PROMPT = "Reply with exactly OK."
TRUSTED_REMOTE_PROVIDER_HOSTS = {
    "deepseek": {"api.deepseek.com"},
}
DESKTOP_PROXY_NETWORK = ipaddress.ip_network("198.18.0.0/15")


class ModelDiagnosticError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.safe_message = message


def _validate_runtime_target(provider: dict):
    parsed = urlparse(provider["base_url"])
    host = (parsed.hostname or "").lower()
    is_local = provider["provider_type"] in LOCAL_PROVIDER_TYPES
    if host in ALWAYS_BLOCKED_HOSTS:
        raise ModelDiagnosticError("TARGET_BLOCKED", "Provider target is blocked")

    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(host, parsed.port, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise ModelDiagnosticError("DNS_FAILED", "Provider host could not be resolved") from exc

    for value in addresses:
        address = ipaddress.ip_address(value)
        if (
            address.is_link_local
            or address.is_multicast
            or address.is_unspecified
            or address.is_reserved
        ):
            raise ModelDiagnosticError("TARGET_BLOCKED", "Provider target address is blocked")
        if is_local and not (address.is_private or address.is_loopback):
            raise ModelDiagnosticError(
                "TARGET_BLOCKED", "Local provider resolved to a public address"
            )
        trusted_remote_host = host in TRUSTED_REMOTE_PROVIDER_HOSTS.get(
            provider["provider_type"], set()
        )
        trusted_desktop_proxy = trusted_remote_host and address in DESKTOP_PROXY_NETWORK
        if not is_local and not address.is_global and not trusted_desktop_proxy:
            raise ModelDiagnosticError(
                "TARGET_BLOCKED", "Remote provider resolved to a non-public address"
            )


def _credential_headers(provider: dict, credential: str | None = None) -> dict:
    if credential is None:
        try:
            credential = CredentialResolver().resolve(provider.get("credential_ref"))
        except (ValueError, RuntimeError) as exc:
            raise ModelDiagnosticError(
                "CREDENTIAL_UNAVAILABLE", "Provider credential is not configured"
            ) from exc
    if not credential:
        return {}
    if provider["api_format"] in {"openai", "openai_chat", "openai_compatible"}:
        return {"Authorization": f"Bearer {credential}"}
    return {"X-API-Key": credential}


def _request_json(
    provider: dict,
    method: str,
    endpoint: str,
    payload: dict | None = None,
    credential: str | None = None,
):
    _validate_runtime_target(provider)
    if not endpoint.startswith("/") or "://" in endpoint:
        raise ModelDiagnosticError("INVALID_ENDPOINT", "Provider endpoint must be relative")
    try:
        response = requests.request(
            method,
            f"{provider['base_url'].rstrip('/')}{endpoint}",
            headers={"Accept": "application/json", **_credential_headers(provider, credential)},
            json=payload,
            timeout=(5, 20),
            allow_redirects=False,
        )
    except requests.Timeout as exc:
        raise ModelDiagnosticError("TIMEOUT", "Provider request timed out") from exc
    except requests.RequestException as exc:
        raise ModelDiagnosticError("CONNECTION_FAILED", "Provider connection failed") from exc

    if 300 <= response.status_code < 400:
        raise ModelDiagnosticError("REDIRECT_BLOCKED", "Provider redirect was blocked")
    if response.status_code == 401 or response.status_code == 403:
        raise ModelDiagnosticError("AUTH_FAILED", "Provider authentication failed")
    if not 200 <= response.status_code < 300:
        raise ModelDiagnosticError(
            f"HTTP_{response.status_code}", f"Provider returned HTTP {response.status_code}"
        )
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise ModelDiagnosticError("RESPONSE_TOO_LARGE", "Provider response exceeded size limit")
    try:
        return response.json()
    except ValueError as exc:
        raise ModelDiagnosticError("INVALID_RESPONSE", "Provider returned invalid JSON") from exc


def discover_model_names(provider: dict, credential: str | None = None) -> list[str]:
    endpoint = provider.get("models_endpoint") or "/models"
    payload = _request_json(provider, "GET", endpoint, credential=credential)
    raw_models = payload.get("data", payload.get("models", []))
    names = []
    for item in raw_models if isinstance(raw_models, list) else []:
        name = item.get("id") or item.get("name") or item.get("model") if isinstance(item, dict) else item
        if isinstance(name, str) and name.strip() and name.strip() not in names:
            names.append(name.strip())
    if not names:
        raise ModelDiagnosticError("NO_MODELS", "Provider returned no usable chat models")
    return names


def _record_result(
    *, provider_id: str, model_profile_id: str | None, test_type: str,
    status: str, latency_ms: int, capabilities: dict, error_code: str | None = None,
    error_message: str | None = None,
):
    result_id = uuid.uuid4().hex
    conn = _get_registry_conn()
    try:
        conn.execute(
            "INSERT INTO model_test_results "
            "(id,provider_id,model_profile_id,test_type,status,latency_ms,capability_summary,error_code,error_message) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                result_id,
                provider_id,
                model_profile_id,
                test_type,
                status,
                latency_ms,
                json.dumps(capabilities, ensure_ascii=True, sort_keys=True),
                error_code,
                error_message,
            ),
        )
        if model_profile_id:
            conn.execute(
                "UPDATE model_profiles SET health_status=?,remote_status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (
                    "healthy" if status == "passed" else "unhealthy",
                    "available" if status == "passed" else "unavailable",
                    model_profile_id,
                ),
            )
        else:
            conn.execute(
                "UPDATE model_providers SET health_status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                ("healthy" if status == "passed" else "unhealthy", provider_id),
            )
        conn.commit()
    finally:
        conn.close()
    if model_profile_id:
        provider = get_provider(provider_id)
        if provider and provider["provider_type"] in LOCAL_PROVIDER_TYPES:
            from services.ollama_observability import mark_probe_result

            mark_probe_result(
                model_profile_id,
                verified=status == "passed",
                error_code=error_code,
            )
    return result_id


def _run_diagnostic(provider: dict, model_profile: dict | None = None):
    started_at = time.monotonic()
    test_type = "model_basic" if model_profile else "provider_connection"
    capabilities = {}
    try:
        if model_profile is None:
            endpoint = provider.get("models_endpoint")
            if not endpoint:
                endpoint = "/api/tags" if provider["provider_type"] in LOCAL_PROVIDER_TYPES else "/models"
            payload = _request_json(provider, "GET", endpoint)
            model_count = len(payload.get("models", payload.get("data", [])))
            capabilities = {"model_discovery": True, "reported_model_count": model_count}
        elif model_profile["model_type"] == "embedding":
            if provider["provider_type"] not in LOCAL_PROVIDER_TYPES:
                raise ModelDiagnosticError(
                    "UNSUPPORTED_TEST", "Cloud embedding diagnostics are not enabled"
                )
            payload = _request_json(
                provider,
                "POST",
                "/api/embed",
                {"model": model_profile["provider_model_name"], "input": ["AetherDB"]},
            )
            embeddings = payload.get("embeddings") or []
            if not embeddings or not embeddings[0]:
                raise ModelDiagnosticError("INVALID_RESPONSE", "Embedding response was empty")
            capabilities = {
                "supports_embedding": True,
                "embedding_dimensions": len(embeddings[0]),
            }
        else:
            if provider["provider_type"] in LOCAL_PROVIDER_TYPES:
                endpoint = "/api/chat"
                request_payload = {
                    "model": model_profile["provider_model_name"],
                    "messages": [{"role": "user", "content": FIXED_TEST_PROMPT}],
                    "stream": False,
                    "options": {"num_predict": 8},
                }
            else:
                endpoint = "/chat/completions"
                request_payload = {
                    "model": model_profile["provider_model_name"],
                    "messages": [{"role": "user", "content": FIXED_TEST_PROMPT}],
                    "stream": False,
                    "max_tokens": 8,
                }
            payload = _request_json(provider, "POST", endpoint, request_payload)
            response_present = bool(payload.get("message") or payload.get("choices"))
            if not response_present:
                raise ModelDiagnosticError("INVALID_RESPONSE", "Model response content was missing")
            capabilities = {
                "supports_chat": True,
                "supports_streaming": bool(model_profile["supports_streaming"]),
                "supports_json": bool(model_profile["supports_json_mode"]),
                "supports_tools": bool(model_profile["supports_tools"]),
            }

        latency_ms = int((time.monotonic() - started_at) * 1000)
        result_id = _record_result(
            provider_id=provider["id"],
            model_profile_id=model_profile["id"] if model_profile else None,
            test_type=test_type,
            status="passed",
            latency_ms=latency_ms,
            capabilities=capabilities,
        )
        return {
            "test_id": result_id,
            "status": "passed",
            "latency_ms": latency_ms,
            "capabilities": capabilities,
        }
    except ModelDiagnosticError as exc:
        latency_ms = int((time.monotonic() - started_at) * 1000)
        result_id = _record_result(
            provider_id=provider["id"],
            model_profile_id=model_profile["id"] if model_profile else None,
            test_type=test_type,
            status="failed",
            latency_ms=latency_ms,
            capabilities=capabilities,
            error_code=exc.code,
            error_message=exc.safe_message,
        )
        return {
            "test_id": result_id,
            "status": "failed",
            "latency_ms": latency_ms,
            "error": {"code": exc.code, "message": exc.safe_message},
        }


def test_provider_connection(provider_id: str):
    provider = get_provider(provider_id)
    if not provider:
        raise KeyError(provider_id)
    return {"provider_id": provider_id, **_run_diagnostic(provider)}


def test_model_profile(model_profile_id: str):
    profile = get_model_profile(model_profile_id)
    if not profile:
        raise KeyError(model_profile_id)
    provider = get_provider(profile["provider_id"])
    if not provider:
        raise KeyError(profile["provider_id"])
    return {
        "provider_id": provider["id"],
        "model_profile_id": model_profile_id,
        **_run_diagnostic(provider, profile),
    }


def list_test_results(
    *, provider_id: str | None = None, model_profile_id: str | None = None, limit: int = 20,
):
    conditions = []
    values = []
    if provider_id:
        conditions.append("provider_id=?")
        values.append(provider_id)
    if model_profile_id:
        conditions.append("model_profile_id=?")
        values.append(model_profile_id)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    conn = _get_registry_conn()
    try:
        rows = conn.execute(
            "SELECT id,provider_id,model_profile_id,test_type,status,latency_ms,"
            "capability_summary,error_code,error_message,created_at FROM model_test_results "
            f"{where} ORDER BY created_at DESC,id DESC LIMIT ?",
            (*values, max(1, min(int(limit), 100))),
        )
        results = []
        for row in rows:
            item = dict(row)
            item["capabilities"] = json.loads(item.pop("capability_summary") or "{}")
            results.append(item)
        return results
    finally:
        conn.close()
