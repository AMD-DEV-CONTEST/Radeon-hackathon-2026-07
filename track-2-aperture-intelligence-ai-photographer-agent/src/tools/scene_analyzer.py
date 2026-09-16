"""Stable tool wrapper around the VLM vision analyzer."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _labels_use_visible_props(
    labels: list[dict[str, Any]],
    visible_props: list[str],
) -> bool:
    props = " ".join(visible_props).lower()
    phone_visible = any(word in props for word in ("phone", "smartphone", "mobile"))
    if not phone_visible:
        return True
    hand_labels = [
        str(label.get("text", "")).lower()
        for label in labels
        if label.get("anchor") == "hands"
    ]
    return bool(hand_labels) and any(
        any(word in text for word in ("phone", "smartphone", "mobile"))
        for text in hand_labels
    )


class SceneAnalyzer:
    def __init__(self, vision: Any | None = None) -> None:
        if vision is None:
            # Keep heavyweight ROCm/Transformers imports out of unit-test discovery.
            from src.vision.vlm_inference import get_shared_vision_analyzer

            vision = get_shared_vision_analyzer()
        self._vision = vision

    def run(
        self, image_path: str | Path, user_request: str | None = None
    ) -> dict[str, Any]:
        if not user_request:
            return self._vision.analyze(image_path)
        from src.vision.prompts import PHOTOGRAPHY_PROMPT

        prompt = (
            PHOTOGRAPHY_PROMPT
            + f"\nThe user's goal is: {user_request}\n"
            + "Write all user-facing scene, action, pose, gaze, and camera "
            + "direction fields in concise, natural English."
        )
        try:
            result = self._vision.analyze(image_path, prompt=prompt)
        except ValueError as exc:
            if "did not return JSON" not in str(exc):
                raise
            repair_prompt = (
                prompt
                + "\nThe previous response was truncated or malformed. Return one "
                + "complete JSON object. Keep every user-facing text field concise, "
                + "use no more than 18 words per text field, "
                + "visual_risks to exactly 2 items, action_labels to "
                + "2-4 items, and do not add prose before or after JSON."
            )
            try:
                result = self._vision.analyze(
                    image_path,
                    prompt=repair_prompt,
                    max_new_tokens=1280,
                )
            except TypeError:
                result = self._vision.analyze(image_path, prompt=repair_prompt)
            retry_metrics = dict(result.get("_metrics", {}))
            retry_metrics["json_parse_retry"] = True
            result["_metrics"] = retry_metrics
        if not result.get("people_boxes"):
            grounding_prompt = """Locate only the main foreground person or people
that the photographer is intentionally photographing. Ignore distant bystanders.
Coordinates use 0-1000 relative to the image. Boxes must be tight around each
person and must not cover the whole image. Return only JSON:
{
  "people_boxes": [[x1,y1,x2,y2]],
  "visible_props": ["phone, bag, chair, railing, or other handled object"],
  "action_labels": [
    {
      "person_indices": [0],
      "anchor": "head, body, hands, feet, or between",
      "text": "a concise action in no more than eight English words"
    }
  ],
  "recommended_crop": [x1,y1,x2,y2],
  "avoid_regions": [[x1,y1,x2,y2]],
  "camera_move": "left, right, closer, lower, higher, or stay",
  "subject_move": "left, right, forward, back, or stay",
  "light_direction": "left, right, front, back, soft, or unknown"
}"""
            try:
                geometry = self._vision.analyze(
                    image_path,
                    prompt=grounding_prompt,
                    max_new_tokens=256,
                )
            except TypeError:
                geometry = self._vision.analyze(
                    image_path, prompt=grounding_prompt
                )
            for field in (
                "people_boxes",
                "visible_props",
                "action_labels",
                "recommended_crop",
                "avoid_regions",
                "camera_move",
                "subject_move",
                "light_direction",
            ):
                if geometry.get(field):
                    result[field] = geometry[field]
            metrics = dict(result.get("_metrics", {}))
            grounding_metrics = geometry.get("_metrics", {})
            metrics["grounding_retry"] = True
            metrics["grounding_seconds"] = grounding_metrics.get(
                "inference_seconds"
            )
            metrics["model_reused"] = grounding_metrics.get(
                "model_reused", metrics.get("model_reused")
            )
            result["_metrics"] = metrics
        if result.get("people_boxes") and len(result.get("action_labels") or []) < 2:
            label_prompt = f"""Generate only executable subject-action labels for this photo.
