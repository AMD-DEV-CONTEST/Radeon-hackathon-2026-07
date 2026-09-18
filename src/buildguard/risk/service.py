"""Risk policy application and tool registration."""

from __future__ import annotations

import math

from buildguard.config import RiskPolicyConfig
from buildguard.risk.policies import risk_level
from buildguard.risk.scorer import RiskComponents, RiskScorer
from buildguard.schemas.rag import RetrievedEvidence
from buildguard.schemas.vision import Detection, InspectionResult, RiskAssessment
from buildguard.tools.base import ToolDefinition
from buildguard.tools.registry import ToolRegistry
from buildguard.vision.schemas import RiskAssessmentInput, RiskAssessmentOutput


class RiskAssessmentService:
    def __init__(self, config: RiskPolicyConfig) -> None:
        self.config = config
        self.scorer = RiskScorer()

    def _location_score(self, detection: Detection, image_height: float) -> float:
        configured_zone = detection.attributes.get("zone_risk")
        zone_score = (
            min(max(float(configured_zone), 0.0), 1.0)
            if isinstance(configured_zone, (int, float))
            else 0.0
        )
        configured_height = detection.attributes.get("image_height", image_height)
        height = (
            float(configured_height)
            if isinstance(configured_height, (int, float))
            else image_height
        )
        if height <= 0:
            return max(self.config.location_middle, zone_score)
        center = (detection.bounding_box.y1 + detection.bounding_box.y2) / 2 / height
        if center < 1 / 3:
            return max(self.config.location_top, zone_score)
        if center < 2 / 3:
            return max(self.config.location_middle, zone_score)
        return max(self.config.location_bottom, zone_score)

    def _evidence_score(self, evidence: list[RetrievedEvidence]) -> float:
        return (
            max(item.score for item in evidence)
            if evidence
            else self.config.default_evidence_strength
        )

    def _duration_score(self, detection: Detection) -> float:
        value = detection.attributes.get("duration_seconds", 0.0)
        seconds = float(value) if isinstance(value, (int, float)) else 0.0
        return min(max(seconds, 0.0) / self.config.duration_reference_seconds, 1.0)

    def _frequency_score(self, detection: Detection) -> float:
        value = detection.attributes.get("repeat_count", 0)
        count = float(value) if isinstance(value, (int, float)) else 0.0
        if count <= 0:
            return 0.0
        return min(
            math.log1p(count) / math.log1p(self.config.frequency_reference_count),
            1.0,
        )

    def assess(
        self,
        inspection: InspectionResult,
        evidence: list[RetrievedEvidence],
    ) -> RiskAssessmentOutput:
        image_height = max(
            (detection.bounding_box.y2 for detection in inspection.detections),
            default=1.0,
        )
        evidence_score = self._evidence_score(evidence)
        candidates: list[tuple[float, Detection, RiskComponents]] = []
        for detection in inspection.detections:
            components = RiskComponents(
                severity=self.config.base_severity.get(
                    detection.label, self.config.default_severity
                ),
                confidence=detection.confidence,
                location=self._location_score(detection, image_height),
                evidence=evidence_score,
                duration=self._duration_score(detection),
                frequency=self._frequency_score(detection),
            )
            candidates.append((self.scorer.score(components), detection, components))
        if not candidates:
            components = RiskComponents(
                severity=0,
                confidence=0,
                location=0,
                evidence=evidence_score,
                duration=0,
                frequency=0,
            )
            score = self.scorer.score(components)
            governing = None
            summary = "未检测到视觉缺陷，无法进行定量风险评分。"
            actions: list[str] = []
        else:
            score, governing, components = max(
                candidates,
                key=lambda item: (item[0], item[1].label),
            )
            summary = (
                f"风险评分由检测项「{governing.label}」主导，"
                "评分结果由确定性规则计算，不受 LLM 影响。"
            )
            actions = [
                f"复核「{governing.label}」相关现场证据",
                "按现场安全管理程序落实管控措施",
            ]
        assessment = RiskAssessment(
            severity=risk_level(score),
            score=score,
            summary=summary,
            recommended_actions=actions,
        )
        return RiskAssessmentOutput(
            assessment=assessment,
            component_scores={
                "severity": components.severity,
                "confidence": components.confidence,
                "location": components.location,
                "evidence": components.evidence,
                "duration": components.duration,
                "frequency": components.frequency,
            },
            governing_detection=governing,
        )


def register_risk_tool(
    registry: ToolRegistry,
    service: RiskAssessmentService,
    *,
    timeout_seconds: float = 10,
) -> None:
    def assess(raw: object) -> RiskAssessmentOutput:
        request = RiskAssessmentInput.model_validate(raw)
        if request.inspection_result is not None:
            return service.assess(
                request.inspection_result,
                request.retrieved_evidence,
            )
        results = [
            service.assess(inspection, request.retrieved_evidence)
            for inspection in request.inspection_results
        ]
        return RiskAssessmentOutput(
            assessment=results[0].assessment,
            assessments=[item.assessment for item in results],
            component_scores=results[0].component_scores,
            component_scores_batch=[item.component_scores for item in results],
            governing_detection=results[0].governing_detection,
            governing_detections=[item.governing_detection for item in results],
        )

    registry.register(
        ToolDefinition(
            name="assess_risk",
            description=(
                "Compute deterministic construction risk for one or more verified "
                "inspection results and optional retrieved evidence."
            ),
            input_schema=RiskAssessmentInput,
            output_schema=RiskAssessmentOutput,
            permission="auto",
            read_only=True,
            timeout_seconds=timeout_seconds,
            category="risk",
        ),
        assess,
    )
