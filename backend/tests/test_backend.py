"""Backend unit tests runnable with pytest."""
import os
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import torch
from PIL import Image

from inference.pipeline import AnalysisPipeline
from models.classifier import RADDINOHead, RADDINOClassifierBackend
from models.vision_encoder import RADDINOVisionEncoder

try:
    import pytest
except ImportError:
    pytest = None  # type: ignore


def _create_temporary_head() -> str:
    encoder = RADDINOVisionEncoder(device="cpu")
    head = RADDINOHead(encoder.hidden_size, 8)
    path = os.path.join(tempfile.gettempdir(), f"test_classifier_head_{uuid.uuid4().hex}.pt")
    torch.save({"head": head.state_dict()}, path)
    return path


if pytest is not None:
    @pytest.fixture
    def pipeline():
        # Default backend is TorchXRayVision (no CLASSIFIER_HEAD).
        # Also run a quick RAD-DINO backend test if a temporary head exists.
        yield AnalysisPipeline(device="cpu")


def _make_pipeline() -> AnalysisPipeline:
    return AnalysisPipeline(device="cpu")


def _make_raddino_pipeline() -> AnalysisPipeline:
    path = _create_temporary_head()
    os.environ["CLASSIFIER_HEAD"] = path
    try:
        return AnalysisPipeline(device="cpu")
    except Exception:
        os.remove(path)
        raise


def test_analysis_pipeline(pipeline=None):
    pipeline = pipeline or _make_pipeline()
    img = Image.new("RGB", (512, 512), color=(128, 128, 128))
    result = pipeline.analyze(img)
    assert result.image_id
    assert len(result.findings) > 0
    assert any(f.confidence > 0 for f in result.findings)
    assert result.report
    assert result.mask is not None
    assert result.localization_maps is not None


def test_chat(pipeline=None):
    # With no chat backend configured, the report-generator fallback answers.
    old_chat = os.environ.get("CHAT_MODEL", None)
    old_openai = os.environ.get("CHAT_OPENAI_BASE_URL", None)
    os.environ.pop("CHAT_MODEL", None)
    os.environ.pop("CHAT_OPENAI_BASE_URL", None)
    try:
        pipeline = pipeline or _make_pipeline()
        findings = [type("F", (), {"label": "Cardiomegaly", "confidence": 0.96, "region": None})]
        answer = pipeline.chat("Report", findings, "Why cardiomegaly?")
        assert isinstance(answer, str)
    finally:
        if old_chat is not None:
            os.environ["CHAT_MODEL"] = old_chat
        else:
            os.environ.pop("CHAT_MODEL", None)
        if old_openai is not None:
            os.environ["CHAT_OPENAI_BASE_URL"] = old_openai
        else:
            os.environ.pop("CHAT_OPENAI_BASE_URL", None)


def test_generate_report(pipeline=None):
    pipeline = pipeline or _make_pipeline()
    structured = {
        "modality": "Chest X-ray",
        "findings": [{"name": "pneumonia", "confidence": 0.87}],
    }
    report_result = pipeline.generate_report(structured)
    assert report_result.report


def test_raddino_backend():
    """Test the RAD-DINO head backend path (used when CLASSIFIER_HEAD is set)."""
    old_head = os.environ.pop("CLASSIFIER_HEAD", None)
    path = _create_temporary_head()
    os.environ["CLASSIFIER_HEAD"] = path
    try:
        pipeline = AnalysisPipeline(device="cpu")
        img = Image.new("RGB", (512, 512), color=(128, 128, 128))
        result = pipeline.analyze(img)
        assert len(result.findings) > 0
    finally:
        os.remove(path)
        if old_head is not None:
            os.environ["CLASSIFIER_HEAD"] = old_head
        else:
            os.environ.pop("CLASSIFIER_HEAD", None)


if __name__ == "__main__":
    test_analysis_pipeline()
    test_chat()
    test_generate_report()
    test_raddino_backend()
    print("All backend tests passed.")
