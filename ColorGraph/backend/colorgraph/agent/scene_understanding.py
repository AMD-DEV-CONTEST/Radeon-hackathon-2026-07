from __future__ import annotations

import hashlib
from contextlib import nullcontext
from pathlib import Path

import torch
import torch.nn.functional as functional
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from colorgraph.agent.vlm_shadow import (
    DEFAULT_VLM_LABELS,
    VLMLabelSpec,
    VLMShadowBatchReport,
    VLMShadowCalibration,
    score_vlm_shadow_embeddings,
)
from colorgraph.config import settings
from colorgraph.devices.base import ComputeBackend
from colorgraph.devices.evidence import TorchStageEvidence, TorchStageEvidenceRecorder
from colorgraph.vision.model_lifecycle import (
    IMAGE_EMBEDDING_CACHE,
    MODEL_LIFECYCLE_CACHE,
    TorchModelResource,
    estimate_torch_model_bytes,
    inference_cache_stats,
    release_inference_models,
    torch_model_cache_key,
    torch_model_state_sha256,
    unload_torch_resource,
)


class SceneTag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    confidence: float = Field(ge=0, le=1)


class ShotSceneAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_path: str
    terrain: SceneTag
    lighting: SceneTag
    risk: SceneTag
    suggested_look: SceneTag
    model_id: str
    model_revision: str | None = None
    checkpoint_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    checkpoint_hash_kind: str | None = None
    device_runtime: str


CANDIDATES = {
    "terrain": [
        "a mountain landscape",
        "a forest landscape",
        "a coast or ocean landscape",
        "a lake or river landscape",
        "a snowy landscape",
        "a foggy valley landscape",
        "an urban landscape",
    ],
    "lighting": [
        "bright sunny daylight",
        "soft overcast daylight",
        "golden hour sunset light",
        "blue hour twilight",
        "misty low contrast light",
        "dramatic high contrast light",
    ],
    "risk": [
        "a landscape with clipped bright sky",
        "a landscape with a dark foreground",
        "a landscape with oversaturated green vegetation",
        "a landscape with low contrast haze",
        "a naturally balanced landscape exposure",
    ],
    "suggested_look": [
        "natural clean travel photography colors",
        "cool restrained documentary colors",
        "warm cinematic sunset colors",
        "soft desaturated foggy cinematic colors",
    ],
}


def _friendly_label(value: str) -> str:
    replacements = {
        "a ": "",
        " landscape": "",
        " colors": "",
        " light": "",
    }
    label = value
    for old, new in replacements.items():
        label = label.replace(old, new)
    return label.strip()


