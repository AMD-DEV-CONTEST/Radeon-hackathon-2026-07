"""Zero-dependency localhost dashboard for the private screening pipeline."""

from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import mimetypes
from pathlib import Path
import re
from typing import Any, Mapping, Sequence
from urllib.parse import unquote, urlparse

from .analysis import load_parameter_ranges
from .pipeline import run_full_demo
from .gcs_validation import load_bradbury_rocks_v1, predict_cs_isotherm_envelope
from .model_selection import ModelCandidate, ModelSelectionAgent
from .replay import ReplayVerificationError, verify_bundle


_SESSION = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MAX_BODY = 1_000_000
_STATIC_INDEX = Path(__file__).with_name("static") / "index.html"
_PACKAGE_DATA = Path(__file__).with_name("data")
_PUBLIC_ARTIFACTS = frozenset(
    {
        "report.json",
        "report.md",
        "concentration_vs_time.svg",
        "workflow.json",
        "sensitivity.json",
        "sensitivity.csv",
        "uncertainty.json",
        "uncertainty.csv",
        "uncertainty.svg",
        "manifest.json",
    }
)


def validate_host(host: str, allow_network: bool) -> str:
    if allow_network:
        raise ValueError("network dashboard binds are disabled; use a loopback host")
    if host == "localhost":
        return host
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError as exc:
        raise ValueError("dashboard host must be a loopback address") from exc
    if not loopback:
        raise ValueError("dashboard host must be a loopback address")
    return host


def _load_object(path: Path, label: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return payload


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(v) for v in value]
    return value


class DashboardApplication:
    def __init__(
        self,
        scenario_path: str | Path,
        knowledge_dir: str | Path,
        ranges_path: str | Path,
        output_root: str | Path,
        uncertainty_samples: int = 256,
        seed: int = 42,
    ) -> None:
        self.default_case = _load_object(Path(scenario_path), "scenario")
        self.knowledge_dir = Path(knowledge_dir)
        self.parameter_ranges = load_parameter_ranges(
            _load_object(Path(ranges_path), "uncertainty ranges")
        )
        self.output_root = Path(output_root)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.uncertainty_samples = uncertainty_samples
        self.seed = seed

    def e4_primary_metadata(self) -> dict[str, Any]:
        path = _PACKAGE_DATA / "parameters" / "bradbury_baeyens_gcs_v2.json"
        return {"schema_version": "1.0.0", "model_version": "bradbury-baeyens-gcs-2.0",
                "parameter_file": path.name, "metadata": _load_object(path, "GCS parameters")}

    def e4_paper_rocks(self) -> dict[str, Any]:
        path = _PACKAGE_DATA / "validation" / "bradbury_2000_rocks_v1.json"
        rocks = load_bradbury_rocks_v1(path)
        return {"schema_version": "1.0.0", "citation": "Bradbury (2000) reconstruction",
                "rocks": [{"name": r.name, "location": r.location, "provenance": r.provenance,
                            "envelope": predict_cs_isotherm_envelope(r)} for r in rocks]}

    def e4_source_terms(self) -> dict[str, Any]:
        return {"schema_version": "1.0.0", "contract_version": "source-term-1.0",
                "models": [{"name": n, "kind": k, "read_only": True} for n, k in (
                    ("maintained_boundary", "constant"), ("finite_duration_boundary", "finite"),
                    ("instantaneous_pulse", "pulse"), ("constant_rate_release", "rate"),
                    ("piecewise_linear_series", "series"))]}

    def run_case(self, case: Mapping[str, Any], session_id: str) -> dict[str, Any]:
        if not _SESSION.fullmatch(session_id):
            raise ValueError("session_id must use 1-64 letters, numbers, '-' or '_'")
        run_dir = self.output_root / session_id
        artifacts = run_full_demo(
            case,
            run_dir,
            knowledge_dir=self.knowledge_dir,
            parameter_ranges=self.parameter_ranges,
            uncertainty_samples=self.uncertainty_samples,
            seed=self.seed,
            session_id=session_id,
        )
        report = json.loads(artifacts["report_json"].read_text(encoding="utf-8"))
        workflow = json.loads(artifacts["workflow_json"].read_text(encoding="utf-8"))
        return {
            "report": report,
            "workflow": workflow,
            "artifacts": {
                name: f"/artifacts/{session_id}/{path.name}"
                for name, path in artifacts.items()
                if name != "memory_jsonl"
            },
        }


