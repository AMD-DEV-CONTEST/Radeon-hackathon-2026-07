from __future__ import annotations

import json
import statistics
import tempfile
import time
from dataclasses import dataclass, replace
from pathlib import Path

from PIL import Image, ImageDraw

from .audience_pulse import LexicalAudiencePulse
from .contracts import (
    AuditFinding,
    CampaignRequest,
    CampaignState,
    Claim,
    Severity,
    Stage,
)
from .runtime import build_supervisor
from .workflow import Supervisor


@dataclass(frozen=True)
class EvalResult:
    case_id: str
    failure_mode: str
    expected_stage: str
    actual_stage: str
    passed: bool
    latency_ms: float


def _fixture(path: Path) -> None:
    image = Image.new("RGBA", (96, 128), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((12, 8, 84, 118), radius=16, fill=(235, 241, 255, 255))
    draw.rectangle((28, 28, 68, 88), fill=(28, 92, 170, 255))
    draw.ellipse((36, 96, 60, 112), fill=(248, 178, 70, 255))
    image.save(path, format="PNG")


def run_control_plane_eval(
    *,
    cases_per_mode: int = 20,
    output_path: str | Path | None = None,
) -> dict:
    """Runs five named synthetic failure modes without claiming model quality."""

    results: list[EvalResult] = []
    with tempfile.TemporaryDirectory(prefix="prooflaunch-eval-") as temp:
        root = Path(temp)
        product = root / "product.png"
        _fixture(product)
        baseline = CampaignRequest(
            product_name="Aster Arc",
            product_image=str(product),
            specification_text="Battery life up to 18 hours under the documented test.",
            market="Japan",
            platform="TikTok",
            goal="launch",
            target_emotion="joy",
        )
        for mode in (
            "happy_path",
            "missing_evidence",
            "missing_product",
            "unapproved_claim_injection",
            "persistent_audit_failure",
        ):
            for index in range(cases_per_mode):
                request = baseline
                supervisor = build_supervisor(
                    audience=LexicalAudiencePulse(),
                    seed=202607 + index,
                    canvas_overrides={"TikTok": (360, 640)},
                )
                expected = Stage.DELIVER
                if mode == "missing_evidence":
                    request = replace(baseline, specification_text="")
                    expected = Stage.BLOCKED
                elif mode == "missing_product":
                    request = replace(
                        baseline, product_image=str(root / "does-not-exist.png")
                    )
                    expected = Stage.BLOCKED
                elif mode == "unapproved_claim_injection":
                    base = supervisor.adapters

                    class PoisonedEvidence:
                        def extract(self, ignored: CampaignRequest) -> list[Claim]:
                            return [
                                Claim(
                                    id="CLM-001",
                                    text="Unsupported 10x claim.",
                                    source_ref="attacker",
                                    source_span="",
                                    approved=False,
                                    confidence=0.0,
                                )
                            ]

                    supervisor = Supervisor(replace(base, evidence=PoisonedEvidence()))
                    expected = Stage.BLOCKED
                elif mode == "persistent_audit_failure":
                    base = supervisor.adapters

                    class AlwaysFail:
                        def audit(
                            self, state: CampaignState
                        ) -> list[AuditFinding]:
                            return [
                                AuditFinding(
                                    id="AUD-INJECTED",
                                    category="fault_injection",
                                    severity=Severity.CRITICAL,
                                    message="Injected persistent audit failure.",
                                    asset_id=state.assets[0].id,
                                    repair_action="bounded_retry",
                                )
                            ]

                    supervisor = Supervisor(replace(base, auditor=AlwaysFail()))
                    expected = Stage.BLOCKED
                run_dir = root / f"{mode}-{index:03d}"
                started = time.perf_counter()
                state = supervisor.run(
                    request,
                    str(run_dir),
                    run_id=f"eval-{mode}-{index:03d}",
                )
                latency_ms = (time.perf_counter() - started) * 1000
                results.append(
                    EvalResult(
                        case_id=f"{mode}-{index:03d}",
                        failure_mode=mode,
                        expected_stage=expected.value,
                        actual_stage=state.stage.value,
                        passed=state.stage == expected,
                        latency_ms=round(latency_ms, 3),
                    )
                )
    latencies = sorted(result.latency_ms for result in results)
    p95_index = max(0, min(len(latencies) - 1, int(len(latencies) * 0.95) - 1))
    payload = {
        "schema": "ProofLaunchDeterministicEvalV1",
        "scope": "Local CPU orchestration and deterministic rendering only",
        "case_count": len(results),
        "named_failure_modes": sorted({result.failure_mode for result in results}),
        "passed": sum(result.passed for result in results),
        "pass_rate": (
            sum(result.passed for result in results) / len(results) if results else 0
        ),
        "latency_ms": {
            "median": round(statistics.median(latencies), 3) if latencies else 0,
            "p95": round(latencies[p95_index], 3) if latencies else 0,
            "max": round(max(latencies), 3) if latencies else 0,
        },
        "truth_boundary": (
            "This eval does not measure generative-image quality, ROCm performance, "
            "human preference, persuasion, or competitor superiority."
        ),
        "results": [result.__dict__ for result in results],
    }
    if output_path is not None:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return payload
