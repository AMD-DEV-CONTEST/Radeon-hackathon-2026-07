#!/usr/bin/env python3
"""Exercise the real loopback API, worker and durable store across the GTM matrix.

This is deliberately a local synthetic reliability receipt.  It does not close
production-traffic, human-preference, Radeon, effect, or revenue proof gates.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import io
import json
import statistics
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from prooflaunch_remix.audience_pulse import LexicalAudiencePulse
from prooflaunch_remix.production_trace_ledger import ProductionTraceLedger
from prooflaunch_remix.runtime import build_supervisor
from prooflaunch_remix.v10_submission_production_api import make_production_server
from prooflaunch_remix.v10_submission_runtime import (
    AgencyRunWorker,
    ProductionAgencyService,
)
from prooflaunch_remix.v10_submission_store import SubmissionStore


SCHEMA = "ProofLaunchLocalAgenticApiSoakV1"
TENANT_ID = "org-local-soak"
TENANT_TOKEN = "local-soak-tenant-token-20260802-00000001"
APPROVAL_TOKEN = "local-soak-approval-token-20260802-00000001"
MEMORY_SECRET = b"local-soak-memory-secret-20260802-00000001"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _pretty_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _content_sha256(value: dict[str, Any]) -> str:
    unsigned = dict(value)
    unsigned.pop("content_sha256", None)
    return hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * fraction)))
    return round(ordered[index], 3)


def _png_bytes() -> bytes:
    stream = io.BytesIO()
    image = Image.new("RGBA", (96, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 6, 88, 120), radius=14, fill=(240, 244, 255, 255))
    draw.rectangle((26, 28, 70, 84), fill=(24, 86, 170, 255))
    image.save(stream, format="PNG")
    return stream.getvalue()


def _supervisor_factory(event_sink):
    return build_supervisor(
        audience=LexicalAudiencePulse(),
        seed=20260803,
        canvas_overrides={"TikTok": (360, 640), "LinkedIn": (360, 640)},
        event_sink=event_sink,
    )


class _Harness:
    def __init__(self, root: Path, web_root: Path, trace_root: Path) -> None:
        self.root = root
        self.web_root = web_root
        self.trace_root = trace_root
        self.store: SubmissionStore | None = None
        self.worker: AgencyRunWorker | None = None
        self.service: ProductionAgencyService | None = None
        self.trace: ProductionTraceLedger | None = None
        self.server = None
        self.thread: threading.Thread | None = None
        self.host = "127.0.0.1"
        self.port = 0

    def start(self, restart_index: int) -> None:
        self.store = SubmissionStore(self.root)
        self.worker = AgencyRunWorker(
            self.store,
            worker_id=f"local-api-soak-worker-{restart_index}",
            supervisor_factory=_supervisor_factory,
        )
        self.service = ProductionAgencyService(self.store, worker=self.worker)
        self.trace = ProductionTraceLedger(self.trace_root, retention_days=90)
        self.server = make_production_server(
            "127.0.0.1",
            0,
            service=self.service,
            web_root=self.web_root,
            approval_token=APPROVAL_TOKEN,
            approver_identity="local-soak-named-reviewer@example.test",
            tenant_tokens={TENANT_ID: TENANT_TOKEN},
            memory_capsule_secret=MEMORY_SECRET,
            trace_ledger=self.trace,
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self.thread.start()
        self.host, self.port = self.server.server_address

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise RuntimeError("local soak HTTP server did not stop")
        self.server = None
        self.thread = None

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes, float]:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=30)
        request_headers = {
            "Authorization": f"Bearer {TENANT_TOKEN}",
            **(headers or {}),
        }
        if body is not None:
            request_headers.setdefault("Content-Length", str(len(body)))
        started = time.perf_counter()
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            response_body = response.read()
            response_headers = {
                key.casefold(): value for key, value in response.getheaders()
            }
            elapsed_ms = (time.perf_counter() - started) * 1000
            return response.status, response_headers, response_body, elapsed_ms
        finally:
            connection.close()

    def json_request(
        self,
        method: str,
        path: str,
        payload: object,
        *,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], dict[str, Any], float]:
        body = _canonical_bytes(payload)
        status, response_headers, response_body, elapsed_ms = self.request(
            method,
            path,
            body=body,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        decoded = json.loads(response_body)
        if not isinstance(decoded, dict):
            raise RuntimeError("local soak API returned a non-object JSON response")
        return status, response_headers, decoded, elapsed_ms


def _payload(case: dict[str, Any], index: int, image_sha256: str) -> dict[str, Any]:
    high_risk = case["industry_risk"] == "high_regulation"
    business_model = str(case["business_model"])
    return {
        "request_id": f"soak-request-{index:04d}",
        "campaign_id": f"soak-campaign-{index:04d}",
        "campaign": {
            "product_name": f"Synthetic {case['input_archetype']} evidence product",
            "specification_text": (
                "Owner-attested synthetic product evidence. No external performance, "
                "revenue, preference, or causal effect has been observed."
            ),
            "market": "North America",
            "platform": "LinkedIn" if business_model == "b2b" else "TikTok",
            "goal": "Prepare a rights-clear, claim-safe GTM draft for human review.",
            "target_emotion": "joy",
        },
        "input_artifacts": {"product_image": image_sha256},
        "rights": {
            "confirmed": True,
            "basis": "Programmatically generated synthetic fixture owned by the test run.",
        },
        "strategy": {
            "project_id": f"project-soak-{index:04d}",
            "owner": "local-soak-owner@example.test",
            "industry": str(case["input_archetype"]),
            "business_model": business_model,
            "lifecycle": str(case["lifecycle"]),
            "budget": str(case["budget"]),
            "industry_risk": str(case["industry_risk"]),
            "audience_name": "synthetic decision-maker",
            "audience_problem": "needs evidence before approving a GTM experiment",
            "audience_outcome": "review a bounded, reversible campaign draft",
            "buying_context": "synthetic local reliability evaluation",
            "brand_purpose": "Make GTM decisions reviewable and evidence-bound.",
            "customer_promise": "A human-reviewed plan with no automatic activation.",
            "brand_voice": "specific, calm, evidence-first",
            "offer": "review the synthetic evidence pack",
            "landing_url": f"https://example.invalid/soak/{index:04d}",
            "schedule_timezone": "America/New_York",
            "claim_assurance": "owner_attested",
            "specialist_approved_by": (
                "local-soak-specialist@example.test" if high_risk else None
            ),
        },
        "maximum_actions": 12,
        "maximum_cost_usd": 0,
        "human_release_required": True,
        "data_class": "synthetic",
    }


def run(project_root: Path, output_path: Path) -> dict[str, Any]:
    matrix_path = project_root / "evidence/v10/gtm-industry-profile-matrix-v1.json"
    matrix_bytes = matrix_path.read_bytes()
    matrix = json.loads(matrix_bytes)
    cases = matrix["cases"]
    if len(cases) != 456 or matrix["case_count"] != 456:
        raise RuntimeError("the frozen GTM matrix must contain exactly 456 cases")

    png = _png_bytes()
    png_sha256 = hashlib.sha256(png).hexdigest()
    create_latencies: list[float] = []
    worker_latencies: list[float] = []
    get_latencies: list[float] = []
    trace_ids: set[str] = set()
    run_ids: list[str] = []
    restart_count = 0
    recovered_after_restart = False
    started = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="prooflaunch-local-api-soak-") as temporary:
        temporary_root = Path(temporary)
        store_root = temporary_root / "store"
        trace_root = temporary_root / "traces"
        harness = _Harness(store_root, project_root / "web", trace_root)
        harness.start(restart_index=0)
        try:
            upload_status, upload_headers, _, _ = harness.request(
                "PUT",
                f"/v1/artifacts/{png_sha256}",
                body=png,
                headers={"Content-Type": "image/png"},
            )
            if upload_status != 201:
                raise RuntimeError(f"fixture upload failed with HTTP {upload_status}")
            trace_ids.add(upload_headers["x-prooflaunch-trace-id"])

            midpoint = len(cases) // 2
            for index, case in enumerate(cases, start=1):
                body = _payload(case, index, png_sha256)
                status, headers, created, elapsed_ms = harness.json_request(
                    "POST",
                    "/v1/runs",
                    body,
                    headers={"Idempotency-Key": f"local-soak-{index:04d}"},
                )
                if status != 202 or created.get("status") != "queued":
                    raise RuntimeError(
                        f"case {case['case_id']} create failed: HTTP {status} {created}"
                    )
                create_latencies.append(elapsed_ms)
                trace_ids.add(headers["x-prooflaunch-trace-id"])
                run_id = str(created["run_id"])
                run_ids.append(run_id)

                worker_started = time.perf_counter()
                result = harness.worker.process_one() if harness.worker is not None else None
                worker_latencies.append((time.perf_counter() - worker_started) * 1000)
                if (
                    result is None
                    or not result.processed
                    or result.run_id != run_id
                    or result.status != "awaiting_release"
                ):
                    raise RuntimeError(f"case {case['case_id']} worker failed: {result}")

                get_status, get_headers, snapshot, get_elapsed_ms = harness.json_request(
                    "GET", f"/v1/runs/{run_id}", {}
                )
                if (
                    get_status != 200
                    or snapshot.get("status") != "awaiting_release"
                    or snapshot.get("external_release_executed") is not False
                ):
                    raise RuntimeError(
                        f"case {case['case_id']} snapshot failed: HTTP {get_status} {snapshot}"
                    )
                get_latencies.append(get_elapsed_ms)
                trace_ids.add(get_headers["x-prooflaunch-trace-id"])

                if index == midpoint:
                    recovery_run_id = run_ids[0]
                    harness.stop()
                    restart_count += 1
                    harness = _Harness(store_root, project_root / "web", trace_root)
                    harness.start(restart_index=restart_count)
                    recovery_status, recovery_headers, recovery, recovery_ms = (
                        harness.json_request("GET", f"/v1/runs/{recovery_run_id}", {})
                    )
                    recovered_after_restart = (
                        recovery_status == 200
                        and recovery.get("status") == "awaiting_release"
                    )
                    if not recovered_after_restart:
                        raise RuntimeError("durable run recovery failed after API restart")
                    get_latencies.append(recovery_ms)
                    trace_ids.add(recovery_headers["x-prooflaunch-trace-id"])

            trace_status = harness.trace.status(tenant_id=TENANT_ID)
        finally:
            harness.stop()

    elapsed_seconds = time.perf_counter() - started
    expected_trace_count = 1 + len(cases) * 2 + restart_count
    if trace_status["request_trace_count"] != expected_trace_count:
        raise RuntimeError(
            "request trace count drifted: "
            f"{trace_status['request_trace_count']} != {expected_trace_count}"
        )
    if len(trace_ids) != expected_trace_count:
        raise RuntimeError("HTTP trace identities were not unique")

    dimensions = {
        key: sorted({str(case[key]) for case in cases})
        for key in ("input_archetype", "business_model", "lifecycle", "budget", "industry_risk")
    }
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_matrix": {
            "path": str(matrix_path.relative_to(project_root)),
            "file_sha256": hashlib.sha256(matrix_bytes).hexdigest(),
            "declared_content_sha256": matrix.get("content_sha256"),
            "case_count": len(cases),
            "dimensions": dimensions,
        },
        "execution": {
            "transport": "real_loopback_http",
            "graph": "ProductionAgencyService.create_run",
            "loop": "AgencyRunWorker.process_one",
            "harness": "production API auth + idempotency + guardrails + trace ledger",
            "artifact_upload_count": 1,
            "accepted_run_count": len(run_ids),
            "awaiting_human_release_count": len(run_ids),
            "status_get_count": len(cases) + restart_count,
            "restart_count": restart_count,
            "durable_run_recovered_after_restart": recovered_after_restart,
            "unique_run_id_count": len(set(run_ids)),
            "unique_http_trace_id_count": len(trace_ids),
            "duration_seconds": round(elapsed_seconds, 3),
            "external_model_api_calls": 0,
            "external_gpu_sessions": 0,
            "external_publish_or_send_actions": 0,
            "spend_usd": 0.0,
        },
        "latency_ms": {
            "create": {
                "mean": round(statistics.fmean(create_latencies), 3),
                "p50": _percentile(create_latencies, 0.50),
                "p95": _percentile(create_latencies, 0.95),
                "max": round(max(create_latencies), 3),
            },
            "worker_prepare": {
                "mean": round(statistics.fmean(worker_latencies), 3),
                "p50": _percentile(worker_latencies, 0.50),
                "p95": _percentile(worker_latencies, 0.95),
                "max": round(max(worker_latencies), 3),
            },
            "status_get": {
                "mean": round(statistics.fmean(get_latencies), 3),
                "p50": _percentile(get_latencies, 0.50),
                "p95": _percentile(get_latencies, 0.95),
                "max": round(max(get_latencies), 3),
            },
        },
        "trace_ledger": trace_status,
        "acceptance": {
            "all_456_cases_accepted": len(run_ids) == 456,
            "all_456_cases_prepared_to_human_gate": len(run_ids) == 456,
            "zero_worker_failures": True,
            "restart_recovery_passed": recovered_after_restart,
            "trace_hash_chain_valid": trace_status["hash_chain_valid"] is True,
            "raw_request_or_response_content_retained": False,
            "automatic_external_activation_enabled": False,
        },
        "truth_boundary": {
            "local_synthetic_reliability_observed": True,
            "production_deployment_observed": False,
            "named_human_preference_observed": False,
            "radeon_local_key_inference_observed": False,
            "real_effect_observed": False,
            "causal_revenue_observed": False,
            "four_a_or_top_one_claim_eligible": False,
        },
    }
    receipt["content_sha256"] = _content_sha256(receipt)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(_pretty_bytes(receipt))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evidence/v10/local-agentic-api-soak-v1.json"),
    )
    arguments = parser.parse_args()
    project_root = arguments.project_root.resolve(strict=True)
    output = arguments.output
    if not output.is_absolute():
        output = project_root / output
    receipt = run(project_root, output)
    print(
        json.dumps(
            {
                "output": str(output),
                "case_count": receipt["execution"]["accepted_run_count"],
                "duration_seconds": receipt["execution"]["duration_seconds"],
                "trace_count": receipt["trace_ledger"]["request_trace_count"],
                "content_sha256": receipt["content_sha256"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