class _DashboardHandler(BaseHTTPRequestHandler):
    app: DashboardApplication
    server_version = "NuclidePath/0.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> Any:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("request body size is invalid") from exc
        if length <= 0 or length > _MAX_BODY:
            raise ValueError("request body size is invalid")
        return json.loads(self.rfile.read(length))

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route == "/":
            self._bytes(_STATIC_INDEX.read_bytes(), "text/html; charset=utf-8")
            return
        if route == "/api/health":
            self._json({"status": "ok", "mode": "local-only"})
            return
        if route == "/api/default-case":
            self._json(self.app.default_case)
            return
        if route == "/api/v1/models/gcs/primary":
            self._json(self.app.e4_primary_metadata()); return
        if route == "/api/v1/paper-rocks":
            self._json(_jsonable(self.app.e4_paper_rocks())); return
        if route == "/api/v1/source-terms":
            self._json(self.app.e4_source_terms()); return
        if route.startswith("/artifacts/"):
            self._serve_artifact(route)
            return
        self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def _serve_artifact(self, route: str) -> None:
        parts = unquote(route).split("/")
        if len(parts) != 4 or not _SESSION.fullmatch(parts[2]):
            self._json({"error": "invalid artifact path"}, HTTPStatus.BAD_REQUEST)
            return
        filename = parts[3]
        if Path(filename).name != filename:
            self._json({"error": "invalid artifact path"}, HTTPStatus.BAD_REQUEST)
            return
        if filename not in _PUBLIC_ARTIFACTS:
            self._json(
                {"error": "artifact is not publicly downloadable"},
                HTTPStatus.NOT_FOUND,
            )
            return
        path = self.app.output_root / parts[2] / filename
        if not path.is_file():
            self._json({"error": "artifact not found"}, HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".svg":
            content_type = "image/svg+xml"
        self._bytes(path.read_bytes(), content_type)

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route == "/api/v1/replay/verify":
            try:
                payload = self._read_json_body()
                requested = Path(payload["path"]).resolve()
                root = self.app.output_root.resolve()
                if root not in requested.parents or not requested.is_dir():
                    self._json({"error": "replay path must be a directory within results root"}, HTTPStatus.FORBIDDEN); return
                self._json({"valid": verify_bundle(requested).valid, "path": str(requested.relative_to(root))})
            except (KeyError, OSError, TypeError, json.JSONDecodeError, ReplayVerificationError, ValueError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if route == "/api/v1/model-selection":
            try:
                payload = self._read_json_body()
                candidates = [ModelCandidate(**item) for item in payload["candidates"]]
                result = ModelSelectionAgent().select(payload["request"], candidates)
                self._json({"schema_version": "1.0.0", "eligible": list(result.eligible), "selected": list(result.selected), "rejected": {k: list(v) for k, v in result.rejected.items()}})
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if route != "/api/run":
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._read_json_body()
            if not isinstance(payload, dict) or not isinstance(payload.get("case"), dict):
                raise ValueError("request requires a case object")
            session_id = payload.get("session_id", "web-session")
            if not isinstance(session_id, str):
                raise ValueError("session_id must be a string")
            self._json(self.app.run_case(payload["case"], session_id))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


def create_server(
    app: DashboardApplication, host: str = "127.0.0.1", port: int = 8080
) -> ThreadingHTTPServer:
    host = validate_host(host, False)

    class Handler(_DashboardHandler):
        pass

    Handler.app = app
    return ThreadingHTTPServer((host, port), Handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the NuclidePath local dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--scenario",
        type=Path,
        default=_PACKAGE_DATA / "scenarios" / "cs137_emergency_full.json",
    )
    parser.add_argument(
        "--knowledge-dir", type=Path, default=_PACKAGE_DATA / "knowledge"
    )
    parser.add_argument(
        "--uncertainty-ranges",
        type=Path,
        default=_PACKAGE_DATA / "scenarios" / "uncertainty_ranges.json",
    )
    parser.add_argument("--output", type=Path, default=Path("results/dashboard"))
    parser.add_argument("--samples", type=int, default=256)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    host = validate_host(args.host, False)
    app = DashboardApplication(
        args.scenario,
        args.knowledge_dir,
        args.uncertainty_ranges,
        args.output,
        uncertainty_samples=args.samples,
    )
    server = create_server(app, host, args.port)
    print(f"NuclidePath dashboard: http://{host}:{server.server_address[1]}")
    print("Privacy mode: local-only")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
