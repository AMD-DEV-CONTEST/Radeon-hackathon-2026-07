from __future__ import annotations

import io
import json
import math
import re
import threading
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from .v10_contracts import EvidenceClass, V10ContractError, stable_digest


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _iso8601(value: str, field_name: str) -> None:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise V10ContractError(f"{field_name} must be ISO-8601") from error


def _jsonable(value: object) -> object:
    if isinstance(value, EvidenceClass):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, frozenset, set)):
        return [_jsonable(item) for item in value]
    return value


@dataclass(frozen=True)
class AgencyLaunchRequest:
    request_id: str
    campaign_id: str
    objective: str
    required_capabilities: tuple[str, ...]
    input_artifacts: Mapping[str, str]
    maximum_actions: int
    maximum_cost_usd: float
    created_at: str
    human_release_required: bool = True
    data_class: str = "internal"
    schema: str = "ProofLaunchAgencyLaunchRequestV1"

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.request_id, self.campaign_id, self.objective)
        ):
            raise V10ContractError("launch request identity and objective are required")
        if not self.required_capabilities or any(
            not value.strip() for value in self.required_capabilities
        ):
            raise V10ContractError("launch request requires named capabilities")
        if len(set(self.required_capabilities)) != len(self.required_capabilities):
            raise V10ContractError("launch request capabilities must be unique")
        if not self.input_artifacts or any(
            not artifact_id.strip() or not _SHA256.fullmatch(digest)
            for artifact_id, digest in self.input_artifacts.items()
        ):
            raise V10ContractError("launch request artifacts require IDs and SHA-256")
        if self.maximum_actions < 1 or self.maximum_actions > 100:
            raise V10ContractError("launch request action budget must be in [1, 100]")
        if not math.isfinite(self.maximum_cost_usd) or self.maximum_cost_usd < 0:
            raise V10ContractError("launch request cost cap must be finite and non-negative")
        if not self.human_release_required:
            raise V10ContractError("external launch requests require human release")
        if self.data_class not in {"public", "internal", "confidential", "synthetic"}:
            raise V10ContractError("launch request data class is unknown")
        _iso8601(self.created_at, "created_at")

    @property
    def digest(self) -> str:
        return stable_digest(_jsonable(asdict(self)))


@dataclass(frozen=True)
class ModelCard:
    model_id: str
    revision: str
    role: str
    capabilities: tuple[str, ...]
    limitations: tuple[str, ...]
    training_data_manifest_sha256: str | None
    evaluation_record_ids: tuple[str, ...]
    radeon_execution_evidence: str | None
    promotion_status: str
    created_at: str
    schema: str = "ProofLaunchModelCardV1"

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.model_id, self.revision, self.role)):
            raise V10ContractError("model card identity, revision and role are required")
        if not self.capabilities or not self.limitations:
            raise V10ContractError("model card capabilities and limitations are required")
        if self.training_data_manifest_sha256 is not None and not _SHA256.fullmatch(
            self.training_data_manifest_sha256
        ):
            raise V10ContractError("model card training manifest must be SHA-256")
        if self.promotion_status not in {"planned", "hold", "rejected", "promoted"}:
            raise V10ContractError("model card promotion status is unknown")
        if self.promotion_status == "promoted" and (
            not self.evaluation_record_ids or not self.radeon_execution_evidence
        ):
            raise V10ContractError("promoted model cards require eval and Radeon evidence")
        _iso8601(self.created_at, "created_at")

    @property
    def digest(self) -> str:
        return stable_digest(_jsonable(asdict(self)))


