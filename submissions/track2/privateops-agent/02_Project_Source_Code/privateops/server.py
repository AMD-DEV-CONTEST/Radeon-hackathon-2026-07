from __future__ import annotations

import json
import mimetypes
import os
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from privateops.agent import PrivateOpsAgent
from privateops.config import Settings
from privateops.permissions import classify_intent
from privateops.provider_runtime import RuntimeProviderManager
from privateops.radeon_evidence import RadeonEvidenceStore

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"


@dataclass(frozen=True)
class Route:
    path: str


@dataclass
class PrivateOpsHttpApp:
    agent: PrivateOpsAgent
    routes: list[Route]


def build_agent_from_env() -> PrivateOpsAgent:
    return PrivateOpsAgent(settings=Settings.from_env())


def create_app(agent: PrivateOpsAgent | None = None) -> PrivateOpsHttpApp:
    return PrivateOpsHttpApp(
        agent=agent or build_agent_from_env(),
        routes=[
            Route("/"),
            Route("/api/health"),
            Route("/api/status"),
            Route("/api/chat"),
            Route("/api/search"),
            Route("/api/memory"),
            Route("/api/permission"),
            Route("/api/rocm-profile"),
            Route("/api/rocm-evidence"),
            Route("/api/audit"),
            Route("/api/audit/export"),
            Route("/api/confirm"),
            Route("/api/benchmarks"),
            Route("/api/benchmarks/export.csv"),
            Route("/api/provider/test"),
            Route("/api/provider/config"),
        ],
    )


class PrivateOpsHandler(BaseHTTPRequestHandler):
    app: PrivateOpsHttpApp

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._send_file(WEB_DIR / "index.html")
        elif path.startswith("/static/"):
            relative = unquote(path.removeprefix("/static/"))
            self._send_file(WEB_DIR / relative)
        elif path == "/api/health":
            self._send_json(
                {
                    "status": "ok",
                    "app": "PrivateOps Agent",
                    "mode": self.app.agent.status()["provider_mode"],
                    "provider": self.app.agent.provider.name,
                }
            )
        elif path == "/api/status":
            self._send_json(self.app.agent.status())
        elif path == "/api/memory":
            self._send_json({"memory": self.app.agent.memory()})
        elif path == "/api/rocm-profile":
            self._send_json(self.app.agent.load_rocm_profile().to_dict())
        elif path == "/api/rocm-evidence":
            self._send_json(RadeonEvidenceStore(ROOT / "submission" / "evidence").summary())
        elif path == "/api/audit":
            self._send_json({"entries": self.app.agent.audit_trail()})
        elif path == "/api/audit/export":
            self._send_json(self.app.agent.audit.export(), download_name="privateops-audit.json")
        elif path == "/api/benchmarks":
            self._send_json(self.app.agent.benchmarks.export())
        elif path == "/api/benchmarks/export.csv":
            self._send_bytes(
                self.app.agent.benchmarks.export_csv().encode("utf-8-sig"),
                "text/csv; charset=utf-8",
                download_name="privateops-benchmarks.csv",
            )
        else:
            self._send_error("not_found", "Route not found.", 404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
            if path == "/api/chat":
                prompt = str(payload.get("prompt", "")).strip()
                if not prompt:
                    raise ApiError("missing_prompt", "A non-empty prompt is required.", 400)
                if self.app.agent.provider.name == "deterministic-local":
                    raise ApiError(
                        "provider_required",
                        "Please enter and apply a model API before asking the Agent.",
                        409,
                    )
                response = self.app.agent.ask(
                    prompt,
                    str(payload.get("confirmation_token", "")),
                    str(payload.get("response_language", "en")),
                )
                self._send_json(response.to_dict())
            elif path == "/api/search":
                results = [item.to_dict() for item in self.app.agent.search(str(payload.get("query", "")))]
                self._send_json({"results": results})
            elif path == "/api/permission":
                self._send_json(classify_intent(str(payload.get("prompt", ""))).to_dict())
            elif path == "/api/confirm":
                confirmation = self.app.agent.issue_confirmation(str(payload.get("prompt", "")))
                self._send_json(confirmation.to_dict(), status=201)
            elif path == "/api/benchmarks":
                self._send_json(self.app.agent.benchmarks.record(payload), status=201)
            elif path == "/api/rocm-profile":
                profile = self.app.agent.save_rocm_profile(
                    str(payload.get("gpu_name", "")),
                    str(payload.get("rocm_version", "")),
                    str(payload.get("model_endpoint", "")),
                    str(payload.get("notes", "")),
                )
                self._send_json(profile.to_dict())
            elif path == "/api/provider/test":
                self._send_json(RuntimeProviderManager(self.app.agent).test(payload))
            elif path == "/api/provider/config":
                self._send_json(RuntimeProviderManager(self.app.agent).apply(payload))
            else:
                self._send_error("not_found", "Route not found.", 404)
        except ApiError as exc:
            self._send_error(exc.code, exc.message, exc.status)
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            self._send_error("provider_unavailable", f"Local model provider failed: {exc}", 502)
        except ValueError as exc:
            self._send_error("validation_error", str(exc), 400)

    def do_DELETE(self) -> None:
        path = unquote(urlparse(self.path).path)
        prefix = "/api/audit/"
        if not path.startswith(prefix):
            self._send_error("not_found", "Route not found.", 404)
            return
        audit_id = path.removeprefix(prefix)
        try:
            deleted = self.app.agent.audit.delete(audit_id)
        except ValueError:
            self._send_error("invalid_audit_id", "A valid audit ID is required.", 400)
            return
        except OSError:
            self._send_error("audit_delete_failed", "The audit record could not be deleted safely.", 500)
            return
        if not deleted:
            self._send_error("audit_not_found", "Audit record not found.", 404)
            return
        self._send_json({"deleted": audit_id})

    def log_message(self, format: str, *args) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_048_576:
            raise ApiError("payload_too_large", "Request body exceeds 1 MiB.", 413)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            raise ApiError("invalid_json", "Request body must be valid JSON.", 400)
        if not isinstance(parsed, dict):
            raise ApiError("invalid_json", "Request body must be a JSON object.", 400)
        return parsed

    def _send_json(self, payload: dict, status: int = 200, download_name: str = "") -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(data, "application/json; charset=utf-8", status, download_name)

    def _send_error(self, code: str, message: str, status: int) -> None:
        self._send_json({"error": {"code": code, "message": message}}, status=status)

    def _send_bytes(self, data: bytes, content_type: str, status: int = 200, download_name: str = "") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        if download_name:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path) -> None:
        resolved = path.resolve()
        if not resolved.is_relative_to(WEB_DIR.resolve()) or not resolved.exists() or not resolved.is_file():
            self._send_error("not_found", "File not found.", 404)
            return
        data = resolved.read_bytes()
        content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def create_http_server(
    app: PrivateOpsHttpApp,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> ThreadingHTTPServer:
    handler = type("ConfiguredPrivateOpsHandler", (PrivateOpsHandler,), {"app": app})
    return ThreadingHTTPServer((host, port), handler)


def run_server(app: PrivateOpsHttpApp, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = create_http_server(app, host, port)
    print(f"PrivateOps Agent running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    run_server(create_app())


if __name__ == "__main__":
    main()
