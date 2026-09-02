from __future__ import annotations

import os
from contextlib import nullcontext
from dataclasses import dataclass

import cv2
import numpy as np
import torch
import torch.nn.functional as functional
from PIL import Image

from colorgraph.config import settings
from colorgraph.devices.base import ComputeBackend
from colorgraph.devices.evidence import TorchStageEvidence, TorchStageEvidenceRecorder
from colorgraph.vision.base import MaskPrediction, MaskProvider
from colorgraph.vision.model_lifecycle import (
    MODEL_LIFECYCLE_CACHE,
    TorchModelResource,
    estimate_torch_model_bytes,
    release_inference_models,
    torch_model_cache_key,
    torch_model_state_sha256,
    unload_torch_resource,
)

DEFAULT_MODEL_ID = "depth-anything/Depth-Anything-V2-Small-hf"
DEPTH_TARGETS = frozenset({"depth_near", "depth_mid", "depth_far"})
DEPTH_CALIBRATION_VERSION = "colorgraph.shot-depth-calibration/v1"
_QUANTILE_LEVELS = np.asarray([5.0, 25.0, 50.0, 75.0, 95.0], dtype=np.float64)


@dataclass(frozen=True, slots=True)
class CalibratedDepth:
    raw_inverse_depth: np.ndarray
    aligned_inverse_depth: np.ndarray
    normalized_near_score: np.ndarray
    uncertainty: float
    valid_sample_ratio: float
    scale: float
    shift: float
    shot_quantiles: tuple[float, ...]
    alignment_residual: float


class ShotDepthCalibrator:
    """Hold one depth scale for a shot and align later anchors into it."""

    def __init__(self) -> None:
        self.shot_id: str | None = None
        self._reference_quantiles: np.ndarray | None = None

    def reset(self, shot_id: str | None = None) -> None:
        self.shot_id = shot_id
        self._reference_quantiles = None

    def calibrate(self, raw_depth: np.ndarray) -> CalibratedDepth:
        raw = np.asarray(raw_depth, dtype=np.float32)
        finite = np.isfinite(raw)
        valid_ratio = float(np.mean(finite))
        if not np.any(finite):
            raise ValueError("depth prediction does not contain finite samples")
        finite_values = raw[finite].astype(np.float64)
        replacement = float(np.median(finite_values))
        safe = np.where(finite, raw, replacement).astype(np.float32)
        current_quantiles = np.percentile(finite_values, _QUANTILE_LEVELS)
        current_range = max(float(current_quantiles[-1] - current_quantiles[0]), 1e-6)

        if self._reference_quantiles is None:
            self._reference_quantiles = current_quantiles
            scale = 1.0
            shift = 0.0
            alignment_residual = 0.0
            uncertainty = 0.18 + 0.5 * (1.0 - valid_ratio)
        else:
            design = np.column_stack(
                (current_quantiles, np.ones_like(current_quantiles))
            )
            coefficients, *_ = np.linalg.lstsq(
                design,
                self._reference_quantiles,
                rcond=None,
            )
            scale = float(coefficients[0])
            shift = float(coefficients[1])
            invalid_scale = not np.isfinite(scale) or scale <= 0 or not 0.20 <= scale <= 5.0
            if invalid_scale:
                scale = 1.0
                shift = float(self._reference_quantiles[2] - current_quantiles[2])
            fitted = current_quantiles * scale + shift
            reference_range = max(
                float(self._reference_quantiles[-1] - self._reference_quantiles[0]),
                1e-6,
            )
            alignment_residual = float(
                np.median(np.abs(fitted - self._reference_quantiles)) / reference_range
            )
            uncertainty = (
                0.06
                + min(alignment_residual * 2.5, 0.70)
                + 0.5 * (1.0 - valid_ratio)
                + (0.20 if invalid_scale else 0.0)
            )

        aligned = safe * scale + shift
        assert self._reference_quantiles is not None
        reference_low = float(self._reference_quantiles[0])
        reference_high = float(self._reference_quantiles[-1])
        reference_range = max(reference_high - reference_low, 1e-6)
        normalized = ((aligned - reference_low) / reference_range).clip(0, 1)
        if current_range <= max(abs(float(current_quantiles[2])) * 1e-4, 1e-5):
            uncertainty = max(uncertainty, 0.90)
        return CalibratedDepth(
            raw_inverse_depth=safe,
            aligned_inverse_depth=aligned.astype(np.float32),
            normalized_near_score=normalized.astype(np.float32),
            uncertainty=float(np.clip(uncertainty, 0.02, 1.0)),
            valid_sample_ratio=valid_ratio,
            scale=scale,
            shift=shift,
            shot_quantiles=tuple(float(value) for value in self._reference_quantiles),
            alignment_residual=alignment_residual,
        )