def _feature_tensor(output: object) -> torch.Tensor:
    if isinstance(output, torch.Tensor):
        return output
    pooler_output = getattr(output, "pooler_output", None)
    if isinstance(pooler_output, torch.Tensor):
        return pooler_output
    try:
        candidate = output[0]  # type: ignore[index]
    except (IndexError, KeyError, TypeError) as exc:
        raise TypeError("model feature output does not contain a tensor") from exc
    if not isinstance(candidate, torch.Tensor):
        raise TypeError("model feature output does not contain a tensor")
    return candidate


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class LocalSceneAnalyzer:
    """CLIP-based local multimodal perception behind the shared torch device."""

    def __init__(
        self,
        backend: ComputeBackend,
        model_id: str | None = None,
        model_revision: str | None = None,
        *,
        local_files_only: bool = False,
    ) -> None:
        self.backend = backend
        self.model_id = model_id or settings.scene_model_id
        self.model_revision = model_revision
        self.local_files_only = local_files_only
        self.inference_evidence: list[TorchStageEvidence] = []

    def _load_resource(self) -> TorchModelResource:
        from transformers import AutoModel, AutoProcessor
        from transformers.utils import logging

        logging.disable_progress_bar()

        cache_dir = settings.huggingface_cache_dir
        load_options: dict[str, object] = {
            "cache_dir": cache_dir,
            "local_files_only": self.local_files_only,
        }
        if self.model_revision is not None:
            load_options["revision"] = self.model_revision
        processor = AutoProcessor.from_pretrained(self.model_id, **load_options)
        model = AutoModel.from_pretrained(self.model_id, **load_options)
        model_revision = (
            getattr(model.config, "_commit_hash", None)
            or getattr(model.config, "revision", None)
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
            family="clip-scene",
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

    @staticmethod
    def _model_revision(resource: TorchModelResource) -> str:
        config = getattr(resource.model, "config", None)
        return str(
            resource.model_revision
            or getattr(config, "_commit_hash", None)
            or getattr(config, "revision", None)
            or "unreported"
        )

    def _image_features(self, frame_paths: list[str | Path]) -> torch.Tensor:
        if not frame_paths:
            return torch.empty((0, 0), dtype=torch.float32)
        resolved = [Path(path).resolve() for path in frame_paths]
        with self._model_resource() as resource:
            revision = self._model_revision(resource)
            checkpoint_identity = resource.checkpoint_sha256 or "checkpoint-unreported"
            cache_keys = [
                hashlib.sha256(
                    (
                        f"{self.model_id}\0{revision}\0{checkpoint_identity}\0"
                        f"{self.backend.info.runtime}\0"
                        f"{_file_sha256(path)}"
                    ).encode()
                ).hexdigest()
                for path in resolved
            ]
            features: list[torch.Tensor | None] = [
                IMAGE_EMBEDDING_CACHE.get(key) for key in cache_keys
            ]
            missing: dict[str, tuple[Path, list[int]]] = {}
            for index, (path, cache_key, feature) in enumerate(
                zip(resolved, cache_keys, features, strict=True)
            ):
                if feature is None:
                    if cache_key not in missing:
                        missing[cache_key] = (path, [])
                    missing[cache_key][1].append(index)
            if missing:
                images: list[Image.Image] = []
                try:
                    for path, _ in missing.values():
                        with Image.open(path) as source:
                            images.append(source.convert("RGB"))
                    inputs = resource.processor(images=images, return_tensors="pt")
                    pixel_values = inputs["pixel_values"].to(self.backend.torch_device)
                    if self.backend.info.runtime in {"cuda", "rocm"}:
                        pixel_values = pixel_values.to(dtype=torch.float16)
                    evidence = TorchStageEvidenceRecorder(
                        self.backend,
                        stage="clip_image_embedding",
                        model_id=self.model_id,
                        model=resource.model,
                        inputs={"pixel_values": pixel_values},
                    )
                    with self.backend.inference_context():
                        output = resource.model.get_image_features(
                            pixel_values=pixel_values
                        )
                        feature_tensor = _feature_tensor(output)
                        self.inference_evidence.append(
                            evidence.finish(feature_tensor)
                        )
                        encoded = functional.normalize(
                            feature_tensor.float(),
                            dim=-1,
                        ).cpu()
                finally:
                    for image in images:
                        image.close()
                for (cache_key, (_, indexes)), feature in zip(
                    missing.items(),
                    encoded,
                    strict=True,
                ):
                    IMAGE_EMBEDDING_CACHE.put(cache_key, feature)
                    for index in indexes:
                        features[index] = feature
        if any(feature is None for feature in features):
            raise RuntimeError("image embedding cache did not resolve every input")
        return torch.stack(
            [feature for feature in features if feature is not None]
        )

    def _text_features(
        self,
        resource: TorchModelResource,
        candidates: list[str],
    ) -> torch.Tensor:
        revision = self._model_revision(resource)
        checkpoint_identity = resource.checkpoint_sha256 or "checkpoint-unreported"
        cache_key = hashlib.sha256(
            (
                f"{self.model_id}\0{revision}\0{checkpoint_identity}\0"
                + "\0".join(candidates)
            ).encode()
        ).hexdigest()
        with resource.auxiliary_lock:
            cached = resource.auxiliary_tensors.get(cache_key)
            if cached is not None:
                return cached
            model_type = str(
                getattr(getattr(resource.model, "config", None), "model_type", "")
            ).lower()
            siglip = "siglip" in model_type or "siglip2" in self.model_id.lower()
            processor_options: dict[str, object] = {
                "text": candidates,
                "return_tensors": "pt",
                "padding": "max_length" if siglip else True,
            }
            if siglip:
                processor_options.update(max_length=64, truncation=True)
            inputs = resource.processor(**processor_options)
            inputs = {
                key: value.to(self.backend.torch_device)
                for key, value in inputs.items()
            }
            evidence = TorchStageEvidenceRecorder(
                self.backend,
                stage="clip_text_embedding",
                model_id=self.model_id,
                model=resource.model,
                inputs=inputs,
            )
            with self.backend.inference_context():
                output = resource.model.get_text_features(**inputs)
                feature_tensor = _feature_tensor(output)
                self.inference_evidence.append(
                    evidence.finish(feature_tensor)
                )
                encoded = functional.normalize(
                    feature_tensor.float(),
                    dim=-1,
                )
            resource.auxiliary_tensors[cache_key] = encoded
            return encoded

    @staticmethod
    def _logit_scale(model: object) -> torch.Tensor | float:
        value = getattr(model, "logit_scale", None)
        return value.float().exp() if isinstance(value, torch.Tensor) else 1.0

    @staticmethod
    def _logit_bias(model: object) -> torch.Tensor | float:
        value = getattr(model, "logit_bias", None)
        return value.float() if isinstance(value, torch.Tensor) else 0.0

    def _uses_independent_sigmoid(self, model: object) -> bool:
        model_type = str(
            getattr(getattr(model, "config", None), "model_type", "")
        ).lower()
        return "siglip" in model_type or "siglip2" in self.model_id.lower()

    def _rank_feature_sets(
        self,
        image_feature: torch.Tensor,
        candidate_sets: dict[str, list[str]],
    ) -> dict[str, SceneTag]:
        ranked: dict[str, SceneTag] = {}
        with self._model_resource() as resource:
            image = image_feature.to(self.backend.torch_device).view(1, -1)
            for category, candidates in candidate_sets.items():
                text = self._text_features(resource, candidates)
                logits = (
                    (image @ text.transpose(0, 1)).mul(
                        self._logit_scale(resource.model)
                    )
                    + self._logit_bias(resource.model)
                )
                probabilities = logits.float()
                probabilities = (
                    probabilities.sigmoid()
                    if self._uses_independent_sigmoid(resource.model)
                    else probabilities.softmax(dim=-1)
                )[0]
                best = int(probabilities.argmax().item())
                ranked[category] = SceneTag(
                    label=_friendly_label(candidates[best]),
                    confidence=float(probabilities[best].item()),
                )
        return ranked

    def release_model(self) -> int:
        return release_inference_models(family="clip-scene")

    def reset_inference_evidence(self) -> None:
        self.inference_evidence.clear()

    @staticmethod
    def cache_stats() -> dict[str, dict[str, int]]:
        return inference_cache_stats()

    def embed_images(self, frame_paths: list[str | Path]) -> torch.Tensor:
        """Return normalized CPU CLIP embeddings with content-addressed reuse."""

        return self._image_features(frame_paths)

    def rank_look(self, frame_path: str | Path) -> SceneTag:
        feature = self._image_features([frame_path])[0]
        return self._rank_feature_sets(
            feature,
            {"suggested_look": CANDIDATES["suggested_look"]},
        )["suggested_look"]

    def score_images_against_text(
        self,
        frame_paths: list[str | Path],
        text: str,
    ) -> list[float]:
        if not frame_paths:
            return []
        normalized_text = text.strip()
        if not normalized_text:
            raise ValueError("comparison text cannot be empty")
        image_features = self._image_features(frame_paths)
        with self._model_resource() as resource:
            text_features = self._text_features(resource, [normalized_text])
            logits = (
                image_features.to(self.backend.torch_device)
                @ text_features.transpose(0, 1)
            )[:, 0]
            probabilities = logits.mul(
                self._logit_scale(resource.model)
            ).float().softmax(dim=0)
        return probabilities.cpu().tolist()

    def analyze_vlm_shadow(
        self,
        frame_paths: list[str | Path],
        calibration: VLMShadowCalibration,
        *,
        labels: tuple[VLMLabelSpec, ...] = DEFAULT_VLM_LABELS,
    ) -> VLMShadowBatchReport:
        if not frame_paths:
            raise ValueError("VLM shadow requires at least one frame")
        resolved = [Path(path).resolve() for path in frame_paths]
        image_features = self._image_features(resolved)
        with self._model_resource() as resource:
            revision = self._model_revision(resource)
            text_features = self._text_features(
                resource,
                [label.prompt for label in labels],
            ).cpu()
            scale = self._logit_scale(resource.model)
            bias = self._logit_bias(resource.model)
            logit_scale = (
                float(scale.detach().cpu().item())
                if isinstance(scale, torch.Tensor)
                else float(scale)
            )
            logit_bias = (
                float(bias.detach().cpu().item())
                if isinstance(bias, torch.Tensor)
                else float(bias)
            )
            checkpoint_sha256 = resource.checkpoint_sha256
            checkpoint_hash_kind = resource.checkpoint_hash_kind
        return score_vlm_shadow_embeddings(
            image_features,
            text_features,
            frame_paths=[str(path) for path in resolved],
            frame_sha256=[_file_sha256(path) for path in resolved],
            labels=labels,
            calibration=calibration,
            model_id=self.model_id,
            model_revision=revision,
            logit_scale=logit_scale,
            logit_bias=logit_bias,
            checkpoint_sha256=checkpoint_sha256,
            checkpoint_hash_kind=checkpoint_hash_kind,
        )

    def analyze(self, frame_path: str | Path) -> ShotSceneAnalysis:
        resolved = Path(frame_path).resolve()
        feature = self._image_features([resolved])[0]
        ranked = self._rank_feature_sets(feature, CANDIDATES)
        with self._model_resource() as resource:
            model_revision = self._model_revision(resource)
            checkpoint_sha256 = resource.checkpoint_sha256
            checkpoint_hash_kind = resource.checkpoint_hash_kind
        return ShotSceneAnalysis(
            frame_path=str(resolved),
            terrain=ranked["terrain"],
            lighting=ranked["lighting"],
            risk=ranked["risk"],
            suggested_look=ranked["suggested_look"],
            model_id=self.model_id,
            model_revision=model_revision,
            checkpoint_sha256=checkpoint_sha256,
            checkpoint_hash_kind=checkpoint_hash_kind,
            device_runtime=self.backend.info.runtime,
        )