User goal: {user_request}
Primary person boxes, in fixed order: {result["people_boxes"]}
Subject evidence: {result.get("subject", "")}
Visible props: {result.get("visible_props", [])}
Composition evidence: {result.get("composition", "")}
Current recommendation: {result.get("recommendation", "")}

Hard rules:
1. Return only JSON with the unchanged people_boxes and 2 to 4 action_labels.
2. Every label must tell the subject exactly what to do in no more than eight English words.
3. If the user needs body, hand, or gaze direction, label each visible part separately
   with anchors body, hands, and head.
4. Never direct feet or legs that are cropped out.
5. Use recognized props. If a phone or smartphone is visible, the hands label must
   say "phone" and must not say "let both hands hang."
6. Reject vague labels such as "adjust the pose," "move the hands," or "change the head angle."
7. Use two person indices and anchor "between" for a shared group action.

Good examples:
- phone portrait: "Lower shoulders and turn slightly", "Lower the phone", "Look past the phone"
- parent and child: "Adult turns toward child", "Child looks up", "Hold hands naturally"
{{
  "people_boxes": {result["people_boxes"]},
  "action_labels": [
    {{
      "person_indices": [0],
      "anchor": "head, body, hands, feet, or between",
      "text": "concise English action"
    }}
  ]
}}"""
            try:
                label_result = self._vision.analyze(
                    image_path,
                    prompt=label_prompt,
                    max_new_tokens=256,
                )
            except TypeError:
                label_result = self._vision.analyze(
                    image_path,
                    prompt=label_prompt,
                )
            if label_result.get("action_labels"):
                result["action_labels"] = label_result["action_labels"]
            metrics = dict(result.get("_metrics", {}))
            label_metrics = label_result.get("_metrics", {})
            metrics["action_label_retry"] = True
            metrics["action_label_retry_seconds"] = label_metrics.get(
                "inference_seconds"
            )
            metrics["action_labels_generated"] = len(
                result.get("action_labels") or []
            )
            metrics["model_reused"] = label_metrics.get(
                "model_reused", metrics.get("model_reused")
            )
            if not _labels_use_visible_props(
                result.get("action_labels") or [],
                result.get("visible_props") or [],
            ):
                correction_prompt = f"""The previous action labels conflict with a visible prop. Rewrite only the labels.
User goal: {user_request}
Primary person boxes: {result["people_boxes"]}
Visible props: {result.get("visible_props", [])}
Incorrect labels: {result.get("action_labels", [])}