@dataclass(frozen=True)
class AgencyEvalRecord:
    eval_id: str
    model_id: str
    model_revision: str
    benchmark_id: str
    benchmark_sha256: str
    metrics: Mapping[str, float]
    raw_counts: Mapping[str, int]
    evidence_class: EvidenceClass
    evidence_locator: str
    observed_at: str
    blinded: bool
    schema: str = "ProofLaunchAgencyEvalRecordV1"

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.eval_id,
                self.model_id,
                self.model_revision,
                self.benchmark_id,
                self.evidence_locator,
            )
        ):
            raise V10ContractError("agency eval identity and evidence are required")
        if not _SHA256.fullmatch(self.benchmark_sha256):
            raise V10ContractError("agency eval benchmark must be SHA-256 bound")
        if not self.metrics or any(
            not name.strip() or not math.isfinite(value)
            for name, value in self.metrics.items()
        ):
            raise V10ContractError("agency eval metrics must be finite and named")
        if not self.raw_counts or any(
            not name.strip() or value < 0 for name, value in self.raw_counts.items()
        ):
            raise V10ContractError("agency eval requires non-negative raw counts")
        _iso8601(self.observed_at, "observed_at")

    @property
    def digest(self) -> str:
        return stable_digest(_jsonable(asdict(self)))


@dataclass
class RunRecord:
    run_id: str
    request: AgencyLaunchRequest
    status: str = "awaiting_approval"
    approvals: list[dict[str, object]] = field(default_factory=list)
    events: list[dict[str, object]] = field(default_factory=list)

    def snapshot(self) -> dict[str, object]:
        return {
            "schema": "ProofLaunchRunStatusV1",
            "run_id": self.run_id,
            "request_digest": self.request.digest,
            "campaign_id": self.request.campaign_id,
            "status": self.status,
            "human_release_required": self.request.human_release_required,
            "approval_count": len(self.approvals),
            "event_count": len(self.events),
        }


class AgencyRunStore:
    """Thread-safe, idempotent store for the single-port submission API.

    This control plane never executes external side effects. Approval changes
    the run to bundle-ready only; publication and spend remain outside the API.
    """

    def __init__(
        self,
        *,
        model_cards: Sequence[ModelCard] = (),
        eval_records: Sequence[AgencyEvalRecord] = (),
    ) -> None:
        self._lock = threading.RLock()
        self._runs: dict[str, RunRecord] = {}
        self.model_cards = tuple(model_cards)
        self.eval_records = tuple(eval_records)

    def create(self, request: AgencyLaunchRequest) -> RunRecord:
        run_id = f"run-{request.digest[:24]}"
        with self._lock:
            existing = self._runs.get(run_id)
            if existing is not None:
                return existing
            record = RunRecord(run_id, request)
            record.events.append(
                {
                    "sequence": 1,
                    "type": "run_created",
                    "status": record.status,
                    "request_digest": request.digest,
                }
            )
            self._runs[run_id] = record
            return record

    def get(self, run_id: str) -> RunRecord:
        with self._lock:
            try:
                return self._runs[run_id]
            except KeyError as error:
                raise KeyError("unknown run") from error

    def approve(
        self,
        run_id: str,
        *,
        decision: str,
        approver: str,
        decided_at: str,
        reason: str,
    ) -> RunRecord:
        if decision not in {"approve", "reject"}:
            raise V10ContractError("approval decision must be approve or reject")
        if not approver.strip() or not reason.strip():
            raise V10ContractError("approval requires approver and reason")
        _iso8601(decided_at, "decided_at")
        with self._lock:
            record = self.get(run_id)
            if record.status not in {"awaiting_approval", "rejected"}:
                raise V10ContractError("run is not at an approval boundary")
            approval = {
                "decision": decision,
                "approver": approver,
                "decided_at": decided_at,
                "reason": reason,
            }
            record.approvals.append(approval)
            record.status = "bundle_ready" if decision == "approve" else "rejected"
            record.events.append(
                {
                    "sequence": len(record.events) + 1,
                    "type": "human_approval",
                    "status": record.status,
                    "approval_sha256": stable_digest(approval),
                }
            )
            return record

    def events(self, run_id: str) -> tuple[dict[str, object], ...]:
        return tuple(self.get(run_id).events)

    def bundle(self, run_id: str) -> bytes:
        record = self.get(run_id)
        if record.status != "bundle_ready":
            raise V10ContractError("bundle download requires human approval")
        request_payload = _jsonable(asdict(record.request))
        status_payload = record.snapshot()
        event_payload = "".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
            for item in record.events
        )
        ledger = {
            "schema": "ProofLaunchEvidenceLedgerV1",
            "run_id": run_id,
            "request_sha256": record.request.digest,
            "event_chain_sha256": stable_digest(record.events),
            "approval_sha256": stable_digest(record.approvals),
            "external_release_executed": False,
        }
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in (
                ("request.json", json.dumps(request_payload, ensure_ascii=False, indent=2)),
                ("run.json", json.dumps(status_payload, ensure_ascii=False, indent=2)),
                ("events.jsonl", event_payload),
                ("evidence-ledger.json", json.dumps(ledger, ensure_ascii=False, indent=2)),
            ):
                info = zipfile.ZipInfo(name)
                info.date_time = (1980, 1, 1, 0, 0, 0)
                info.external_attr = 0o644 << 16
                archive.writestr(info, payload.encode("utf-8"))
        return output.getvalue()

    def leaderboard(self) -> list[dict[str, object]]:
        rows = []
        for record in self.eval_records:
            rows.append(
                {
                    "eval_id": record.eval_id,
                    "model_id": record.model_id,
                    "model_revision": record.model_revision,
                    "benchmark_id": record.benchmark_id,
                    "metrics": dict(record.metrics),
                    "evidence_class": record.evidence_class.value,
                    "blinded": record.blinded,
                    "record_digest": record.digest,
                }
            )
        rows.sort(
            key=lambda row: (
                -float(row["metrics"].get("overall", float("-inf"))),  # type: ignore[union-attr]
                str(row["model_id"]),
            )
        )
        return rows