class DepthMaskProvider(MaskProvider):
    def __init__(
        self,
        backend: ComputeBackend,
        model_id: str | None = None,
        *,
        model_revision: str | None = None,
        local_files_only: bool = False,
    ) -> None:
        self.backend = backend
        self.model_id = model_id or os.getenv(
            "COLORGRAPH_DEPTH_MODEL",
            DEFAULT_MODEL_ID,
        )
        self.model_revision = model_revision or os.getenv(
            "COLORGRAPH_DEPTH_MODEL_REVISION"
        )
        self.local_files_only = local_files_only
        self.calibrator = ShotDepthCalibrator()
        self.last_depth: CalibratedDepth | None = None
        self.last_inference_evidence: TorchStageEvidence | None = None

    @property
    def provider_id(self) -> str:
        return self.model_id

    @property
    def supported_targets(self) -> frozenset[str]:
        return DEPTH_TARGETS

    def reset_shot(self, shot_id: str | None = None) -> None:
        self.calibrator.reset(shot_id)
        self.last_depth = None

    def _load_resource(self) -> TorchModelResource:
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation
        from transformers.utils import logging

        logging.disable_progress_bar()

        cache_dir = settings.huggingface_cache_dir
        load_options: dict[str, object] = {
            "cache_dir": cache_dir,
            "local_files_only": self.local_files_only,
        }
        if self.model_revision is not None:
            load_options["revision"] = self.model_revision
        processor = AutoImageProcessor.from_pretrained(
            self.model_id,
            **load_options,
        )
        model = AutoModelForDepthEstimation.from_pretrained(
            self.model_id,
            **load_options,
        )
        model_revision = (
            getattr(model.config, "_commit_hash", None)
            or getattr(model.config, "revision", None)
            or self.model_revision
        )
        checkpoint_sha256 = torch_model_state_sha256(model)
        model.eval()
        model.to(self.backend.torch_device)
        if self.backend.info.runtime in {"cuda", "rocm"}:
            model.to(dtype=torch.float16)
        return TorchModelResource(
            processor=processor,
            model=model,
            model_revision=str(model_revision) if model_revision else None,
            checkpoint_sha256=checkpoint_sha256,
            checkpoint_hash_kind="colorgraph.torch-state-dict/v1",
        )

    def _model_resource(self):
        override = self.__dict__.get("_processor_and_model")
        if override is not None:
            processor, model = override
            return nullcontext(TorchModelResource(processor=processor, model=model))
        key = torch_model_cache_key(
            family="depth-estimation",
            model_id=(
                f"{self.model_id}@{self.model_revision}"
                if self.model_revision is not None
                else self.model_id
            ),
            backend=self.backend,
        )
        return MODEL_LIFECYCLE_CACHE.acquire(
            key,
            loader=self._load_resource,
            estimate_bytes=estimate_torch_model_bytes,
            unload=lambda resource: unload_torch_resource(
                resource,
                backend=self.backend,
            ),
        )

    def release_model(self) -> int:
        return release_inference_models(family="depth-estimation")

    def predict_many(
        self,
        image: Image.Image,
        targets: list[str],
    ) -> dict[str, MaskPrediction]:
        unsupported = set(targets) - self.supported_targets
        if unsupported:
            raise ValueError(f"unsupported depth targets: {sorted(unsupported)}")

        rgb = image.convert("RGB")
        with self._model_resource() as resource:
            processor, model = resource.processor, resource.model
            inputs = processor(images=rgb, return_tensors="pt")
            inputs = {
                key: value.to(self.backend.torch_device)
                for key, value in inputs.items()
            }
            if self.backend.info.runtime in {"cuda", "rocm"} and "pixel_values" in inputs:
                inputs["pixel_values"] = inputs["pixel_values"].to(dtype=torch.float16)

            evidence = TorchStageEvidenceRecorder(
                self.backend,
                stage="depth_estimation",
                model_id=self.model_id,
                model=model,
                inputs=inputs,
            )
            with self.backend.inference_context():
                predicted = model(**inputs).predicted_depth
                self.last_inference_evidence = evidence.finish(predicted)
                predicted = functional.interpolate(
                    predicted.unsqueeze(1).float(),
                    size=(rgb.height, rgb.width),
                    mode="bicubic",
                    align_corners=False,
                )[0, 0]

            # Depth Anything emits relative inverse depth: larger values are nearer.
            calibrated = self.calibrator.calibrate(predicted.cpu().numpy())
            self.last_depth = calibrated
            near_score = calibrated.normalized_near_score
            masks = {
                "depth_near": np.clip((near_score - 0.45) / 0.55, 0, 1),
                "depth_far": np.clip((0.55 - near_score) / 0.55, 0, 1),
                "depth_mid": np.clip(1 - np.abs(near_score - 0.5) * 2.2, 0, 1),
            }
            model_revision = resource.model_revision or str(
                getattr(model.config, "_commit_hash", None)
                or getattr(model.config, "revision", None)
                or "unreported"
            )
            model_provenance: dict[str, object] = {
                "model_revision": model_revision,
            }
            if resource.checkpoint_sha256 is not None:
                model_provenance["checkpoint_sha256"] = resource.checkpoint_sha256
            if resource.checkpoint_hash_kind is not None:
                model_provenance["checkpoint_hash_kind"] = (
                    resource.checkpoint_hash_kind
                )
            confidence = 1.0 - calibrated.uncertainty
            results: dict[str, MaskPrediction] = {}
            for target in targets:
                mask = cv2.GaussianBlur(
                    masks[target].astype(np.float32),
                    (0, 0),
                    1.5,
                ).clip(0, 1)
                results[target] = MaskPrediction(
                    target=target,
                    mask=mask,
                    confidence=confidence,
                    metadata={
                        "provider": self.provider_id,
                        **model_provenance,
                        "torch_stage_evidence": self.last_inference_evidence.model_dump(
                            mode="json"
                        ),
                        "depth_convention": "larger_is_nearer",
                        "calibration_version": DEPTH_CALIBRATION_VERSION,
                        "calibration_scope": "shot",
                        "shot_id": self.calibrator.shot_id or "unassigned",
                        "valid_sample_ratio": calibrated.valid_sample_ratio,
                        "uncertainty": calibrated.uncertainty,
                        "scale": calibrated.scale,
                        "shift": calibrated.shift,
                        "alignment_residual": calibrated.alignment_residual,
                        "shot_quantiles": list(calibrated.shot_quantiles),
                        "score_semantics": "one_minus_temporal_scale_uncertainty",
                        "confidence_is_accuracy": False,
                    },
                    score_semantics="one_minus_temporal_scale_uncertainty",
                )
            return results
