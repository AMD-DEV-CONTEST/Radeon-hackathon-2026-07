from __future__ import annotations

import gc
import json
import re
from dataclasses import dataclass
from typing import Iterable

from PIL import Image

from .mission import EvidenceObservation, MissionError
from .multimodal_ingest import MediaArtifact, MediaKind


def _release_accelerator_memory() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


@dataclass(frozen=True)
class UnderstandingResult:
    summary: str
    observations: tuple[EvidenceObservation, ...]
    model_ref: str


def parse_grounded_understanding(
    text: str,
    *,
    allowed_source_ids: set[str],
    model_ref: str,
) -> UnderstandingResult:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise MissionError("vision-language model did not return a JSON object")
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as error:
        raise MissionError("vision-language JSON is invalid") from error
    summary = str(payload.get("summary", "")).strip()
    raw_observations = payload.get("observations")
    if not summary or not isinstance(raw_observations, list):
        raise MissionError("vision-language output is missing required fields")
    observations: list[EvidenceObservation] = []
    for position, item in enumerate(raw_observations, start=1):
        source_id = str(item.get("source_id", ""))
        if source_id not in allowed_source_ids:
            raise MissionError(f"unknown evidence source ID: {source_id}")
        observations.append(
            EvidenceObservation(
                id=f"OBS-{position:03d}",
                source_artifact_id=source_id,
                claim=str(item.get("claim", "")).strip(),
                locator=str(item.get("locator", "")).strip(),
                confidence=float(item.get("confidence", 0)),
                model_ref=model_ref,
            )
        )
    if not observations:
        raise MissionError("vision-language output contains no grounded observations")
    return UnderstandingResult(summary, tuple(observations), model_ref)


class LocalQwen3VLAnalyzer:
    """Lazy, caller-owned Qwen3-VL adapter for local image/video understanding."""

    def __init__(
        self,
        model_id: str = "Qwen/Qwen3-VL-2B-Instruct",
        *,
        revision: str | None = None,
        local_files_only: bool = False,
        max_new_tokens: int = 768,
    ) -> None:
        self.model_id = model_id
        self.revision = revision
        self.local_files_only = local_files_only
        self.max_new_tokens = max_new_tokens
        self._model = None
        self._processor = None

    @property
    def model_ref(self) -> str:
        return (
            f"{self.model_id}@{self.revision}"
            if self.revision is not None
            else self.model_id
        )

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        self._processor = AutoProcessor.from_pretrained(
            self.model_id,
            revision=self.revision,
            local_files_only=self.local_files_only,
        )
        self._model = AutoModelForImageTextToText.from_pretrained(
            self.model_id,
            revision=self.revision,
            local_files_only=self.local_files_only,
            torch_dtype=torch.float16,
            device_map="auto",
        )

    def load(self) -> None:
        self._load()

    def release(self) -> None:
        self._model = None
        self._processor = None
        _release_accelerator_memory()

    def analyze(
        self,
        artifacts: Iterable[MediaArtifact],
        *,
        mission_prompt: str,
    ) -> UnderstandingResult:
        selected = tuple(
            item
            for item in artifacts
            if item.kind in {MediaKind.IMAGE, MediaKind.VIDEO}
        )
        if not selected:
            raise MissionError("Qwen3-VL requires at least one image or video")
        self._load()
        assert self._processor is not None and self._model is not None
        content: list[dict] = []
        for item in selected:
            content.append(
                {
                    "type": "image" if item.kind == MediaKind.IMAGE else "video",
                    item.kind.value: f"file://{item.path}",
                }
            )
            content.append(
                {
                    "type": "text",
                    "text": f"Source ID {item.id}; role={item.role}",
                }
            )
        content.append(
            {
                "type": "text",
                "text": (
                    f"{mission_prompt}\nReturn exactly one JSON object with keys "
                    "summary and observations. Each observation must contain "
                    "claim, source_id, locator (bounding box, frame/time, or page), "
                    "and confidence from 0 to 1. Never invent source IDs."
                ),
            }
        )
        messages = [{"role": "user", "content": content}]
        inputs = self._processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        ).to(self._model.device)
        generated = self._model.generate(
            **inputs,
            max_new_tokens=self.max_new_tokens,
            do_sample=False,
        )
        trimmed = generated[:, inputs.input_ids.shape[1] :]
        text = self._processor.batch_decode(
            trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0]
        return parse_grounded_understanding(
            text,
            allowed_source_ids={item.id for item in selected},
            model_ref=self.model_ref,
        )


