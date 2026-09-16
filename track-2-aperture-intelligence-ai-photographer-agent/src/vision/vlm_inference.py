"""Qwen2.5-VL inference on AMD Radeon GPU through ROCm."""

from __future__ import annotations

import json
import os
import re
import time
import fcntl
from pathlib import Path
from threading import Lock
from typing import Any

import torch
from PIL import Image, UnidentifiedImageError
from qwen_vl_utils import process_vision_info
from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

from src.vision.pose_analyzer import normalize_pose_fields
from src.vision.prompts import PHOTOGRAPHY_PROMPT

MODEL_ID = "Qwen/Qwen2.5-VL-3B-Instruct"
DEFAULT_CACHE_DIR: str | None = None
DEFAULT_LOCAL_CACHE = Path(
    "/root/.cache/huggingface/models--Qwen--Qwen2.5-VL-3B-Instruct"
)

OUTPUT_FIELDS = (
    "scene",
    "subject",
    "environment",
    "relationship",
    "composition",
    "recommendation",
)
COACHING_FIELDS = (
    "people_boxes",
    "visible_props",
    "visual_risks",
    "action_labels",
    "recommended_crop",
    "avoid_regions",
    "camera_move",
    "subject_move",
    "light_direction",
    "shot_geometry",
    "body_pose",
    "hands",
    "gaze",
    "photographer",
)


def _acquire_gpu_process_lock() -> Any:
    """Prevent two model processes from silently contending for one Radeon GPU."""
    lock_path = Path(
        os.environ.get(
            "AI_PHOTOGRAPHER_GPU_LOCK", "/tmp/ai-photographer-agent-gpu.lock"
        )
    )
    lock_file = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        lock_file.close()
        raise RuntimeError(
            "Another AI Photographer Agent process already owns the GPU model. "
            "Reuse the running web server or stop it before starting the CLI."
        ) from exc
    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(str(os.getpid()))
    lock_file.flush()
    return lock_file


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip().replace("```json", "").replace("```", "").strip()
    cleaned = _strip_json_line_comments(cleaned)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise ValueError(f"Model did not return JSON: {cleaned[:300]}")
        candidate = re.sub(r",\s*([}\]])", r"\1", match.group(0))
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            # Qwen occasionally omits a comma between two line-separated
            # properties. Repair only that narrow, unambiguous shape; never
            # guess missing values or rewrite model content.
            repaired = re.sub(
                r'([}\]"])\s*\n(\s*"[^"\n]+"\s*:)',
                r"\1,\n\2",
                candidate,
            )
            try:
                parsed = json.loads(repaired)
            except json.JSONDecodeError as exc:
                # Normalize malformed or truncated model output so the scene
                # analyzer can perform its one bounded JSON-only retry.
                raise ValueError(
                    f"Model did not return JSON: {cleaned[:300]}"
                ) from exc
    if not isinstance(parsed, dict):
        raise ValueError("Model JSON response must be an object.")
    return parsed


def _strip_json_line_comments(text: str) -> str:
    """Remove Qwen's occasional // comments without touching quoted strings."""
    output: list[str] = []
    index = 0
    in_string = False
    escaped = False
    while index < len(text):
        character = text[index]
        if in_string:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            index += 1
            continue
        if character == '"':
            in_string = True
            output.append(character)
            index += 1
            continue
        if character == "/" and index + 1 < len(text) and text[index + 1] == "/":
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue
        output.append(character)
        index += 1
    return "".join(output)