Return only JSON with 2 to 4 specific English actions. If a phone is visible,
the hands label must explicitly say "phone," for example "Lower the phone."
Do not say "let both hands hang." Body and gaze labels must also state a direction.
{{
  "people_boxes": {result["people_boxes"]},
  "visible_props": {result.get("visible_props", [])},
  "action_labels": [
    {{
      "person_indices": [0],
      "anchor": "body, hands, or head",
      "text": "specific English action"
    }}
  ]
}}"""
                correction_error: str | None = None
                try:
                    try:
                        corrected = self._vision.analyze(
                            image_path,
                            prompt=correction_prompt,
                            max_new_tokens=192,
                        )
                    except TypeError:
                        corrected = self._vision.analyze(
                            image_path,
                            prompt=correction_prompt,
                        )
                except Exception as exc:
                    corrected = {}
                    correction_error = f"{type(exc).__name__}: {exc}"
                corrected_labels = corrected.get("action_labels") or []
                if _labels_use_visible_props(
                    corrected_labels,
                    result.get("visible_props") or [],
                ):
                    result["action_labels"] = corrected_labels
                else:
                    result["action_labels"] = [
                        label
                        for label in result.get("action_labels") or []
                        if label.get("anchor") != "hands"
                    ]
                correction_metrics = corrected.get("_metrics", {})
                metrics["action_label_correction"] = True
                if correction_error:
                    metrics["action_label_correction_error"] = correction_error
                metrics["action_label_correction_seconds"] = (
                    correction_metrics.get("inference_seconds")
                )
                metrics["action_label_prop_consistent"] = (
                    _labels_use_visible_props(
                        result.get("action_labels") or [],
                        result.get("visible_props") or [],
                    )
                )
                metrics["model_reused"] = correction_metrics.get(
                    "model_reused", metrics.get("model_reused")
                )
            result["_metrics"] = metrics
        from src.vision.pose_analyzer import POSE_SCHEMA, pose_schema_complete

        if not pose_schema_complete(result):
            pose_prompt = f"""Return only the action JSON required by an on-set photography guidance card.
User goal: {user_request}
Scene: {result.get("scene", "")}
Subject: {result.get("subject", "")}
Subject-environment relationship: {result.get("relationship", "")}
Composition: {result.get("composition", "")}
Visible props: {result.get("visible_props", [])}

Return only the JSON structure below. Every value must be concise, specific,
executable English. Do not leave fields empty and do not generate an image:
{{
  "body_pose": {{
    "body_rotation": "where the body turns and by roughly how much",
    "shoulder": "a specific shoulder action",
    "head_direction": "where the head turns"
  }},
  "hands": {{
    "object": "the real visible handheld prop, or none",
    "position": "exactly how both hands hold or rest"
  }},
  "gaze": {{
    "direction": "exactly where the eyes look",
    "expression": "a specific expression cue"
  }},
  "photographer": {{
    "distance": "photographer-to-subject distance in meters",
    "angle": "level, upward, or downward according to perspective",
    "height": "camera height relative to the eyes or body",
    "background": "what to preserve or avoid in the background",
    "purpose": "the subject-environment relationship to preserve"
  }}
}}
Do not estimate a left, right, front, or rear photographer position. distance must use meters;
angle must say level, upward, or downward; height must be relative to the eyes or body,
such as "slightly above eye level," never an arbitrary absolute height. Preserve visible props in hand guidance."""
            pose_error: str | None = None
            try:
                try:
                    pose_result = self._vision.analyze(
                        image_path,
                        prompt=pose_prompt,
                        max_new_tokens=384,
                    )
                except TypeError:
                    pose_result = self._vision.analyze(
                        image_path,
                        prompt=pose_prompt,
                    )
            except Exception as exc:
                pose_result = {}
                pose_error = f"{type(exc).__name__}: {exc}"
            for section in POSE_SCHEMA:
                if isinstance(pose_result.get(section), dict):
                    result[section] = pose_result[section]
            metrics = dict(result.get("_metrics", {}))
            pose_metrics = pose_result.get("_metrics", {})
            metrics["pose_schema_retry"] = True
            metrics["pose_schema_retry_seconds"] = pose_metrics.get(
                "inference_seconds"
            )
            metrics["pose_schema_complete"] = pose_schema_complete(result)
            metrics["model_reused"] = pose_metrics.get(
                "model_reused", metrics.get("model_reused")
            )
            if pose_error:
                metrics["pose_schema_error"] = pose_error
            result["_metrics"] = metrics
        return result

    def review_preview(
        self,
        reference_path: str | Path,
        preview_path: str | Path,
        user_request: str,
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        return self._vision.review_preview(
            reference_path, preview_path, user_request, plan
        )