class LocalWhisperTranscriber:
    """Timestamped local ASR adapter; ROCm is exposed through torch.cuda."""

    def __init__(self, model_id: str = "openai/whisper-small") -> None:
        self.model_id = model_id
        self._pipeline = None

    def _load(self) -> None:
        if self._pipeline is not None:
            return
        import torch
        from transformers import pipeline

        device = 0 if torch.cuda.is_available() else -1
        dtype = torch.float16 if device == 0 else torch.float32
        self._pipeline = pipeline(
            "automatic-speech-recognition",
            model=self.model_id,
            torch_dtype=dtype,
            device=device,
        )

    def load(self) -> None:
        self._load()

    def release(self) -> None:
        self._pipeline = None
        _release_accelerator_memory()

    def transcribe(self, artifact: MediaArtifact) -> tuple[EvidenceObservation, ...]:
        if artifact.kind not in {MediaKind.AUDIO, MediaKind.VIDEO}:
            raise MissionError("Whisper requires an audio or video artifact")
        self._load()
        result = self._pipeline(
            artifact.path,
            return_timestamps=True,
            chunk_length_s=30,
        )
        observations: list[EvidenceObservation] = []
        for position, chunk in enumerate(result.get("chunks", []), start=1):
            start, end = chunk.get("timestamp", (None, None))
            observations.append(
                EvidenceObservation(
                    id=f"ASR-{position:03d}",
                    source_artifact_id=artifact.id,
                    claim=str(chunk.get("text", "")).strip(),
                    locator=f"time:{start}-{end}",
                    confidence=1.0,
                    model_ref=self.model_ref,
                )
            )
        if not observations and str(result.get("text", "")).strip():
            observations.append(
                EvidenceObservation(
                    id="ASR-001",
                    source_artifact_id=artifact.id,
                    claim=str(result["text"]).strip(),
                    locator="time:full",
                    confidence=1.0,
                    model_ref=self.model_ref,
                )
            )
        if not observations:
            raise MissionError("Whisper returned no transcript")
        return tuple(observations)


class LocalPDFTextExtractor:
    """Exact page-located text extraction; no model is allowed to rewrite it."""

    def __init__(self, model_ref: str = "PyMuPDF/local-exact-text") -> None:
        self.model_ref = model_ref

    def extract(self, artifact: MediaArtifact) -> tuple[EvidenceObservation, ...]:
        if artifact.kind != MediaKind.PDF:
            raise MissionError("PDF extractor requires a PDF artifact")
        import fitz

        observations: list[EvidenceObservation] = []
        with fitz.open(artifact.path) as document:
            for page_index, page in enumerate(document, start=1):
                text = page.get_text("text").strip()
                if not text:
                    continue
                observations.append(
                    EvidenceObservation(
                        id=f"PDF-{page_index:03d}",
                        source_artifact_id=artifact.id,
                        claim=text,
                        locator=f"page:{page_index}",
                        confidence=1.0,
                        model_ref=self.model_ref,
                    )
                )
        if not observations:
            raise MissionError("PDF contains no extractable text")
        return tuple(observations)


@dataclass(frozen=True)
class GroundedDetection:
    label: str
    score: float
    box_xyxy: tuple[float, float, float, float]
    source_artifact_id: str
    model_ref: str

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise MissionError("grounded detection requires a label")
        if not 0 <= self.score <= 1:
            raise MissionError("grounded detection score must be between zero and one")
        x1, y1, x2, y2 = self.box_xyxy
        if not (x1 < x2 and y1 < y2):
            raise MissionError("grounded detection box is invalid")

    def to_observation(self, position: int) -> EvidenceObservation:
        box = ",".join(f"{value:.2f}" for value in self.box_xyxy)
        return EvidenceObservation(
            id=f"DINO-{position:03d}",
            source_artifact_id=self.source_artifact_id,
            claim=f"Detected {self.label}",
            locator=f"bbox_xyxy:{box}",
            confidence=self.score,
            model_ref=self.model_ref,
        )


