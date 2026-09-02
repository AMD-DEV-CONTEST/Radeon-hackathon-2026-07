from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import nullcontext
from functools import cached_property
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as functional
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator

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

DEFAULT_MODEL_ID = "nvidia/segformer-b0-finetuned-ade-512-512"
SEMANTIC_MAPPING_SCHEMA = "colorgraph.semantic-label-map/v2"
DEFAULT_LABEL_MAPPING_PATH = Path(__file__).resolve().with_name("semantic_labels_v2.json")


class SemanticLabelMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str = Field(alias="schema")
    version: str = Field(min_length=1)
    targets: dict[str, list[str]]

    @model_validator(mode="after")
    def validate_mapping(self) -> SemanticLabelMapping:
        if self.schema_version != SEMANTIC_MAPPING_SCHEMA:
            raise ValueError(f"unsupported semantic label mapping: {self.schema_version}")
        if not self.targets:
            raise ValueError("semantic label mapping must define targets")
        owners: dict[str, str] = {}
        for target, aliases in self.targets.items():
            if not target or not aliases:
                raise ValueError("semantic targets and alias lists cannot be empty")
            for alias in aliases:
                normalized = " ".join(alias.casefold().replace("_", " ").split())
                if not normalized:
                    raise ValueError("semantic label aliases cannot be empty")
                owner = owners.get(normalized)
                if owner is not None and owner != target:
                    raise ValueError(
                        f"semantic alias {normalized!r} belongs to both {owner!r} "
                        f"and {target!r}"
                    )
                owners[normalized] = target
        return self


def load_semantic_label_mapping(
    path: str | Path | None = None,
) -> tuple[SemanticLabelMapping, str]:
    configured = path or os.getenv("COLORGRAPH_SEMANTIC_LABEL_MAP")
    resolved = Path(configured).resolve() if configured else DEFAULT_LABEL_MAPPING_PATH
    payload = resolved.read_bytes()
    mapping = SemanticLabelMapping.model_validate(json.loads(payload))
    return mapping, hashlib.sha256(payload).hexdigest()


_DEFAULT_LABEL_MAPPING, _DEFAULT_LABEL_MAPPING_SHA256 = load_semantic_label_mapping()
TARGET_LABELS: dict[str, frozenset[str]] = {
    target: frozenset(aliases)
    for target, aliases in _DEFAULT_LABEL_MAPPING.targets.items()
}


def _normalized_label_parts(label: str) -> set[str]:
    normalized = re.sub(r"\s+", " ", label.lower().replace("_", " ")).strip()
    return {part.strip() for part in re.split(r"[,;/]", normalized) if part.strip()} | {normalized}


def resolve_semantic_class_ids(
    id2label: dict[int | str, str],
    target_labels: dict[str, frozenset[str]],
) -> dict[str, list[int]]:
    resolved: dict[str, list[int]] = {target: [] for target in target_labels}
    for raw_class_id, raw_label in id2label.items():
        label_parts = _normalized_label_parts(str(raw_label))
        matched_targets = [
            target
            for target, aliases in target_labels.items()
            if label_parts & aliases
        ]
        if len(matched_targets) > 1:
            raise ValueError(
                f"model class {raw_label!r} resolves to multiple semantic targets: "
                f"{matched_targets}"
            )
        if matched_targets:
            resolved[matched_targets[0]].append(int(raw_class_id))
    return resolved


def _feather(mask: np.ndarray, sigma: float = 1.2) -> np.ndarray:
    return cv2.GaussianBlur(mask.astype(np.float32), (0, 0), sigma).clip(0, 1)