def _extract_json(
    text: str, image_size: tuple[int, int] | None = None
) -> dict[str, Any]:
    parsed = _parse_json_object(text)
    pixel_coordinates = _uses_pixel_coordinates(parsed)
    result: dict[str, Any] = {
        field: str(parsed.get(field, "")).strip() for field in OUTPUT_FIELDS
    }
    normalized_people = _normalize_boxes(
        parsed.get("people_boxes"),
        limit=6,
        min_area=0.005,
        max_area=0.8,
        image_size=image_size if pixel_coordinates else None,
    )
    result["people_boxes"], person_index_map = _filter_primary_people(
        normalized_people
    )
    result["visible_props"] = _normalize_short_strings(
        parsed.get("visible_props"),
        limit=5,
        max_characters=24,
    )
    result["visual_risks"] = _normalize_short_strings(
        parsed.get("visual_risks"),
        limit=4,
        max_characters=48,
    )
    result["action_labels"] = _normalize_action_labels(
        parsed.get("action_labels"),
        people_count=len(normalized_people),
        person_index_map=person_index_map,
    )
    crop = _normalize_box(
        parsed.get("recommended_crop"),
        image_size=image_size if pixel_coordinates else None,
    )
    result["recommended_crop"] = crop or [50, 50, 950, 950]
    result["avoid_regions"] = _normalize_boxes(
        parsed.get("avoid_regions"),
        limit=3,
        max_area=0.35,
        image_size=image_size if pixel_coordinates else None,
    )
    for field, allowed, fallback in (
        ("camera_move", {"left", "right", "closer", "lower", "higher", "stay"}, "stay"),
        ("subject_move", {"left", "right", "forward", "back", "stay"}, "stay"),
        (
            "light_direction",
            {"left", "right", "front", "back", "soft", "unknown"},
            "unknown",
        ),
    ):
        value = str(parsed.get(field, fallback)).strip().lower()
        result[field] = value if value in allowed else fallback
    geometry = parsed.get("shot_geometry")
    geometry = geometry if isinstance(geometry, dict) else {}
    normalized_geometry: dict[str, str | float] = {}
    for field, allowed in (
        (
            "framing",
            {"full_body", "three_quarter", "half_body", "closeup", "unknown"},
        ),
        (
            "camera_height",
            {"ground", "knee", "waist", "chest", "eye", "above_eye", "unknown"},
        ),
        ("camera_tilt", {"up", "level", "down", "unknown"}),
    ):
        value = str(geometry.get(field, "unknown")).strip().lower()
        normalized_geometry[field] = value if value in allowed else "unknown"
    normalized_geometry["subject_frame_height_ratio"] = round(
        max(
            ((box[3] - box[1]) / 1000 for box in result["people_boxes"]),
            default=0.0,
        ),
        3,
    )
    result["shot_geometry"] = normalized_geometry
    result.update(normalize_pose_fields(parsed))
    return result


def _normalize_short_strings(
    value: Any,
    *,
    limit: int,
    max_characters: int,
) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value[:limit]:
        for candidate in re.split(r"[,，;；]", str(item)):
            text = candidate.strip()
            if (
                text
                and len(text) <= max_characters
                and text not in normalized
            ):
                normalized.append(text)
            if len(normalized) >= limit:
                return normalized
    return normalized


