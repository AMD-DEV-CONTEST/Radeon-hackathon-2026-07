"""End-to-end orchestration for the private AI Photographer Agent."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from src.agent.critic import PlanCritic
from src.agent.intent import IntentRouter
from src.agent.permissions import PermissionPolicy
from src.agent.planner import PhotographyPlanner
from src.agent.tool_registry import ToolRegistry
from src.tools.composition_checker import check_composition
from src.tools.scene_analyzer import SceneAnalyzer
from src.vision.pose_analyzer import PoseAnalyzer


class PhotographerAgent:
    """Coordinates tools, planning and one bounded critic-refinement pass."""

    def __init__(
        self,
        analyzer: SceneAnalyzer | None = None,
        router: IntentRouter | None = None,
        planner: PhotographyPlanner | None = None,
        critic: PlanCritic | None = None,
        pose_analyzer: PoseAnalyzer | None = None,
        policy: PermissionPolicy | None = None,
        tools: ToolRegistry | None = None,
    ) -> None:
        self.analyzer = analyzer or SceneAnalyzer()
        self.router = router or IntentRouter()
        self.planner = planner or PhotographyPlanner()
        self.critic = critic or PlanCritic()
        self.pose_analyzer = pose_analyzer or PoseAnalyzer()
        self.tools = tools or ToolRegistry(policy=policy)

    def run(
        self,
        image: str | Path,
        request: str,
        *,
        generate_overlay: bool = False,
        overlay_path: str | Path | None = None,
        generate_preview: bool = False,
        preview_path: str | Path | None = None,
        review_preview: bool = True,
        local_person_geometry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if generate_preview:
            raise ValueError(
                "Concept-image generation is disabled. "
                "Use the deterministic AI photography execution card."
            )
        request = request.strip()
        if not request:
            raise ValueError("The photography request cannot be empty.")
        image_path = Path(image).expanduser().resolve()
        if not image_path.is_file():
            raise FileNotFoundError(image_path)

        trace: list[dict[str, Any]] = []
        self.tools.begin_run()
        total_started = time.perf_counter()

        started = time.perf_counter()
        intent = self.tools.invoke(
            "intent_router",
            lambda: self.router.route(request),
            input_summary={"request_characters": len(request)},
            output_summary=lambda value: {"task_type": value["task_type"]},
        )
        trace.append(self._trace("intent_router", started, intent["task_type"]))

        started = time.perf_counter()
        raw_analysis = self.tools.invoke(
            "vision_analyzer",
            lambda: self.analyzer.run(image_path, request),
            input_summary={
                "image_filename": image_path.name,
                "request_characters": len(request),
            },
            output_summary=lambda value: {
                "people": len(value.get("people_boxes") or []),
                "action_labels": len(value.get("action_labels") or []),
                "grounded": all(
                    value.get(field)
                    for field in self.critic.REQUIRED_ANALYSIS_FIELDS
                ),
            },
        )
        analysis = dict(raw_analysis)
        if isinstance(local_person_geometry, dict):
            analysis["_local_person_geometry"] = dict(local_person_geometry)
        metrics = analysis.pop("_metrics", {})
        trace.append(self._trace("vision_analyzer", started, "grounded JSON"))
        required_fields = self.critic.REQUIRED_ANALYSIS_FIELDS
        missing_visual = [field for field in required_fields if not analysis.get(field)]
        if missing_visual:
            started = time.perf_counter()
            retry_request = (
                request
                + "\nThe previous visual pass omitted these required fields: "
                + ", ".join(missing_visual)
                + ". Re-analyze the image and return every required field with "
                + "specific, non-empty visual evidence."
            )
            retry_raw = self.tools.invoke(
                "vision_analyzer",
                lambda: self.analyzer.run(image_path, retry_request),
                input_summary={
                    "image_filename": image_path.name,
                    "retry_for_missing_fields": missing_visual,
                },
                output_summary=lambda value: {
                    "recovered_fields": [
                        field for field in missing_visual if value.get(field)
                    ]
                },
            )
            retry_analysis = dict(retry_raw)
            retry_metrics = retry_analysis.pop("_metrics", {})
            for field in required_fields:
                if retry_analysis.get(field):
                    analysis[field] = retry_analysis[field]
            metrics = dict(metrics)
            metrics["vision_attempts"] = 2
            metrics["vision_retry_seconds"] = retry_metrics.get(
                "inference_seconds"
            )
            metrics["vision_inference_seconds_total"] = round(
                float(metrics.get("inference_seconds", 0))
                + float(retry_metrics.get("inference_seconds", 0)),
                3,
            )
            metrics["model_reused"] = retry_metrics.get(
                "model_reused", metrics.get("model_reused")
            )
            remaining = [
                field for field in required_fields if not analysis.get(field)
            ]
            trace.append(
                self._trace(
                    "vision_missing_field_retry",
                    started,
                    "repaired" if not remaining else "still_missing",
                )
            )
        else:
            metrics = dict(metrics)
            metrics["vision_attempts"] = 1

        started = time.perf_counter()
        composition = self.tools.invoke(
            "composition_checker",
            lambda: check_composition(analysis),
            input_summary={
                "analysis_fields": list(self.critic.REQUIRED_ANALYSIS_FIELDS)
            },
            output_summary=lambda value: {
                "status": value["status"],
                "actionability_score": value["actionability_score"],
            },
        )
        trace.append(self._trace("composition_checker", started, composition["status"]))

        started = time.perf_counter()
        plan = self.tools.invoke(
            "photography_planner",
            lambda: self.planner.plan(analysis, request, intent),
            input_summary={"task_type": intent["task_type"]},
            output_summary=lambda value: {
                "schema_fields": len(value),
                "sequence_steps": len(value.get("shooting_sequence") or []),
            },
        )
        trace.append(self._trace("photography_planner", started, "field_guidance"))

        started = time.perf_counter()
        review = self.tools.invoke(
            "plan_critic",
            lambda: self.critic.review(analysis, plan),
            input_summary={"schema": "photography_field_plan"},
            output_summary=lambda value: {
                "status": value["status"],
                "issues": len(value["issues"]),
            },
        )
        trace.append(self._trace("plan_critic", started, review["status"]))

        if review["status"] != "pass":
            started = time.perf_counter()
            plan = self.tools.invoke(
                "plan_refiner",
                lambda: self.planner.refine(
                    plan,
                    review["issues"],
                    analysis=analysis,
                    user_request=request,
                    intent=intent,
                ),
                input_summary={"issues": len(review["issues"])},
                output_summary=lambda value: {"schema_fields": len(value)},
            )
            review = self.tools.invoke(
                "plan_critic",
                lambda: self.critic.review(analysis, plan),
                input_summary={
                    "schema": "photography_field_plan",
                    "after_refinement": True,
                },
                output_summary=lambda value: {
                    "status": value["status"],
                    "issues": len(value["issues"]),
                },
            )
            trace.append(self._trace("bounded_refinement", started, review["status"]))
        started = time.perf_counter()
        pose_json = self.tools.invoke(
            "pose_analyzer",
            lambda: self.pose_analyzer.build(analysis, plan),
            input_summary={
                "people": len(analysis.get("people_boxes") or []),
                "vlm_pose_fields_present": all(
                    isinstance(analysis.get(field), dict)
                    for field in ("body_pose", "hands", "gaze", "photographer")
                ),
            },
            output_summary=lambda value: {
                "source": value["source"],
                "sections": ["body_pose", "hands", "gaze", "photographer"],
            },
        )
        trace.append(self._trace("pose_analyzer", started, pose_json["source"]))

        if generate_overlay and review["status"] != "pass":
            raise RuntimeError(
                "Plan Critic blocked the photography execution card: "
                + "; ".join(review["issues"])
            )

        pose_card: dict[str, Any] = {"status": "not_requested"}
        if generate_overlay:
            if overlay_path is None:
                raise ValueError(
                    "overlay_path is required when generate_overlay=True."
                )
            from src.tools.pose_card_renderer import render_pose_card

            started = time.perf_counter()
            pose_card = self.tools.invoke(
                "pose_card_renderer",
                lambda: render_pose_card(
                    image_path, analysis, plan, pose_json, overlay_path
                ),
                input_summary={
                    "image_filename": image_path.name,
                    "people": len(analysis.get("people_boxes") or []),
                    "output_scope": "temporary_local_png",
                    "renderer": "deterministic_pil",
                },
                output_summary=lambda value: {
                    "status": value["status"],
                    "render_mode": value["render_mode"],
                    "people_matched": value["person_outline"].get(
                        "people_matched", 0
                    ),
                    "image_generation_model_used": value[
                        "image_generation_model_used"
                    ],
                },
            )
            trace.append(
                self._trace(
                    "pose_card_renderer",
                    started,
                    f"{pose_card['width']}x{pose_card['height']}",
                )
            )

        preview: dict[str, Any] = {
            "status": "disabled",
            "reason": (
                "The product deterministically renders a photography execution "
                "card and does not generate a replacement concept image."
            ),
        }
        visual_review: dict[str, Any] = {
            "status": "not_applicable",
            "reason": "No generated image is produced.",
        }

        metrics = dict(metrics)
        metrics["total_agent_seconds"] = round(time.perf_counter() - total_started, 3)
        return {
            "schema_version": "3.0",
            "request": request,
            "image": {"filename": image_path.name},
            "intent": intent,
            "analysis": analysis,
            "composition_check": composition,
            "shooting_plan": plan,
            "critic": review,
            "pose_json": pose_json,
            "pose_card": pose_card,
            "preview": preview,
            "visual_review": visual_review,
            "agent_trace": trace,
            "tool_manifest": self.tools.manifest(),
            "tool_calls": list(self.tools.calls),
            "permission_audit": list(self.tools.permission_audit),
            "privacy": {
                "core_inference": "local_amd_rocm",
                "external_ai_api": False,
                "external_network_allowed": False,
                "persistent_memory": False,
                "source_pixels_in_visual_result": True,
                "source_reference_included_for_user": True,
                "policy": self.tools.policy.public_summary(),
            },
            "metrics": metrics,
        }

    @staticmethod
    def _trace(node: str, started: float, result: str) -> dict[str, Any]:
        return {
            "node": node,
            "status": "completed",
            "result": result,
            "seconds": round(time.perf_counter() - started, 3),
        }