class SemanticMaskProvider(MaskProvider):
    def __init__(
        self,
        backend: ComputeBackend,
        model_id: str | None = None,
        *,
        model_revision: str | None = None,
        label_mapping_path: str | Path | None = None,
        probability_threshold: float = 0.30,
        local_files_only: bool = False,
    ) -> None:
        if not 0 < probability_threshold < 1:
            raise ValueError("semantic probability threshold must be between zero and one")
        self.backend = backend
        self.model_id = model_id or os.getenv(
            "COLORGRAPH_SEGMENTATION_MODEL",
            DEFAULT_MODEL_ID,
        )
        self.model_revision = model_revision or os.getenv(
            "COLORGRAPH_SEGMENTATION_MODEL_REVISION"
        )
        self.local_files_only = local_files_only
        self.probability_threshold = probability_threshold
        self.label_mapping, self.label_mapping_sha256 = load_semantic_label_mapping(
            label_mapping_path
        )
        self.target_labels = {
            target: frozenset(
                " ".join(alias.casefold().replace("_", " ").split())
                for alias in aliases
            )
            for target, aliases in self.label_mapping.targets.items()
        }
        self.last_inference_evidence: TorchStageEvidence | None = None

    @property
    def provider_id(self) -> str:
        return self.model_id

    @property
    def supported_targets(self) -> frozenset[str]:
        return frozenset(self.target_labels)

    def _load_resource(self) -> TorchModelResource:
        from transformers import AutoImageProcessor, AutoModelForSemanticSegmentation
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
        model = AutoModelForSemanticSegmentation.from_pretrained(
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
            family="semantic-segmentation",
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
        return release_inference_models(family="semantic-segmentation")

    @cached_property
    def _target_class_ids(self) -> dict[str, list[int]]:
        with self._model_resource() as resource:
            return resolve_semantic_class_ids(
                resource.model.config.id2label,
                self.target_labels,
            )

    def predict_many(
        self,
        image: Image.Image,
        targets: list[str],
    ) -> dict[str, MaskPrediction]:
        unsupported = set(targets) - self.supported_targets
        if unsupported:
            raise ValueError(f"unsupported semantic targets: {sorted(unsupported)}")

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
                stage="semantic_segmentation",
                model_id=self.model_id,
                model=model,
                inputs=inputs,
            )
            with self.backend.inference_context():
                logits = model(**inputs).logits
                self.last_inference_evidence = evidence.finish(logits)
                logits = functional.interpolate(
                    logits,
                    size=(rgb.height, rgb.width),
                    mode="bilinear",
                    align_corners=False,
                )
                probabilities = logits.float().softmax(dim=1)[0]

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
            results: dict[str, MaskPrediction] = {}
            for target in targets:
                class_ids = self._target_class_ids[target]
                if class_ids:
                    probability = probabilities[class_ids].sum(dim=0).clamp(0, 1)
                    mask = probability.cpu().numpy().astype(np.float32)
                    selected = mask >= self.probability_threshold
                    confidence = float(mask[selected].mean()) if selected.any() else 0.0
                else:
                    mask = np.zeros((rgb.height, rgb.width), dtype=np.float32)
                    confidence = 0.0
                class_labels = [
                    str(model.config.id2label.get(class_id, class_id))
                    for class_id in class_ids
                ]
                results[target] = MaskPrediction(
                    target=target,
                    mask=_feather(mask),
                    confidence=max(0.0, min(1.0, confidence)),
                    metadata={
                        "provider": self.provider_id,
                        **model_provenance,
                        "torch_stage_evidence": self.last_inference_evidence.model_dump(
                            mode="json"
                        ),
                        "class_ids": class_ids,
                        "class_labels": class_labels,
                        "class_mapping_status": (
                            "resolved" if class_ids else "model_class_missing"
                        ),
                        "probability_threshold": self.probability_threshold,
                        "score_semantics": (
                            "mean_model_probability_over_selected_pixels"
                        ),
                        "confidence_is_accuracy": False,
                        "label_mapping_version": self.label_mapping.version,
                        "label_mapping_sha256": self.label_mapping_sha256,
                    },
                    score_semantics="mean_model_probability_over_selected_pixels",
                )
            return results