def parse_launch_request(payload: Mapping[str, object]) -> AgencyLaunchRequest:
    try:
        for field_name in ("request_id", "campaign_id", "objective", "created_at"):
            if not isinstance(payload[field_name], str):
                raise TypeError(f"{field_name} must be a string")
        artifacts = payload["input_artifacts"]
        if not isinstance(artifacts, Mapping):
            raise TypeError("input_artifacts must be an object")
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in artifacts.items()):
            raise TypeError("input_artifacts keys and values must be strings")
        capabilities = payload["required_capabilities"]
        if not isinstance(capabilities, list) or any(
            not isinstance(value, str) for value in capabilities
        ):
            raise TypeError("required_capabilities must be a string array")
        maximum_actions = payload["maximum_actions"]
        maximum_cost_usd = payload["maximum_cost_usd"]
        human_release_required = payload.get("human_release_required", True)
        data_class = payload.get("data_class", "internal")
        if isinstance(maximum_actions, bool) or not isinstance(maximum_actions, int):
            raise TypeError("maximum_actions must be an integer")
        if isinstance(maximum_cost_usd, bool) or not isinstance(maximum_cost_usd, (int, float)):
            raise TypeError("maximum_cost_usd must be numeric")
        if not isinstance(human_release_required, bool):
            raise TypeError("human_release_required must be boolean")
        if not isinstance(data_class, str):
            raise TypeError("data_class must be a string")
        return AgencyLaunchRequest(
            request_id=payload["request_id"],
            campaign_id=payload["campaign_id"],
            objective=payload["objective"],
            required_capabilities=tuple(capabilities),
            input_artifacts=dict(artifacts),
            maximum_actions=maximum_actions,
            maximum_cost_usd=float(maximum_cost_usd),
            created_at=payload["created_at"],
            human_release_required=human_release_required,
            data_class=data_class,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise V10ContractError("invalid AgencyLaunchRequest payload") from error


def handler_factory(store: AgencyRunStore, web_root: Path) -> type[BaseHTTPRequestHandler]:
    root = web_root.resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = "ProofLaunchAPI/1.0"

        def log_message(self, format: str, *args: object) -> None:
            return

        def _json(self, status: int, payload: object) -> None:
            body = json.dumps(_jsonable(payload), ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> Mapping[str, object]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as error:
                raise V10ContractError("request body length is invalid") from error
            if length <= 0 or length > 1_000_000:
                raise V10ContractError("request body length is invalid")
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(value, Mapping):
                raise V10ContractError("request JSON must be an object")
            return value

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                if path == "/v1/runs":
                    record = store.create(parse_launch_request(self._body()))
                    self._json(HTTPStatus.CREATED, record.snapshot())
                    return
                match = re.fullmatch(r"/v1/runs/(run-[0-9a-f]{24})/approvals", path)
                if match:
                    body = self._body()
                    record = store.approve(
                        match.group(1),
                        decision=str(body.get("decision", "")),
                        approver=str(body.get("approver", "")),
                        decided_at=str(body.get("decided_at", "")),
                        reason=str(body.get("reason", "")),
                    )
                    self._json(HTTPStatus.OK, record.snapshot())
                    return
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            except KeyError:
                self._json(HTTPStatus.NOT_FOUND, {"error": "unknown_run"})
            except (V10ContractError, json.JSONDecodeError, UnicodeDecodeError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            try:
                if path == "/v1/health":
                    self._json(
                        HTTPStatus.OK,
                        {
                            "schema": "ProofLaunchSubmissionHealthV1",
                            "api_connected": True,
                            "execution_mode": "mechanical_fixture_only",
                            "external_release_enabled": False,
                            "radeon_connected": False,
                            "radeon_metrics_observed": False,
                            "model_inference_observed": False,
                        },
                    )
                    return
                if path == "/v1/model-cards":
                    self._json(
                        HTTPStatus.OK,
                        {"model_cards": [_jsonable(asdict(card)) for card in store.model_cards]},
                    )
                    return
                if path == "/v1/evals/leaderboard":
                    self._json(HTTPStatus.OK, {"leaderboard": store.leaderboard()})
                    return
                match = re.fullmatch(r"/v1/runs/(run-[0-9a-f]{24})", path)
                if match:
                    self._json(HTTPStatus.OK, store.get(match.group(1)).snapshot())
                    return
                match = re.fullmatch(r"/v1/runs/(run-[0-9a-f]{24})/events", path)
                if match:
                    body = "".join(
                        f"id: {event['sequence']}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False, sort_keys=True)}\n\n"
                        for event in store.events(match.group(1))
                    ).encode("utf-8")
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                match = re.fullmatch(r"/v1/runs/(run-[0-9a-f]{24})/bundle", path)
                if match:
                    body = store.bundle(match.group(1))
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Disposition", f'attachment; filename="{match.group(1)}.zip"')
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                static_files = {
                    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
                    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                }
                if path in static_files:
                    filename, content_type = static_files[path]
                    candidate = (root / filename).resolve()
                    if candidate.parent != root or not candidate.is_file():
                        self._json(HTTPStatus.NOT_FOUND, {"error": "web_asset_missing"})
                        return
                    body = candidate.read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                spa_route = path in {"/", "/index.html", "/datasets", "/models", "/spec", "/rocm", "/PDF"} or path.startswith(
                    ("/workspace/", "/control/", "/datasets/", "/models/")
                )
                if spa_route:
                    candidate = (root / "index.html").resolve()
                    if candidate.parent != root or not candidate.is_file():
                        self._json(HTTPStatus.NOT_FOUND, {"error": "web_ui_missing"})
                        return
                    body = candidate.read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            except KeyError:
                self._json(HTTPStatus.NOT_FOUND, {"error": "unknown_run"})
            except V10ContractError as error:
                self._json(HTTPStatus.CONFLICT, {"error": str(error)})

    return Handler


def make_server(
    host: str,
    port: int,
    *,
    store: AgencyRunStore,
    web_root: Path,
) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "localhost"}:
        raise V10ContractError("submission API binds loopback only by default")
    if not 0 <= port <= 65535:
        raise V10ContractError("submission API port is invalid")
    return ThreadingHTTPServer((host, port), handler_factory(store, web_root))
