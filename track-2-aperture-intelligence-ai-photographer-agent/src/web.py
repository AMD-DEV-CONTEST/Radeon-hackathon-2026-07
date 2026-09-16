"""Dependency-free local web demo for the AI Photographer Agent."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import re
import tempfile
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
MAX_REQUEST_BYTES = 28 * 1024 * 1024
ALLOWED_MIME = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
DEFAULT_PHOTOGRAPHY_REQUEST = (
    "Turn this reference photo into a practical recreation plan for an everyday user. "
    "Explain camera distance, height, angle, and background control; tell each subject "
    "how to stand, move, and interact; and identify visible failure risks."
)

_AGENT: Any | None = None
_AGENT_LOCK = Lock()
_INFERENCE_LOCK = Lock()


class _InputError(ValueError):
    """A user-correctable request/image validation failure."""


def _get_agent() -> Any:
    global _AGENT
    if _AGENT is None:
        with _AGENT_LOCK:
            if _AGENT is None:
                from src.agent.orchestrator import PhotographerAgent

                _AGENT = PhotographerAgent()
    return _AGENT


def _health() -> dict[str, Any]:
    import torch

    available = torch.cuda.is_available()
    return {
        "status": "ready" if available and torch.version.hip else "unavailable",
        "gpu_available": available,
        "hip": torch.version.hip,
        "torch": torch.__version__,
        "gpu": torch.cuda.get_device_name(0) if available else None,
        "vram_gib": (
            round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2)
            if available
            else None
        ),
        "privacy": "Local processing only; no external AI API.",
        "output_mode": "deterministic AI photography guidance card",
    }


def _decode_image(data_url: str) -> tuple[bytes, str]:
    match = re.fullmatch(
        r"data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=\r\n]+)", data_url
    )
    if not match:
        raise _InputError("Only JPEG, PNG, and WebP images are supported.")
    mime, encoded = match.groups()
    try:
        payload = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise _InputError("The uploaded image is not valid base64 data.") from exc
    if not payload or len(payload) > 20 * 1024 * 1024:
        raise _InputError("The image must be between 1 byte and 20 MB.")
    return payload, ALLOWED_MIME[mime]


class AgentHandler(BaseHTTPRequestHandler):
    server_version = "ApertureAMD/1.0"

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/", "/index.html"}:
            self._send_file(WEB_DIR / "demo.html", "text/html; charset=utf-8")
        elif self.path == "/api/health":
            self._send_json(_health())
        else:
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/analyze":
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise _InputError("Request body is empty or too large.")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise _InputError("Request body must be a JSON object.")
            request = DEFAULT_PHOTOGRAPHY_REQUEST
            if body.get("generate_concept", False) is True:
                raise _InputError(
                    "Image generation is disabled; the result is a deterministic "
                    "AI photography execution card."
                )
            image_bytes, suffix = _decode_image(str(body.get("image", "")))
            filename = Path(
                str(body.get("filename", f"upload{suffix}")).replace("\\", "/")
            ).name
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp:
                temp.write(image_bytes)
                temp_path = Path(temp.name)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as overlay_temp:
                overlay_path = Path(overlay_temp.name)
            try:
                with _INFERENCE_LOCK:
                    from src.tools.image_orientation import (
                        normalize_image_orientation,
                    )

                    try:
                        orientation = normalize_image_orientation(temp_path)
                    except (OSError, ValueError):
                        # The agent performs the authoritative image validation.
                        # This fallback keeps injected test agents isolated.
                        orientation = {
                            "status": "deferred_to_agent_validation",
                            "rotation_degrees": 0,
                            "method": "none",
                        }
                    result = _get_agent().run(
                        temp_path,
                        request,
                        generate_overlay=True,
                        overlay_path=overlay_path,
                        local_person_geometry=orientation.get(
                            "person_geometry"
                        ),
                    )
                result["image"]["filename"] = filename
                result["image"]["orientation"] = orientation
                overlay_bytes = overlay_path.read_bytes()
                result["pose_card"].pop("path", None)
                result["pose_card"]["data_url"] = (
                    "data:image/png;base64,"
                    + base64.b64encode(overlay_bytes).decode("ascii")
                )
                result["pose_card"]["filename"] = (
                    f"{Path(filename).stem}-ai-photography-guidance-card.png"
                )
                self._send_json(result)
            finally:
                temp_path.unlink(missing_ok=True)
                overlay_path.unlink(missing_ok=True)
        except (_InputError, json.JSONDecodeError) as exc:
            self.log_error("invalid analysis request: %r", exc)
            self._send_json(
                {"error": "The image could not be processed. Check the file format and upload it again."},
                HTTPStatus.BAD_REQUEST,
            )
        except Exception as exc:  # Return a clean UI error while retaining server logs.
            self.log_error("analysis failed: %r", exc)
            traceback.print_exc()
            self._send_json(
                {"error": "The analysis did not finish. Generate the card again."},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _send_file(self, path: Path, content_type: str | None = None) -> None:
        if not path.is_file():
            self._send_json({"error": "UI asset not found"}, HTTPStatus.NOT_FOUND)
            return
        payload = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header(
            "Content-Type",
            content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        )
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'",
        )
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(
        self, value: dict[str, Any], status: HTTPStatus = HTTPStatus.OK
    ) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[web] {self.address_string()} - {format % args}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    server = ThreadingHTTPServer((args.host, args.port), AgentHandler)
    print(f"AI Photographer Agent: http://{args.host}:{args.port}")
    print("The VLM is loaded on the first analysis request and then reused.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