def _normalize_action_labels(
    value: Any,
    *,
    people_count: int,
    person_index_map: dict[int, int] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or people_count < 1:
        return []
    allowed_anchors = {"head", "body", "hands", "feet", "between"}
    vague_labels = {
        "adjust the body pose",
        "adjust the body angle",
        "move the hands",
        "adjust the hand pose",
        "change the head angle",
        "adjust the gaze",
        "keep a natural pose",
        "be natural",
    }
    labels: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value[:5]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if (
            not text
            or len(text) > 72
            or text in seen
            or text in vague_labels
        ):
            continue
        raw_indices = item.get("person_indices")
        if not isinstance(raw_indices, list):
            raw_index = item.get("person_index")
            raw_indices = [raw_index] if raw_index is not None else []
        indices: list[int] = []
        for raw_index in raw_indices[:2]:
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if not 0 <= index < people_count:
                continue
            mapped = (
                person_index_map.get(index)
                if person_index_map is not None
                else index
            )
            if mapped is not None and mapped not in indices:
                indices.append(mapped)
        if not indices:
            continue
        anchor = str(item.get("anchor", "body")).strip().lower()
        if anchor not in allowed_anchors:
            anchor = "body"
        lowered = text.lower()
        if any(word in lowered for word in ("look", "gaze", "eyes", "chin", "head")):
            anchor = "head"
        elif any(word in lowered for word in ("hand", "phone", "hold", "grip", "arm")):
            anchor = "hands" if len(indices) == 1 else "between"
        if anchor == "between" and len(indices) < 2:
            anchor = "hands"
        labels.append(
            {
                "person_indices": indices,
                "anchor": anchor,
                "text": text,
            }
        )
        seen.add(text)
    return labels


def _filter_primary_people(
    boxes: list[list[int]],
    *,
    min_relative_area: float = 0.18,
) -> tuple[list[list[int]], dict[int, int]]:
    """Remove tiny bystanders when one clearly dominant foreground person exists."""
    unique_boxes: list[list[int]] = []
    original_to_unique: dict[int, int] = {}
    for original_index, box in enumerate(boxes):
        duplicate_index = next(
            (
                unique_index
                for unique_index, existing in enumerate(unique_boxes)
                if _box_iou(box, existing) >= 0.9
            ),
            None,
        )
        if duplicate_index is None:
            duplicate_index = len(unique_boxes)
            unique_boxes.append(box)
        original_to_unique[original_index] = duplicate_index
    if len(unique_boxes) < 2:
        return unique_boxes, {
            original: 0 for original in original_to_unique
        }
    areas = [
        max(0, box[2] - box[0]) * max(0, box[3] - box[1])
        for box in unique_boxes
    ]
    largest = max(areas)
    keep_indices = [
        index
        for index, area in enumerate(areas)
        if not largest or area / largest >= min_relative_area
    ]
    filtered = [unique_boxes[index] for index in keep_indices]
    unique_to_filtered = {
        unique: remapped for remapped, unique in enumerate(keep_indices)
    }
    return filtered, {
        original: unique_to_filtered[unique]
        for original, unique in original_to_unique.items()
        if unique in unique_to_filtered
    }


def _box_iou(first: list[int], second: list[int]) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0, right - left) * max(0, bottom - top)
    first_area = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
    second_area = max(0, second[2] - second[0]) * max(
        0, second[3] - second[1]
    )
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


def _uses_pixel_coordinates(parsed: dict[str, Any]) -> bool:
    for field in ("people_boxes", "recommended_crop", "avoid_regions"):
        value = parsed.get(field)
        stack = list(value) if isinstance(value, list) else []
        while stack:
            item = stack.pop() if isinstance(stack, list) else None
            if isinstance(item, list):
                stack.extend(item)
            else:
                try:
                    if abs(float(item)) > 1000:
                        return True
                except (TypeError, ValueError):
                    pass
    return False


def _normalize_box(
    value: Any, image_size: tuple[int, int] | None = None
) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        numbers = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    if image_size:
        width, height = image_size
        numbers = [
            numbers[0] * 1000 / width,
            numbers[1] * 1000 / height,
            numbers[2] * 1000 / width,
            numbers[3] * 1000 / height,
        ]
    box = [max(0, min(1000, int(item))) for item in numbers]
    if box[2] - box[0] < 20 or box[3] - box[1] < 20:
        return None
    return box


def _normalize_boxes(
    value: Any,
    *,
    limit: int,
    max_area: float = 1.0,
    min_area: float = 0.0,
    image_size: tuple[int, int] | None = None,
) -> list[list[int]]:
    if not isinstance(value, list):
        return []
    boxes: list[list[int]] = []
    for item in value[:limit]:
        normalized = _normalize_box(item, image_size=image_size)
        area = (
            (normalized[2] - normalized[0])
            * (normalized[3] - normalized[1])
            / 1_000_000
            if normalized
            else 0.0
        )
        if normalized and min_area <= area <= max_area:
            boxes.append(normalized)
    return boxes


