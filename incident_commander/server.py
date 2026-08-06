from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .analyzer import AIIncidentAnalyzer, IncidentAnalyzer
from .agent import AgentError, InvestigationService, default_store
from .llm import OpenAICompatibleClient
from .models import Incident

STATIC_DIR = Path(__file__).resolve().parent.parent / "web"
SAMPLE_PATH = Path(__file__).resolve().parent.parent / "samples" / "checkout-latency.json"


def build_analyzer() -> IncidentAnalyzer | AIIncidentAnalyzer:
    client = OpenAICompatibleClient()
    if os.getenv("LIC_ENABLE_LLM", "0").lower() in {"1", "true", "yes"}:
        return AIIncidentAnalyzer(client)
    return IncidentAnalyzer()


def runtime_status(analyzer: IncidentAnalyzer | AIIncidentAnalyzer) -> dict[str, object]:
    if isinstance(analyzer, AIIncidentAnalyzer):
        client = analyzer.client
        hostname = urlparse(client.base_url).hostname
        local_endpoint = hostname in {"127.0.0.1", "localhost", "::1"}
        evidence = _runtime_evidence(client.model) if local_endpoint else None
        mode = "local-radeon" if evidence else ("local-unverified" if local_endpoint else "remote-api")
        status: dict[str, object] = {
            "status": "ok",
            "engine": "hybrid-radeon-llm",
            "mode": mode,
            "model": client.model,
            "base_url": client.base_url,
            "safety_fallback": "deterministic-baseline",
        }
        if evidence:
            status["runtime_evidence"] = evidence
        return status
    return {
        "status": "ok",
        "engine": "deterministic-baseline",
        "mode": "offline-safe",
        "model": None,
        "safety_fallback": "active",
    }


def _runtime_evidence(expected_model: str) -> dict[str, object] | None:
    path_value = os.getenv("LIC_RUNTIME_EVIDENCE", "").strip()
    if not path_value:
        return None
    try:
        payload = json.loads(Path(path_value).read_text(encoding="utf-8"))
        timestamp = datetime.fromisoformat(str(payload["timestamp"]).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            return None
        age = datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)
        architecture = payload.get("gpu_architecture") or payload.get("architecture")
        required = (
            payload.get("model") == expected_model,
            bool(payload.get("rocm_version")),
            bool(architecture),
            isinstance(payload.get("vram_mb"), int),
            isinstance(payload.get("compute_units"), int),
            bool(payload.get("vllm_version")),
            -timedelta(minutes=5) <= age <= timedelta(hours=24),
        )
        if not all(required):
            return None
        return {
            "timestamp": timestamp.astimezone(timezone.utc).isoformat(),
            "model": expected_model,
            "rocm_version": str(payload["rocm_version"]),
            "gpu_architecture": str(architecture),
            "vram_mb": int(payload["vram_mb"]),
            "compute_units": int(payload["compute_units"]),
            "vllm_version": str(payload["vllm_version"]),
        }
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


class OfflineAgentClient:
    def choose_tool(self, *args: object, **kwargs: object) -> object:
        raise RuntimeError("local model is disabled")

    def complete(self, *args: object, **kwargs: object) -> object:
        raise RuntimeError("local model is disabled")


def build_agent_service(analyzer: IncidentAnalyzer | AIIncidentAnalyzer) -> InvestigationService:
    client = analyzer.client if isinstance(analyzer, AIIncidentAnalyzer) else OfflineAgentClient()
    return InvestigationService(default_store(), client=client, runtime=lambda: runtime_status(analyzer))


class Handler(BaseHTTPRequestHandler):
    analyzer = build_analyzer()
    agent_service = build_agent_service(analyzer)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json(runtime_status(self.analyzer))
            return
        if path == "/api/sample":
            self._json(json.loads(SAMPLE_PATH.read_text(encoding="utf-8")))
            return
        match = re.fullmatch(r"/api/investigations/([A-Za-z0-9_-]+)", path)
        if match:
            try:
                self._investigation(self.agent_service.get(match.group(1)))
            except AgentError as exc:
                self._agent_error(exc)
            return
        relative = "index.html" if path == "/" else path.lstrip("/")
        target = (STATIC_DIR / relative).resolve()
        if STATIC_DIR not in target.parents or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._read_payload()
            if path == "/api/analyze":
                report = self.analyzer.analyze(Incident.from_dict(payload))
                self._json(report.to_dict())
                return
            if path == "/api/investigations":
                self._investigation(self.agent_service.create(payload.get("request_id"), payload.get("incident")))
                return
            next_match = re.fullmatch(r"/api/investigations/([A-Za-z0-9_-]+)/next", path)
            if next_match:
                self._investigation(
                    self.agent_service.next(next_match.group(1), payload.get("request_id"), payload.get("expected_version"))
                )
                return
            message_match = re.fullmatch(r"/api/investigations/([A-Za-z0-9_-]+)/messages", path)
            if message_match:
                self._investigation(
                    self.agent_service.message(
                        message_match.group(1),
                        payload.get("request_id"),
                        payload.get("expected_version"),
                        payload.get("content", ""),
                    )
                )
                return
            decision_match = re.fullmatch(
                r"/api/investigations/([A-Za-z0-9_-]+)/actions/([A-Za-z0-9_-]+)/decision", path
            )
            if decision_match:
                self._investigation(
                    self.agent_service.decision(
                        decision_match.group(1),
                        payload.get("request_id"),
                        payload.get("expected_version"),
                        decision_match.group(2),
                        payload.get("decision"),
                        payload.get("comment"),
                    )
                )
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except AgentError as exc:
            self._agent_error(exc)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def _read_payload(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 1_000_000:
            raise ValueError("request body must be between 1 byte and 1 MB")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _investigation(self, investigation: dict[str, object]) -> None:
        self._json({"schema_version": 1, "investigation": investigation})

    def _agent_error(self, exc: AgentError) -> None:
        self._json({"error": str(exc), "code": exc.code}, status=HTTPStatus(exc.status))

    def _json(self, value: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        content = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[http] {self.address_string()} {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Local Incident Commander")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Local Incident Commander: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