class LocalGroundingDINO:
    """Open-set product grounding using the official Transformers adapter."""

    def __init__(
        self,
        model_id: str = "IDEA-Research/grounding-dino-tiny",
        *,
        revision: str | None = None,
        local_files_only: bool = False,
        box_threshold: float = 0.40,
        text_threshold: float = 0.30,
    ) -> None:
        self.model_id = model_id
        self.revision = revision
        self.local_files_only = local_files_only
        self.box_threshold = box_threshold
        self.text_threshold = text_threshold
        self._model = None
        self._processor = None

    @property
    def model_ref(self) -> str:
        return (
            f"{self.model_id}@{self.revision}"
            if self.revision is not None
            else self.model_id
        )

    def _load(self) -> None:
        if self._model is not None:
            return
        from transformers import (
            AutoModelForZeroShotObjectDetection,
            AutoProcessor,
        )

        self._processor = AutoProcessor.from_pretrained(
            self.model_id,
            revision=self.revision,
            local_files_only=self.local_files_only,
        )
        self._model = AutoModelForZeroShotObjectDetection.from_pretrained(
            self.model_id,
            revision=self.revision,
            local_files_only=self.local_files_only,
            device_map="auto",
        )

    def load(self) -> None:
        self._load()

    def release(self) -> None:
        self._model = None
        self._processor = None
        _release_accelerator_memory()

    def detect(
        self,
        artifact: MediaArtifact,
        *,
        text_labels: Iterable[str],
    ) -> tuple[GroundedDetection, ...]:
        if artifact.kind != MediaKind.IMAGE:
            raise MissionError("Grounding DINO requires an image artifact")
        labels = tuple(label.strip() for label in text_labels if label.strip())
        if not labels:
            raise MissionError("Grounding DINO requires at least one text label")
        self._load()
        assert self._processor is not None and self._model is not None
        import torch

        image = Image.open(artifact.path).convert("RGB")
        inputs = self._processor(
            images=image,
            text=[list(labels)],
            return_tensors="pt",
        ).to(self._model.device)
        with torch.inference_mode():
            outputs = self._model(**inputs)
        result = self._processor.post_process_grounded_object_detection(
            outputs,
            inputs.input_ids,
            threshold=self.box_threshold,
            text_threshold=self.text_threshold,
            target_sizes=[image.size[::-1]],
        )[0]
        detections = tuple(
            GroundedDetection(
                label=str(label),
                score=float(score.item()),
                box_xyxy=tuple(float(value) for value in box.tolist()),
                source_artifact_id=artifact.id,
                model_ref=self.model_ref,
            )
            for box, score, label in zip(
                result["boxes"],
                result["scores"],
                result["labels"],
            )
        )
        if not detections:
            raise MissionError("Grounding DINO found no requested object")
        return detections


@dataclass(frozen=True)
class TemporalTrackSample:
    frame_index: int
    mask_area_ratio: float
    locator: str

    def __post_init__(self) -> None:
        if self.frame_index < 0:
            raise MissionError("track frame index cannot be negative")
        if not 0 <= self.mask_area_ratio <= 1:
            raise MissionError("mask area ratio must be between zero and one")
        if not self.locator.strip():
            raise MissionError("track sample requires a locator")


@dataclass(frozen=True)
class TemporalSegmentationReport:
    passed: bool
    source_artifact_id: str
    model_ref: str
    frame_count: int
    tracked_frame_count: int
    frame_coverage: float
    nonempty_mask_rate: float
    samples: tuple[TemporalTrackSample, ...]
    schema: str = "ProofLaunchTemporalSegmentationReportV1"


def summarize_temporal_masks(
    *,
    source_artifact_id: str,
    model_ref: str,
    frame_count: int,
    frame_mask_area_ratios: Iterable[tuple[int, float]],
    minimum_frame_coverage: float = 0.95,
    minimum_nonempty_mask_rate: float = 0.95,
) -> TemporalSegmentationReport:
    if frame_count <= 0:
        raise MissionError("temporal segmentation frame count must be positive")
    samples = tuple(
        TemporalTrackSample(
            frame_index=index,
            mask_area_ratio=ratio,
            locator=f"frame:{index};mask_area_ratio:{ratio:.6f}",
        )
        for index, ratio in frame_mask_area_ratios
    )
    coverage = min(1.0, len(samples) / frame_count)
    nonempty = (
        sum(item.mask_area_ratio > 0 for item in samples) / len(samples)
        if samples
        else 0.0
    )
    return TemporalSegmentationReport(
        passed=(
            coverage >= minimum_frame_coverage
            and nonempty >= minimum_nonempty_mask_rate
        ),
        source_artifact_id=source_artifact_id,
        model_ref=model_ref,
        frame_count=frame_count,
        tracked_frame_count=len(samples),
        frame_coverage=coverage,
        nonempty_mask_rate=nonempty,
        samples=samples,
    )