def _resolve_model_source(model_id: str) -> tuple[str, bool]:
    """Resolve a local checkpoint and never fall back to network model access."""
    explicit = os.environ.get("QWEN_MODEL_PATH")
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_dir():
            raise FileNotFoundError(f"QWEN_MODEL_PATH does not exist: {path}")
        return str(path), True

    ref = DEFAULT_LOCAL_CACHE / "refs" / "main"
    if ref.is_file():
        revision = ref.read_text(encoding="utf-8").strip()
        snapshot = DEFAULT_LOCAL_CACHE / "snapshots" / revision
        if snapshot.is_dir():
            return str(snapshot), True
    raise FileNotFoundError(
        f"Local checkpoint for {model_id} was not found. "
        "Core inference is offline-only; prepare the model cache before launch."
    )


class VisionAnalyzer:
    """Loads the 3B VLM once and analyzes local image files."""

    def __init__(
        self,
        model_id: str = MODEL_ID,
        cache_dir: str | None = DEFAULT_CACHE_DIR,
    ) -> None:
        if not torch.cuda.is_available():
            raise RuntimeError("No PyTorch GPU device is available.")
        if torch.version.hip is None:
            raise RuntimeError(
                "PyTorch is not using HIP. Keep the Radeon Cloud ROCm torch build."
            )

        self._gpu_process_lock = _acquire_gpu_process_lock()
        self.device = torch.device("cuda:0")
        load_started = time.perf_counter()
        model_source, offline = _resolve_model_source(model_id)
        self.model_source = model_source
        self.offline = offline
        self.processor = AutoProcessor.from_pretrained(
            model_source,
            cache_dir=cache_dir,
            local_files_only=offline,
        )
        self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            model_source,
            cache_dir=cache_dir,
            torch_dtype=torch.bfloat16,
            device_map="auto",
            low_cpu_mem_usage=True,
            local_files_only=offline,
        )
        self.model.eval()
        self.model_load_seconds = round(time.perf_counter() - load_started, 3)
        self.analysis_count = 0

    @torch.inference_mode()
    def analyze(
        self,
        image_path: str | Path,
        prompt: str = PHOTOGRAPHY_PROMPT,
        max_new_tokens: int = 896,
    ) -> dict[str, Any]:
        path = Path(image_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        try:
            with Image.open(path) as image:
                image_size = image.size
                image.verify()
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError(f"Unsupported or corrupt image: {path.name}") from exc

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": path.as_uri()},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        chat_text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = self.processor(
            text=[chat_text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        ).to(self.device)

        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(self.device)
        torch.cuda.synchronize(self.device)
        started = time.perf_counter()
        generated = self.model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
        )
        torch.cuda.synchronize(self.device)
        elapsed = time.perf_counter() - started

        trimmed = [
            output_ids[len(input_ids) :]
            for input_ids, output_ids in zip(inputs.input_ids, generated)
        ]
        response = self.processor.batch_decode(
            trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0]
        analysis = _extract_json(response, image_size=image_size)
        self.analysis_count += 1

        props = torch.cuda.get_device_properties(self.device)
        analysis["_metrics"] = {
            "inference_seconds": round(elapsed, 3),
            "gpu": torch.cuda.get_device_name(self.device),
            "total_vram_gib": round(props.total_memory / 1024**3, 2),
            "peak_allocated_vram_gib": round(
                torch.cuda.max_memory_allocated(self.device) / 1024**3, 3
            ),
            "peak_reserved_vram_gib": round(
                torch.cuda.max_memory_reserved(self.device) / 1024**3, 3
            ),
            "current_allocated_vram_gib": round(
                torch.cuda.memory_allocated(self.device) / 1024**3, 3
            ),
            "torch": torch.__version__,
            "hip": torch.version.hip,
            "model": MODEL_ID,
            "model_source": "local_cache" if self.offline else "huggingface",
            "model_load_seconds": self.model_load_seconds,
            "model_reused": self.analysis_count > 1,
        }
        return analysis

    @torch.inference_mode()
    def review_preview(
        self,
        reference_path: str | Path,
        preview_path: str | Path,
        user_request: str,
        plan: dict[str, Any],
        max_new_tokens: int = 192,
    ) -> dict[str, Any]:
        """Compare the generated concept preview against reference and direction."""
        reference = Path(reference_path).expanduser().resolve()
        preview = Path(preview_path).expanduser().resolve()
        if not reference.is_file() or not preview.is_file():
            raise FileNotFoundError("Reference and generated preview must both exist.")
        plan_excerpt = {
            "visual_intent": str(plan.get("visual_intent", ""))[:240],
            "lens_plan": plan.get("photographer_direction", {}).get("lens_plan"),
            "model_position": plan.get("model_direction", {}).get("position"),
            "model_hands": plan.get("model_direction", {}).get("hands"),
            "model_gaze": plan.get("model_direction", {}).get("gaze"),
            "model_action": plan.get("model_direction", {}).get("action"),
            "preserve_constraints": plan.get("preserve_constraints"),
        }
        prompt = f"""You are the visual critic for a professional photography preview.
Image 1 is the user's reference. Image 2 is an AI concept preview.
User request: {user_request}
Approved direction: {json.dumps(plan_excerpt, ensure_ascii=False)}

Judge the preview as a concept for pose, framing, lighting, subject type, and location.
Do not demand pixel-identical identity. Reject obvious anatomy failures, changed scene
semantics, missing primary subjects, or direction contradictions.
Keep every string under 25 words.

Return only valid JSON:
{{
  "subject_consistency": "",
  "environment_consistency": "",
  "pose_and_action_alignment": "",
  "composition_and_lighting_alignment": "",
  "artifact_check": "",
  "issues": [],
  "verdict": "pass or needs_review"
}}"""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Image 1 — reference"},
                    {
                        "type": "image",
                        "image": reference.as_uri(),
                        "min_pixels": 128 * 28 * 28,
                        "max_pixels": 384 * 28 * 28,
                    },
                    {"type": "text", "text": "Image 2 — generated concept preview"},
                    {
                        "type": "image",
                        "image": preview.as_uri(),
                        "min_pixels": 128 * 28 * 28,
                        "max_pixels": 384 * 28 * 28,
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        chat_text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = self.processor(
            text=[chat_text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        ).to(self.device)
        torch.cuda.reset_peak_memory_stats(self.device)
        torch.cuda.synchronize(self.device)
        started = time.perf_counter()
        generated = self.model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
        )
        torch.cuda.synchronize(self.device)
        elapsed = time.perf_counter() - started
        trimmed = [
            output_ids[len(input_ids) :]
            for input_ids, output_ids in zip(inputs.input_ids, generated)
        ]
        response = self.processor.batch_decode(
            trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0]
        result = _parse_json_object(response)
        issues = result.get("issues", [])
        if isinstance(issues, str):
            issues = [issues] if issues.strip() else []
        elif not isinstance(issues, list):
            issues = [str(issues)]
        verdict = str(result.get("verdict", "needs_review")).strip().lower()
        if verdict not in {"pass", "needs_review"}:
            verdict = "needs_review"
            issues.append("The visual critic returned an invalid verdict.")
        return {
            "subject_consistency": str(result.get("subject_consistency", "")).strip(),
            "environment_consistency": str(
                result.get("environment_consistency", "")
            ).strip(),
            "pose_and_action_alignment": str(
                result.get("pose_and_action_alignment", "")
            ).strip(),
            "composition_and_lighting_alignment": str(
                result.get("composition_and_lighting_alignment", "")
            ).strip(),
            "artifact_check": str(result.get("artifact_check", "")).strip(),
            "issues": [str(issue).strip() for issue in issues if str(issue).strip()],
            "verdict": verdict,
            "review_seconds": round(elapsed, 3),
            "review_model": MODEL_ID,
        }


_SHARED_ANALYZER: VisionAnalyzer | None = None
_SHARED_LOCK = Lock()


def get_shared_vision_analyzer() -> VisionAnalyzer:
    """Load the 3B checkpoint once per process and reuse it across UI requests."""
    global _SHARED_ANALYZER
    if _SHARED_ANALYZER is None:
        with _SHARED_LOCK:
            if _SHARED_ANALYZER is None:
                _SHARED_ANALYZER = VisionAnalyzer()
    return _SHARED_ANALYZER