class OneFormerSemanticMaskProvider(SemanticMaskProvider):
    def _load_resource(self) -> TorchModelResource:
        from transformers import (
            OneFormerForUniversalSegmentation,
            OneFormerProcessor,
        )
        from transformers.utils import logging

        logging.disable_progress_bar()

        cache_dir = settings.huggingface_cache_dir
        load_options: dict[str, object] = {
            "cache_dir": cache_dir,
            "local_files_only": self.local_files_only,
        }
        if self.model_revision is not None:
            load_options["revision"] = self.model_revision
        processor = OneFormerProcessor.from_pretrained(
            self.model_id,
            **load_options,
        )
        model = OneFormerForUniversalSegmentation.from_pretrained(
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
            model_revision=(
                str(model_revision) if model_revision else None
            ),
            checkpoint_sha256=checkpoint_sha256,
            checkpoint_hash_kind="colorgraph.torch-state-dict/v1",
        )

    def predict_many(
        self,
        image: Image.Image,
        targets: list[str],
    ) -> dict[str, MaskPrediction]:
        unsupported = set(targets) - self.supported_targets
        if unsupported:
            raise ValueError(
                f"unsupported semantic targets: {sorted(unsupported)}"
            )

        rgb = image.convert("RGB")
        with self._model_resource() as resource:
            processor, model = resource.processor, resource.model
            inputs = processor(
                images=rgb,
                task_inputs=["semantic"],
                return_tensors="pt",
            )
            inputs = {
                key: value.to(self.backend.torch_device)
                for key, value in inputs.items()
            }
            if (
                self.backend.info.runtime in {"cuda", "rocm"}
                and "pixel_values" in inputs
            ):
                inputs["pixel_values"] = inputs["pixel_values"].to(
                    dtype=torch.float16
                )

            evidence = TorchStageEvidenceRecorder(
                self.backend,
                stage="oneformer_semantic_segmentation",
                model_id=self.model_id,
                model=model,
                inputs=inputs,
            )
            with self.backend.inference_context():
                outputs = model(**inputs)
                self.last_inference_evidence = evidence.finish(outputs)
                processed = processor.post_process_semantic_segmentation(
                    outputs,
                    target_sizes=[(rgb.height, rgb.width)],
                    return_segmentation_scores=True,
                )[0]
                probabilities = processed.segmentation_scores.float()

            if (
                probabilities.ndim != 3
                or tuple(probabilities.shape[1:])
                != (rgb.height, rgb.width)
            ):
                raise ValueError(
                    "OneFormer semantic score map has an unexpected shape"
                )
            model_revision = resource.model_revision or str(
                getattr(model.config, "_commit_hash", None)
                or getattr(model.config, "revision", None)
                or "unreported"
            )
            model_provenance: dict[str, object] = {
                "model_revision": model_revision,
            }
            if resource.checkpoint_sha256 is not None:
                model_provenance["checkpoint_sha256"] = (
                    resource.checkpoint_sha256
                )
            if resource.checkpoint_hash_kind is not None:
                model_provenance["checkpoint_hash_kind"] = (
                    resource.checkpoint_hash_kind
                )

            results: dict[str, MaskPrediction] = {}
            for target in targets:
                class_ids = self._target_class_ids[target]
                if class_ids:
                    probability = probabilities[class_ids].sum(dim=0).clamp(
                        0,
                        1,
                    )
                    mask = probability.cpu().numpy().astype(np.float32)
                    selected = mask >= self.probability_threshold
                    confidence = (
                        float(mask[selected].mean())
                        if selected.any()
                        else 0.0
                    )
                else:
                    mask = np.zeros(
                        (rgb.height, rgb.width),
                        dtype=np.float32,
                    )
                    confidence = 0.0
                class_labels = [
                    str(model.config.id2label.get(class_id, class_id))
                    for class_id in class_ids
                ]
                results[target] = MaskPrediction(
                    target=target,
                    mask=_feather(mask),
                    confidence=max(0.0, min(1.0, confidence)),
                    metadata={
                        "provider": self.provider_id,
                        **model_provenance,
                        "torch_stage_evidence": self.last_inference_evidence.model_dump(
                            mode="json"
                        ),
                        "class_ids": class_ids,
                        "class_labels": class_labels,
                        "class_mapping_status": (
                            "resolved"
                            if class_ids
                            else "model_class_missing"
                        ),
                        "probability_threshold": (
                            self.probability_threshold
                        ),
                        "score_semantics": (
                            "mean_postprocessed_semantic_probability_over_"
                            "selected_pixels"
                        ),
                        "confidence_is_accuracy": False,
                        "label_mapping_version": (
                            self.label_mapping.version
                        ),
                        "label_mapping_sha256": (
                            self.label_mapping_sha256
                        ),
                        "oneformer_task_input": "semantic",
                    },
                    score_semantics=(
                        "mean_postprocessed_semantic_probability_over_"
                        "selected_pixels"
                    ),
                )
            return results