class LocalSAM2VideoTracker:
    """Prompted video-object tracking with the official SAM2 Transformers API."""

    def __init__(
        self,
        model_id: str = "facebook/sam2.1-hiera-small",
        *,
        revision: str | None = None,
        local_files_only: bool = False,
        minimum_frame_coverage: float = 0.95,
        minimum_nonempty_mask_rate: float = 0.95,
    ) -> None:
        self.model_id = model_id
        self.revision = revision
        self.local_files_only = local_files_only
        self.minimum_frame_coverage = minimum_frame_coverage
        self.minimum_nonempty_mask_rate = minimum_nonempty_mask_rate
        self._model = None
        self._processor = None

    @property
    def model_ref(self) -> str:
        return (
            f"{self.model_id}@{self.revision}"
            if self.revision is not None
            else self.model_id
        )

    def _load(self) -> None:
        if self._model is not None:
            return
        from transformers import Sam2VideoModel, Sam2VideoProcessor

        self._model = Sam2VideoModel.from_pretrained(
            self.model_id,
            revision=self.revision,
            local_files_only=self.local_files_only,
            device_map="auto",
        )
        self._processor = Sam2VideoProcessor.from_pretrained(
            self.model_id,
            revision=self.revision,
            local_files_only=self.local_files_only,
        )

    def load(self) -> None:
        self._load()

    def release(self) -> None:
        self._model = None
        self._processor = None
        _release_accelerator_memory()

    def track(
        self,
        *,
        frames: Iterable[Image.Image],
        prompt_box_xyxy: tuple[float, float, float, float],
        source_artifact_id: str,
    ) -> TemporalSegmentationReport:
        selected_frames = tuple(frame.convert("RGB") for frame in frames)
        if not selected_frames:
            raise MissionError("SAM2 requires at least one video frame")
        x1, y1, x2, y2 = prompt_box_xyxy
        if not (x1 < x2 and y1 < y2):
            raise MissionError("SAM2 prompt box is invalid")
        self._load()
        assert self._processor is not None and self._model is not None
        session = self._processor.init_video_session(
            video=selected_frames,
            inference_device=self._model.device,
        )
        self._processor.add_inputs_to_inference_session(
            inference_session=session,
            frame_idx=0,
            obj_ids=1,
            input_boxes=[[[x1, y1, x2, y2]]],
        )
        ratios: list[tuple[int, float]] = []
        for output in self._model.propagate_in_video_iterator(session):
            masks = self._processor.post_process_masks(
                [output.pred_masks],
                original_sizes=[[session.video_height, session.video_width]],
                binarize=True,
            )[0]
            mask_area_ratio = float(masks.float().mean().item())
            ratios.append((int(output.frame_idx), mask_area_ratio))
        return summarize_temporal_masks(
            source_artifact_id=source_artifact_id,
            model_ref=self.model_ref,
            frame_count=len(selected_frames),
            frame_mask_area_ratios=ratios,
            minimum_frame_coverage=self.minimum_frame_coverage,
            minimum_nonempty_mask_rate=self.minimum_nonempty_mask_rate,
        )


@dataclass(frozen=True)
class AudioTextScore:
    passed: bool
    model_ref: str
    selected_label: str
    expected_label: str
    expected_probability: float
    labels: tuple[str, ...]
    probabilities: tuple[float, ...]


class LocalCLAPScorer:
    """Local audio-text semantic scoring; it complements timestamp alignment."""

    def __init__(
        self,
        model_id: str = "laion/clap-htsat-fused",
        *,
        revision: str | None = None,
        local_files_only: bool = False,
        minimum_probability: float = 0.55,
    ) -> None:
        self.model_id = model_id
        self.revision = revision
        self.local_files_only = local_files_only
        self.minimum_probability = minimum_probability
        self._model = None
        self._processor = None

    @property
    def model_ref(self) -> str:
        return (
            f"{self.model_id}@{self.revision}"
            if self.revision is not None
            else self.model_id
        )

    def _load(self) -> None:
        if self._model is not None:
            return
        from transformers import AutoProcessor, ClapModel

        self._model = ClapModel.from_pretrained(
            self.model_id,
            revision=self.revision,
            local_files_only=self.local_files_only,
            device_map="auto",
        )
        self._processor = AutoProcessor.from_pretrained(
            self.model_id,
            revision=self.revision,
            local_files_only=self.local_files_only,
        )

    def load(self) -> None:
        self._load()

    def release(self) -> None:
        self._model = None
        self._processor = None
        _release_accelerator_memory()

    def score_array(
        self,
        *,
        audio,
        sampling_rate: int,
        expected_label: str,
        candidate_labels: Iterable[str],
    ) -> AudioTextScore:
        labels = tuple(label.strip() for label in candidate_labels if label.strip())
        if expected_label not in labels:
            raise MissionError("expected CLAP label must be one of the candidates")
        if sampling_rate <= 0:
            raise MissionError("audio sampling rate must be positive")
        self._load()
        assert self._processor is not None and self._model is not None
        import torch

        inputs = self._processor(
            text=list(labels),
            audio=audio,
            sampling_rate=sampling_rate,
            return_tensors="pt",
            padding=True,
        ).to(self._model.device)
        with torch.inference_mode():
            outputs = self._model(**inputs)
        probabilities = outputs.logits_per_audio.softmax(dim=-1)[0].tolist()
        selected_index = max(range(len(labels)), key=probabilities.__getitem__)
        expected_index = labels.index(expected_label)
        expected_probability = float(probabilities[expected_index])
        return AudioTextScore(
            passed=(
                selected_index == expected_index
                and expected_probability >= self.minimum_probability
            ),
            model_ref=self.model_ref,
            selected_label=labels[selected_index],
            expected_label=expected_label,
            expected_probability=expected_probability,
            labels=labels,
            probabilities=tuple(float(value) for value in probabilities),
        )
