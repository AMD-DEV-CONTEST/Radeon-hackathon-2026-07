from pathlib import Path

import pytest
from pydantic import ValidationError

from buildguard.config import VisionModelConfig


def test_yolo11_config_accepts_valid_yolo_class_mapping() -> None:
    cfg = VisionModelConfig(
        model_name="yolo11-ppe",
        backend="local",
        local_adapter="yolo11",
        model_path=Path(__file__),  # any existing path
        model_sha256="a" * 64,
        yolo_class_mapping={"nohat": "missing_helmet", "novest": "missing_vest"},
        defect_classes=["missing_helmet", "missing_vest"],
    )
    assert cfg.yolo_class_mapping == {"nohat": "missing_helmet", "novest": "missing_vest"}


def test_yolo11_config_rejects_missing_sha256() -> None:
    with pytest.raises(Exception, match="yolo11 adapter is missing required fields"):
        VisionModelConfig(
            model_name="yolo11-ppe",
            backend="local",
            local_adapter="yolo11",
            model_path=Path(__file__),
            yolo_class_mapping={"nohat": "missing_helmet"},
            defect_classes=["missing_helmet"],
        )


def test_yolo11_config_rejects_missing_model_path() -> None:
    with pytest.raises(ValidationError, match="model_path is required for local vision backend"):
        VisionModelConfig(
            model_name="yolo11-ppe",
            backend="local",
            local_adapter="yolo11",
            model_sha256="a" * 64,
            yolo_class_mapping={"nohat": "missing_helmet"},
            defect_classes=["missing_helmet"],
        )
