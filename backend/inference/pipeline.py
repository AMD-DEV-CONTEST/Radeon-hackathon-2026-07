"""End-to-end inference pipeline orchestration."""
import base64
import os
import threading
import uuid
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Optional

import numpy as np
import torch
from PIL import Image

from models.classifier import ChestXRayClassifier, FindingPrediction
from models.localizer import LocalizationResult, XRayLocalizer, combine_masks
from models.radiology_llm import RadiologyLLM
from models.report_generator import ReportResult


def get_pipeline():
    """Dependency-injection helper used by FastAPI routes."""
    import sys
    main_module = sys.modules.get("main") or sys.modules.get("backend.main")
    if main_module is None:
        raise RuntimeError("Main module not loaded")
    pipeline = getattr(main_module, "PIPELINE", None)
    if pipeline is None:
        raise RuntimeError("Pipeline not initialized")
    return pipeline


@dataclass
class AnalysisResult:
    image_id: str
    findings: list[FindingPrediction]
    confidence_scores: dict[str, float]
    localization_maps: list[LocalizationResult]
    report: str
    report_sections: dict[str, str]
    report_source: str
    mask: Optional[np.ndarray] = None
    chat_seed: list[dict[str, Any]] = field(default_factory=list)


class AnalysisPipeline:
    def __init__(self, device: str = "cpu"):
        self.device = device
        self.rocm_available = self._detect_rocm()
        self.classifier = ChestXRayClassifier(device=device)
        self.localizer = XRayLocalizer(device=device)
        # Unified model class for report generation and report-aware chat.
        self.radiology_llm = RadiologyLLM(device=device)
        # Load a dedicated chat backend in the background so the server starts
        # quickly. Report generation is available immediately via the fallback.
        threading.Thread(target=self.radiology_llm.load_chat_engine, daemon=True).start()

    def _wait_for_chat(self, timeout: Optional[float] = None) -> bool:
        return self.radiology_llm.wait_for_chat(timeout=timeout)

    def _detect_rocm(self) -> bool:
        return (
            torch.version.hip is not None
            or "rocm" in torch.__version__.lower()
            or os.environ.get("FORCE_ROCM", "0") == "1"
        )

    def analyze(self, image: Image.Image, evidence_type: str = "attention") -> AnalysisResult:
        findings = self.classifier.predict(image)
        localization_maps = self.localizer.localize(
            image, self.classifier, findings, evidence_type=evidence_type
        )
        combined = combine_masks(image.size, localization_maps)
        structured = self._structured_findings(findings)
        # If an LLM backend was configured, let it become reachable before
        # generating the report rather than returning a template during startup.
        # With no configured backend the documented template fallback remains
        # immediate, rather than waiting for a model that cannot become ready.
        if os.environ.get("CHAT_OPENAI_BASE_URL") or os.environ.get("CHAT_MODEL"):
            self.radiology_llm.wait_for_chat_available(timeout=300.0)
        report_result = self.radiology_llm.generate_report(
            image=image,
            findings=findings,
            structured_findings=structured,
            image_info={"size": image.size},
        )
        return AnalysisResult(
            image_id=str(uuid.uuid4()),
            findings=findings,
            confidence_scores={f.label: f.confidence for f in findings},
            localization_maps=localization_maps,
            report=report_result.report,
            report_sections=report_result.sections,
            report_source=report_result.source,
            mask=combined,
            chat_seed=report_result.chat_seed,   # NEW
        )

    def generate_report(self, structured_findings: dict[str, Any]) -> ReportResult:
        """Generate a report from externally supplied structured findings."""
        # Convert structured findings to internal FindingPrediction objects for chat/templates.
        findings = [
            FindingPrediction(
                label=self._title_name(f["name"]),
                confidence=float(f["confidence"]),
                region=None,
            )
            for f in structured_findings.get("findings", [])
        ]
        return self.radiology_llm.generate_report(
            findings=findings,
            image=None,
            structured_findings=structured_findings,
            image_info=None,
        )

    def chat(
        self,
        report: str,
        findings: list,
        question: str,
        max_tokens: Optional[int] = None,
        history: Optional[list[dict[str, Any]]] = None,   # NEW
    ) -> str:
        self.radiology_llm.wait_for_chat_available(timeout=300.0)
        return self.radiology_llm.chat(
            report, findings, question, max_new_tokens=max_tokens, history=history
        ).text


    @staticmethod
    def _structured_findings(findings: list[FindingPrediction]) -> dict[str, Any]:
        return {
            "modality": "Chest X-ray",
            "findings": [
                {"name": _normalize_label(f.label), "confidence": round(f.confidence, 4)}
                for f in findings
            ],
        }

    @staticmethod
    def _title_name(name: str) -> str:
        return name.replace("_", " ").title()


def _normalize_label(label: str) -> str:
    return label.lower().replace(" ", "_")


def encode_image_as_base64(array: np.ndarray) -> str:
    """Encode a numpy image array as a base64 PNG string."""
    img = Image.fromarray(array)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")
