"""Bounded, auditable XiangLens agent graph."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ValidationError

from xianglens.agent.state import XiangLensState
from xianglens.inference.llama_client import (
    ModelClient,
    ModelRequestError,
    parse_json_object,
)
from xianglens.schemas import (
    CandidateComparison,
    FollowUpDraft,
    StructuredReportDraft,
    VisualObservation,
)
from xianglens.storage.knowledge_store import KnowledgeStore
from xianglens.storage.sqlite_store import SQLiteStore
from xianglens.tools.image_tools import ImageInspector
from xianglens.tools.private_lens import PrivateLensTool


@dataclass(slots=True)
class GraphServices:
    model: ModelClient
    knowledge: KnowledgeStore
    database: SQLiteStore
    image_inspector: ImageInspector
    private_lens: PrivateLensTool | None = None
    rag_top_k: int = 4


SENSITIVE_PATTERNS = (
    r"\binfer\s+(?:my|their|his|her)?\s*personality\b",
    r"\bguess\s+(?:my|their|his|her)?\s*(?:ethnicity|race|religion|politics)\b",
    r"\b(?:criminality|sexual orientation|medical diagnosis|intelligence score)\b",
    r"\bpredict\s+(?:my|their|his|her)?\s*(?:future|destiny|wealth|lifespan)\b",
)

EXPLICIT_MEMORY_PATTERNS = (
    r"\bremember\b",
    r"\bsave (?:this|that|it|my) (?:as |to )?(?:a )?(?:preference|memory)\b",
    r"\bkeep (?:this|that|it) in mind\b",
    r"\bi prefer\b",
    r"\bi(?:'d| would) prefer\b",
    r"\bi (?:like|love|favor)\b",
    r"\bi (?:want|need) to avoid\b",
    r"\bi(?:'m| am) (?:worried|concerned) about\b",
    r"\bmy\s+[a-z0-9 -]{1,50}\s+(?:is|are)\b",
    r"\bdo not treat\b",
    r"\bi (?:always|never)\b",
)

SENSITIVE_MEMORY_TERMS = (
    "medical",
    "disease",
    "diagnosis",
    "religion",
    "politics",
    "sexual orientation",
    "ethnicity",
    "criminal",
    "pregnancy",
)

ModelSchema = TypeVar("ModelSchema", bound=BaseModel)

COMPARISON_SCORE_FIELDS = (
    ("crop_resilience", "crop resilience"),
    ("small_size_clarity", "small-size clarity"),
    ("privacy_safety", "privacy safety"),
    ("intent_alignment", "intent alignment"),
    ("contextual_ambiguity", "contextual ambiguity"),
)
COMPARISON_DECISION_RULE = (
    "Privacy safety takes precedence. Rights or provenance uncertainty is reflected in "
    "goal-relative intent alignment and contextual ambiguity, never as a legal ruling. When "
    "privacy is equal, prefer the strongest combined intent alignment, crop resilience, and "
    "small-size clarity with lower contextual ambiguity."
)


def _normalize_candidate_comparison(
    value: dict[str, Any],
    score_defaults: dict[str, dict[str, int]] | None = None,
) -> dict[str, Any]:
    """Validate model scores and conservatively fill fields the model omitted."""
    candidates = value.get("candidates")
    if not isinstance(candidates, list):
        return value
    normalized = {
        **value,
        "candidates": [],
        "decision_rule": COMPARISON_DECISION_RULE,
    }
    for raw_candidate in candidates:
        if not isinstance(raw_candidate, dict):
            normalized["candidates"].append(raw_candidate)
            continue
        candidate = dict(raw_candidate)
        image_id = str(candidate.get("image_id", ""))
        defaults = (score_defaults or {}).get(image_id, {})
        fallback_labels = []
        for field, label in COMPARISON_SCORE_FIELDS:
            raw_score = candidate.get(field)
            if (
                isinstance(raw_score, int)
                and not isinstance(raw_score, bool)
                and 0 <= raw_score <= 5
            ):
                continue
            candidate[field] = defaults.get(field, 3)
            fallback_labels.append(label)
        rationale = str(candidate.get("rationale", "")).strip()
        if not rationale:
            score_summary = ", ".join(
                f"{label} {candidate[field]}/5" for field, label in COMPARISON_SCORE_FIELDS
            )
            candidate["rationale"] = (
                f"Code-generated summary of the validated rubric scores: {score_summary}."
            )
        elif fallback_labels:
            fallback_note = (
                " Application fallback supplied conservative scores for omitted fields: "
                f"{', '.join(fallback_labels)}."
            )
            candidate["rationale"] = f"{rationale[: 1200 - len(fallback_note)]}{fallback_note}"
        normalized["candidates"].append(candidate)
    if any(
        "Application fallback supplied" in str(candidate.get("rationale", ""))
        for candidate in normalized["candidates"]
        if isinstance(candidate, dict)
    ):
        normalized["caveat"] = (
            "The model omitted one or more rubric scores; XiangLens supplied conservative, "
            "evidence-aware defaults and still applied the fixed decision rule."
        )
    complete_candidates = [
        candidate
        for candidate in normalized["candidates"]
        if isinstance(candidate, dict)
        and isinstance(candidate.get("image_id"), str)
        and all(isinstance(candidate.get(field), int) for field, _ in COMPARISON_SCORE_FIELDS)
    ]
    if len(complete_candidates) == len(normalized["candidates"]) and complete_candidates:
        normalized["recommended_image_id"] = max(
            enumerate(complete_candidates),
            key=lambda indexed: (
                indexed[1]["privacy_safety"],
                indexed[1]["intent_alignment"]
                + indexed[1]["crop_resilience"]
                + indexed[1]["small_size_clarity"]
                - indexed[1]["contextual_ambiguity"],
                indexed[1]["intent_alignment"],
                indexed[1]["crop_resilience"],
                indexed[1]["small_size_clarity"],
                -indexed[1]["contextual_ambiguity"],
                -indexed[0],
            ),
        )[1]["image_id"]
    return normalized


def _comparison_score_defaults(
    image_ids: list[str],
    privacy_findings: list[dict[str, Any]],
    rights_findings: list[dict[str, Any]],
    recalled_memories: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    privacy_risk_ids = {
        str(finding.get("image_id")) for finding in privacy_findings if finding.get("image_id")
    }
    rights_risk_ids = {
        str(finding.get("image_id")) for finding in rights_findings if finding.get("image_id")
    }
    rights_are_a_goal = any(
        any(
            term in str(memory.get("text", "")).lower()
            for term in ("copyright", "trademark", "license", "provenance", "usage rights")
        )
        for memory in recalled_memories
    )
    return {
        image_id: {
            "crop_resilience": 3,
            "small_size_clarity": 3,
            "privacy_safety": 2 if image_id in privacy_risk_ids else 4,
            "intent_alignment": (2 if rights_are_a_goal and image_id in rights_risk_ids else 3),
            "contextual_ambiguity": 4 if image_id in rights_risk_ids else 3,
        }
        for image_id in image_ids
    }


def _trace(
    state: XiangLensState,
    *,
    node: str,
    tool: str,
    started: float,
    summary: str,
    status: str = "completed",
) -> list[dict[str, Any]]:
    return [
        *state.get("tool_trace", []),
        {
            "node": node,
            "tool": tool,
            "status": status,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "summary": summary,
        },
    ]


def _explicit_memory_candidate(message: str) -> bool:
    lowered = message.lower()
    return any(re.search(pattern, lowered) for pattern in EXPLICIT_MEMORY_PATTERNS) and not any(
        term in lowered for term in SENSITIVE_MEMORY_TERMS
    )


def _deterministic_memory_proposal(message: str) -> dict[str, str] | None:
    """Turn an explicit user statement into a consent request without another model call."""
    if not _explicit_memory_candidate(message):
        return None
    text = " ".join(message.split()).strip()
    text = re.sub(
        r"^(?:please\s+)?remember(?:\s+that)?\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"^(?:please\s+)?keep\s+(?:this|that|it)\s+in\s+mind(?:\s*[:,-])?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = text[:500].strip(" ,:;-")
    if len(text) < 3:
        return None
    lowered = text.lower()
    memory_type = "preference"
    if any(term in lowered for term in ("correction", "actually", "instead of")):
        memory_type = "correction"
    elif any(term in lowered for term in ("my goal", "i need", "i want to achieve")):
        memory_type = "goal"
    elif any(term in lowered for term in ("worked well", "did not work", "outcome")):
        memory_type = "outcome"
    return {
        "text": text,
        "memory_type": memory_type,
        "reason": "The user explicitly stated this reusable preference or constraint.",
    }


def _render_bullets(items: list[str], fallback: str) -> str:
    values = [item.strip() for item in items if item.strip()]
    return "\n".join(f"- {item}" for item in values) if values else f"- {fallback}"


def _image_label(image_id: str, image_labels: dict[str, str]) -> str:
    label = image_labels.get(image_id, image_id)
    return label.replace("`", "'").replace("\n", " ").replace("\r", " ")


def _replace_internal_image_ids(markdown: str, image_labels: dict[str, str]) -> str:
    rendered = markdown
    placeholders: dict[str, str] = {}
    for index, image_id in enumerate(image_labels):
        placeholder = f"XIANG_IMAGE_LABEL_{index}_PLACEHOLDER"
        rendered = rendered.replace(image_id, placeholder)
        placeholders[placeholder] = _image_label(image_id, image_labels)
    for placeholder, label in placeholders.items():
        rendered = rendered.replace(placeholder, label)
    return rendered


def _render_report(
    report: StructuredReportDraft,
    evidence: list[dict[str, Any]],
    comparison: dict[str, Any] | None,
    proposal: dict[str, Any] | None,
    private_lens_readings: list[dict[str, Any]],
    rights_findings: list[dict[str, Any]],
    image_labels: dict[str, str] | None = None,
) -> str:
    image_labels = image_labels or {}

    def clean(value: Any) -> str:
        return _replace_internal_image_ids(str(value), image_labels)

    known_cards = {card["card_id"]: card for card in evidence}
    cited = [known_cards[card_id] for card_id in report.cited_card_ids if card_id in known_cards]
    if not cited:
        cited = evidence

    sections = [
        "# XiangLens Review",
        clean(report.summary.strip()),
        "## Observed",
        _render_bullets(
            [clean(item) for item in report.observed],
            "No additional visible fact was asserted.",
        ),
    ]
    if private_lens_readings:
        sections.append("## Private Lens Tool (Opt-In)")
        for reading in private_lens_readings:
            references = ", ".join(reading.get("technique_references", [])) or "No technique ID"
            associations = [clean(item) for item in reading.get("symbolic_associations", [])]
            sections.append(
                f"- `{_image_label(reading['image_id'], image_labels)}` — {references}. "
                + (
                    " ".join(associations)
                    if associations
                    else "No safe symbolic association was emitted."
                )
            )
        sections.append(
            "Private course associations are symbolic context, not factual, medical, "
            "personality, financial, relationship, or predictive claims."
        )
    if comparison:
        comparison_lines = []
        for candidate in comparison["candidates"]:
            comparison_lines.append(
                f"- `{_image_label(candidate['image_id'], image_labels)}` — "
                f"crop {candidate['crop_resilience']}/5, "
                f"small-size clarity {candidate['small_size_clarity']}/5, privacy "
                f"{candidate['privacy_safety']}/5, intent {candidate['intent_alignment']}/5, "
                f"ambiguity {candidate['contextual_ambiguity']}/5. "
                f"{clean(candidate['rationale'])}"
            )
        sections.extend(
            [
                "## Comparison",
                "Recommended image: "
                f"`{_image_label(comparison['recommended_image_id'], image_labels)}`.",
                *comparison_lines,
                f"Decision rule: {clean(comparison['decision_rule'])}",
            ]
        )
        if comparison.get("caveat"):
            sections.append(f"Caveat: {clean(comparison['caveat'])}")

    sections.extend(
        [
            "## Privacy",
            _render_bullets(
                [clean(item) for item in report.privacy],
                "No specific privacy risk was confirmed.",
            ),
        ]
    )
    if rights_findings:
        sections.append("## Rights & Provenance")
        for finding in rights_findings:
            label = _image_label(str(finding.get("image_id", "image")), image_labels)
            summary = clean(finding.get("summary", "Visible artwork requires provenance review."))
            recommendation = clean(
                finding.get(
                    "recommendation",
                    "Verify the artwork source and usage rights before publishing.",
                )
            )
            sections.append(f"- `{label}` — {summary} {recommendation}")
        sections.append(
            "This is a provenance warning, not a determination of ownership, permission, fair "
            "use, or infringement."
        )
    sections.extend(
        [
            "## Context",
            _render_bullets(
                [clean(item) for item in report.context],
                "No additional contextual claim was required.",
            ),
            "## Recommendation",
            _render_bullets(
                [clean(item) for item in report.recommendations],
                "Review the image at the target avatar size.",
            ),
            "## Evidence",
        ]
    )
    if cited:
        sections.extend(
            f"- [{card['source_title']}]({card['source_url']}) — {card['text']} "
            f"(`{card['card_id']}`)"
            for card in cited
        )
    else:
        sections.append("- No knowledge card was available for this claim.")

    if proposal:
        sections.extend(
            [
                "## Memory Proposal",
                f"Pending approval: “{clean(proposal['text'])}”",
                f"Reason: {clean(proposal['reason'])}",
                "This proposal has not been added to long-term memory.",
            ]
        )
    sections.extend(
        [
            "## Limitations",
            _render_bullets(
                [clean(item) for item in report.limitations],
                "This review evaluates the supplied goals, not identity or personality.",
            ),
        ]
    )
    return "\n\n".join(sections).strip()


def _render_follow_up(
    draft: FollowUpDraft,
    evidence: list[dict[str, Any]],
    image_labels: dict[str, str],
) -> str:
    known_cards = {card["card_id"]: card for card in evidence}
    cited = [known_cards[card_id] for card_id in draft.cited_card_ids if card_id in known_cards]

    def clean(value: Any) -> str:
        return _replace_internal_image_ids(str(value), image_labels)

    sections = ["## Follow-up answer", clean(draft.answer)]
    if draft.supporting_points:
        sections.extend(
            [
                "### Supporting points",
                _render_bullets([clean(item) for item in draft.supporting_points], ""),
            ]
        )
    if cited:
        sections.append("### Evidence reused from the image review")
        sections.extend(
            f"- [{card['source_title']}]({card['source_url']}) — {card['text']} "
            f"(`{card['card_id']}`)"
            for card in cited
        )
    if draft.limitations:
        sections.extend(
            ["### Limits", _render_bullets([clean(item) for item in draft.limitations], "")]
        )
    return "\n\n".join(sections).strip()


def _plain_follow_up_fallback(raw: str) -> FollowUpDraft | None:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json|markdown|text)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
    if len(text) < 3:
        return None
    return FollowUpDraft(
        answer=text[:2000],
        supporting_points=[],
        cited_card_ids=[],
        limitations=["The model returned plain text, so structured follow-up fields were omitted."],
    )


def _compact_follow_up_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted = []
    for message in history[-6:]:
        content = str(message.get("content", ""))
        if message.get("role") == "assistant" and content.lstrip().startswith("# XiangLens Review"):
            content = "[Initial full report omitted here; use the cached structured analysis.]"
        compacted.append({"role": message.get("role"), "content": content[:2000]})
    return compacted


def build_graph(services: GraphServices):
    async def validated_model_json(
        messages: list[dict[str, Any]],
        schema: type[ModelSchema],
        max_tokens: int,
        candidate_score_defaults: dict[str, dict[str, int]] | None = None,
    ) -> ModelSchema:
        raw = await services.model.chat(messages, temperature=0.1, max_tokens=max_tokens)
        last_error = "unknown validation error"
        for attempt in range(2):
            try:
                parsed = parse_json_object(raw)
                if schema is CandidateComparison:
                    parsed = _normalize_candidate_comparison(parsed, candidate_score_defaults)
                return schema.model_validate(parsed)
            except (ModelRequestError, ValidationError) as exc:
                last_error = str(exc)
                if schema is FollowUpDraft and "did not contain a JSON object" in last_error:
                    fallback = _plain_follow_up_fallback(raw)
                    if fallback is not None:
                        return fallback
                if attempt == 1:
                    break
                raw = await services.model.chat(
                    [
                        *messages,
                        {"role": "assistant", "content": raw},
                        {
                            "role": "user",
                            "content": (
                                "The response failed validation. Return only one valid JSON object "
                                f"for schema {schema.__name__}. Error: {last_error[:500]}"
                            ),
                        },
                    ],
                    temperature=0.0,
                    max_tokens=max_tokens,
                )
        if schema is FollowUpDraft and "did not contain a JSON object" in last_error:
            fallback = _plain_follow_up_fallback(raw)
            if fallback is not None:
                return fallback
        raise ModelRequestError(f"Model JSON failed validation after one repair: {last_error}")

    async def intake(state: XiangLensState) -> dict[str, Any]:
        started = time.perf_counter()
        if state.get("reuse_latest_analysis"):
            plan = [
                "Apply the sensitive-inference policy gate.",
                "Recall approved preferences and recent messages from this thread.",
                "Reuse the verified image-analysis snapshot without invoking the vision model.",
                "Answer the follow-up with one bounded language-model call.",
                "Propose reusable memory only from an explicit user statement.",
            ]
        else:
            plan = [
                "Apply the sensitive-inference policy gate.",
                "Recall only user-approved preferences and prior thread context.",
                "Measure each image and scan local metadata and QR evidence.",
                "Observe visible, non-sensitive image facts with the self-hosted vision model.",
                "Run the locally mounted private Lens Tool only after explicit opt-in.",
                "Retrieve up to four source-backed cards from enabled Lens Packs.",
                "Compare multiple candidates with one transparent five-dimension rubric.",
                "Propose reusable memory only from an explicit user statement.",
                "Render a structured goal-relative report with code-controlled citations.",
            ]
        summary = (
            "Created a five-step cached follow-up plan without visual re-analysis."
            if state.get("reuse_latest_analysis")
            else f"Created a fixed nine-step plan for {len(state['image_paths'])} image(s)."
        )
        return {
            "plan": plan,
            "tool_trace": _trace(
                state,
                node="intake",
                tool="bounded_planner",
                started=started,
                summary=summary,
            ),
        }

    async def policy_gate(state: XiangLensState) -> dict[str, Any]:
        started = time.perf_counter()
        message = state["message"].lower()
        blocked = any(re.search(pattern, message) for pattern in SENSITIVE_PATTERNS)
        reason = None
        if blocked:
            reason = (
                "XiangLens cannot infer sensitive attributes, personality, intelligence, health, "
                "criminality, wealth, relationships, politics, religion, or destiny from an image."
            )
        return {
            "blocked_reason": reason,
            "tool_trace": _trace(
                state,
                node="policy_gate",
                tool="sensitive_inference_policy",
                started=started,
                summary=(
                    "Request blocked by policy." if blocked else "Request is within product scope."
                ),
                status="blocked" if blocked else "completed",
            ),
        }

    def route_policy(state: XiangLensState) -> Literal["blocked_report", "recall_context"]:
        return "blocked_report" if state.get("blocked_reason") else "recall_context"

    async def blocked_report(state: XiangLensState) -> dict[str, Any]:
        return {
            "measurements": [],
            "visual_observations": [],
            "privacy_findings": [],
            "rights_findings": [],
            "evidence": [],
            "private_lens_readings": [],
            "recalled_memories": [],
            "comparison": None,
            "memory_proposal_draft": None,
            "report_markdown": (
                "## Request not analyzed\n\n"
                f"{state['blocked_reason']}\n\n"
                "I can instead evaluate crop resilience, visible privacy risks, "
                "small-size clarity, platform requirements, or fit with goals you provide."
            ),
        }

    async def recall_context(state: XiangLensState) -> dict[str, Any]:
        started = time.perf_counter()
        memories = services.database.list_memories(state["user_id"], limit=8)
        history = services.database.list_messages(state["thread_id"], limit=8)
        return {
            "recalled_memories": memories,
            "history": history,
            "tool_trace": _trace(
                state,
                node="recall_context",
                tool="sqlite_memory",
                started=started,
                summary=f"Recalled {len(memories)} approved memories and {len(history)} messages.",
            ),
        }

    def route_after_recall(state: XiangLensState) -> Literal["reuse_analysis", "inspect_local"]:
        return "reuse_analysis" if state.get("reuse_latest_analysis") else "inspect_local"

    async def reuse_analysis(state: XiangLensState) -> dict[str, Any]:
        started = time.perf_counter()
        return {
            "tool_trace": _trace(
                state,
                node="reuse_analysis",
                tool="cached_verified_analysis",
                started=started,
                summary=(
                    f"Reused {len(state.get('measurements', []))} observation(s), "
                    f"{len(state.get('privacy_findings', []))} privacy finding(s), and "
                    f"{len(state.get('rights_findings', []))} rights finding(s), plus "
                    f"{len(state.get('evidence', []))} evidence card(s); VLM skipped."
                ),
            )
        }

    async def answer_follow_up(state: XiangLensState) -> dict[str, Any]:
        started = time.perf_counter()
        context = {
            "follow_up_request": state["message"],
            "platform": state["platform"],
            "audience": state["audience"],
            "goals": state["intent_keywords"],
            "image_labels": state.get("image_labels", {}),
            "recent_thread_messages": _compact_follow_up_history(state.get("history", [])),
            "approved_memories": [
                {"type": item["memory_type"], "text": item["text"]}
                for item in state.get("recalled_memories", [])
            ],
            "cached_observations": state.get("measurements", []),
            "cached_privacy_findings": state.get("privacy_findings", []),
            "cached_rights_findings": state.get("rights_findings", []),
            "cached_comparison": state.get("comparison"),
            "cached_private_lens_readings": state.get("private_lens_readings", []),
            "cached_evidence": state.get("evidence", []),
        }
        draft = await validated_model_json(
            [
                {
                    "role": "system",
                    "content": (
                        "Answer one follow-up about an already completed XiangLens image review. "
                        "Return only JSON matching FollowUpDraft with answer, supporting_points, "
                        "cited_card_ids, and limitations. Use the cached observations, privacy "
                        "findings, rights/provenance warnings, comparison, evidence, approved "
                        "memories, and recent messages. "
                        "Do not repeat the full original report. Do not claim that the image was "
                        "visually re-inspected or that rubric scores were recomputed. Cite only "
                        "card IDs present in cached_evidence. Never infer identity or sensitive "
                        "traits. Keep the answer concise."
                    ),
                },
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            ],
            FollowUpDraft,
            1000,
        )
        known_ids = {card["card_id"] for card in state.get("evidence", [])}
        draft = draft.model_copy(
            update={
                "cited_card_ids": [
                    card_id for card_id in draft.cited_card_ids if card_id in known_ids
                ]
            }
        )
        return {
            "follow_up_draft": draft.model_dump(),
            "report_markdown": _render_follow_up(
                draft,
                state.get("evidence", []),
                state.get("image_labels", {}),
            ),
            "tool_trace": _trace(
                state,
                node="answer_follow_up",
                tool="self_hosted_llm_cached_follow_up",
                started=started,
                summary="Answered from cached analysis with no vision-model invocation.",
            ),
        }

    async def inspect_local(state: XiangLensState) -> dict[str, Any]:
        started = time.perf_counter()
        measurements: list[dict[str, Any]] = []
        findings: list[dict[str, Any]] = []
        for path in state["image_paths"]:
            measurement, image_findings = services.image_inspector.inspect(path)
            measurements.append(measurement)
            findings.extend({"image_id": path.stem, **finding} for finding in image_findings)
        return {
            "measurements": measurements,
            "privacy_findings": findings,
            "tool_trace": _trace(
                state,
                node="inspect_local",
                tool="image_measurement_and_privacy_scan",
                started=started,
                summary=(
                    f"Measured {len(measurements)} image(s) and produced "
                    f"{len(findings)} local finding(s)."
                ),
            ),
        }

    async def observe_visual(state: XiangLensState) -> dict[str, Any]:
        started = time.perf_counter()
        prompt = (
            "Return a JSON object with keys visible_elements, composition, text_candidates, "
            "privacy_candidates, rights_candidates, and uncertainties. visible_elements, "
            "text_candidates, privacy_candidates, rights_candidates, and uncertainties must be "
            "arrays of short strings. composition must be one short string, not an array. "
            "In rights_candidates, flag directly visible recognizable third-party characters, "
            "brand marks, watermarks, signatures, or distinctive published artwork whose source "
            "and usage rights should be verified. Name a well-known character only when the "
            "visual resemblance is strong, and phrase it as 'closely resembles X' rather than "
            "asserting authenticity, ownership, or infringement. An empty array is valid when no "
            "such candidate is visible. "
            "Describe only directly visible evidence. "
            f"The user selected platform '{state['platform']}', audience '{state['audience']}', "
            f"and goals {state['intent_keywords']}. Do not identify a person or "
            "infer sensitive traits."
        )
        observations = []
        visual_findings = list(state.get("privacy_findings", []))
        rights_findings: list[dict[str, Any]] = []
        for path in state["image_paths"]:
            raw = await services.model.inspect_image(path, prompt)
            try:
                observation = VisualObservation.model_validate(raw)
            except ValidationError as exc:
                repair_prompt = (
                    prompt
                    + " Your previous JSON failed validation. Return a corrected object only. "
                    + 'Example shape: {"visible_elements":["..."],'
                    + '"composition":"...","text_candidates":[],'
                    + '"privacy_candidates":[],"rights_candidates":[],'
                    + '"uncertainties":[]}. '
                    + f"Validation error: {str(exc)[:500]}"
                )
                repaired = await services.model.inspect_image(path, repair_prompt)
                observation = VisualObservation.model_validate(repaired)
            observations.append({"image_id": path.stem, **observation.model_dump()})
            visual_findings.extend(
                {
                    "image_id": path.stem,
                    "type": "visual_privacy_candidate",
                    "severity": "medium",
                    "observable": True,
                    "summary": candidate,
                    "recommendation": "Confirm the visible detail before sharing the image.",
                }
                for candidate in observation.privacy_candidates
            )
            rights_findings.extend(
                {
                    "image_id": path.stem,
                    "type": "copyright_provenance_candidate",
                    "severity": "medium",
                    "observable": True,
                    "summary": candidate,
                    "recommendation": (
                        "Verify the source and intended-profile usage rights; prefer original, "
                        "commissioned-with-rights, appropriately licensed, or public-domain art."
                    ),
                }
                for candidate in observation.rights_candidates
            )
        return {
            "visual_observations": observations,
            "privacy_findings": visual_findings,
            "rights_findings": rights_findings,
            "tool_trace": _trace(
                state,
                node="observe_visual",
                tool="self_hosted_vlm",
                started=started,
                summary=(
                    f"Validated structured observations for {len(observations)} image(s) and "
                    f"flagged {len(rights_findings)} rights/provenance candidate(s) with the "
                    "configured Radeon endpoint."
                ),
            ),
        }

    async def retrieve_evidence(state: XiangLensState) -> dict[str, Any]:
        started = time.perf_counter()
        finding_types = [item.get("type", "") for item in state.get("privacy_findings", [])]
        rights_terms = [
            str(value)
            for finding in state.get("rights_findings", [])
            for value in (finding.get("type", ""), finding.get("summary", ""))
            if value
        ]
        visual_terms = [
            item
            for observation in state.get("visual_observations", [])
            for item in observation.get("visible_elements", [])[:5]
        ]
        memory_terms = [item["text"] for item in state.get("recalled_memories", [])[:4]]
        query = " ".join(
            [
                state["message"],
                state["platform"],
                state["audience"],
                *state["intent_keywords"],
                *finding_types,
                *rights_terms,
                *visual_terms,
                *memory_terms,
            ]
        )
        cards = services.knowledge.search(query, state["enabled_packs"], limit=services.rag_top_k)
        evidence = [card.model_dump() for card in cards]
        return {
            "evidence": evidence,
            "tool_trace": _trace(
                state,
                node="retrieve_evidence",
                tool="milvus_lite",
                started=started,
                summary=f"Retrieved {len(evidence)} source-backed knowledge card(s).",
            ),
        }

    async def run_private_lens(state: XiangLensState) -> dict[str, Any]:
        started = time.perf_counter()
        if not state.get("enable_private_lens", False):
            return {
                "private_lens_readings": [],
                "tool_trace": _trace(
                    state,
                    node="run_private_lens",
                    tool="private_108_lens",
                    started=started,
                    summary="Private Lens Tool was not enabled for this run.",
                    status="skipped",
                ),
            }
        if services.private_lens is None:
            return {
                "private_lens_readings": [],
                "tool_trace": _trace(
                    state,
                    node="run_private_lens",
                    tool="private_108_lens",
                    started=started,
                    summary="Private Lens Tool is not mounted on this server.",
                    status="skipped",
                ),
            }
        readings = [
            (
                await services.private_lens.inspect(
                    image_path=path,
                    model=services.model,
                )
            ).model_dump()
            for path in state["image_paths"]
        ]
        return {
            "private_lens_readings": readings,
            "tool_trace": _trace(
                state,
                node="run_private_lens",
                tool="private_108_lens",
                started=started,
                summary=(
                    f"Produced {len(readings)} safety-filtered symbolic reading(s) from a "
                    "runtime-only private reference."
                ),
            ),
        }

    async def compare_candidates(state: XiangLensState) -> dict[str, Any]:
        started = time.perf_counter()
        if len(state["image_paths"]) < 2:
            return {
                "comparison": None,
                "tool_trace": _trace(
                    state,
                    node="compare_candidates",
                    tool="transparent_comparison_rubric",
                    started=started,
                    summary="Comparison skipped for a single image.",
                    status="skipped",
                ),
            }
        image_ids = [path.stem for path in state["image_paths"]]
        score_defaults = _comparison_score_defaults(
            image_ids,
            state.get("privacy_findings", []),
            state.get("rights_findings", []),
            state.get("recalled_memories", []),
        )
        context = {
            "image_ids": image_ids,
            "image_labels": state.get("image_labels", {}),
            "platform": state["platform"],
            "audience": state["audience"],
            "goals": state["intent_keywords"],
            "measurements": state.get("measurements", []),
            "observations": state.get("visual_observations", []),
            "privacy_findings": state.get("privacy_findings", []),
            "rights_findings": state.get("rights_findings", []),
            "approved_memories": [
                {"type": item["memory_type"], "text": item["text"]}
                for item in state.get("recalled_memories", [])
            ],
        }
        comparison = await validated_model_json(
            [
                {
                    "role": "system",
                    "content": (
                        "Compare every supplied image with the same five dimensions, each scored "
                        "from 0 to 5: crop_resilience, small_size_clarity, privacy_safety, "
                        "intent_alignment, and contextual_ambiguity. A privacy risk overrides the "
                        "aggregate score. Higher contextual_ambiguity means more ambiguity. "
                        "Every candidates item should include a non-empty rationale string. Use "
                        "approved memories only as user-provided goals or constraints when scoring "
                        "intent_alignment; never treat them as observed image facts or proof of a "
                        "legal conclusion. Treat rights_findings as provenance uncertainty, not "
                        "privacy findings. When the user's approved goal mentions copyright or "
                        "usage rights, reflect a candidate-specific rights warning by lowering "
                        "intent_alignment and/or raising contextual_ambiguity. Use only the "
                        "supplied image IDs. The application "
                        "verifies the scores and "
                        "derives the final recommendation with its fixed rule. Return only JSON "
                        "matching CandidateComparison."
                    ),
                },
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            ],
            CandidateComparison,
            1800,
            candidate_score_defaults=score_defaults,
        )
        candidate_ids = {candidate.image_id for candidate in comparison.candidates}
        if candidate_ids != set(image_ids) or comparison.recommended_image_id not in candidate_ids:
            raise ModelRequestError("The comparison did not cover exactly the supplied image IDs")
        return {
            "comparison": comparison.model_dump(),
            "tool_trace": _trace(
                state,
                node="compare_candidates",
                tool="transparent_comparison_rubric",
                started=started,
                summary=f"Compared {len(image_ids)} images with five visible dimensions.",
            ),
        }

    async def propose_memory(state: XiangLensState) -> dict[str, Any]:
        started = time.perf_counter()
        proposal = _deterministic_memory_proposal(state["message"])
        if proposal is None:
            return {
                "memory_proposal_draft": None,
                "tool_trace": _trace(
                    state,
                    node="propose_memory",
                    tool="consent_first_memory",
                    started=started,
                    summary="No explicit reusable user statement was detected.",
                    status="skipped",
                ),
            }
        return {
            "memory_proposal_draft": proposal,
            "tool_trace": _trace(
                state,
                node="propose_memory",
                tool="consent_first_memory",
                started=started,
                summary=(
                    "Created one deterministic pending memory proposal from the user's explicit "
                    "statement; long-term storage still requires approval."
                ),
            ),
        }

    async def synthesize_report(state: XiangLensState) -> dict[str, Any]:
        started = time.perf_counter()
        context = {
            "request": state["message"],
            "platform": state["platform"],
            "audience": state["audience"],
            "goals": state["intent_keywords"],
            "image_labels": state.get("image_labels", {}),
            "recent_thread_messages": state.get("history", [])[-6:],
            "measurements": state.get("measurements", []),
            "visual_observations": state.get("visual_observations", []),
            "private_lens_readings": state.get("private_lens_readings", []),
            "privacy_findings": state.get("privacy_findings", []),
            "rights_findings": state.get("rights_findings", []),
            "approved_memories": [
                {"type": item["memory_type"], "text": item["text"]}
                for item in state.get("recalled_memories", [])
            ],
            "comparison": state.get("comparison"),
            "evidence": state.get("evidence", []),
        }

        report = await validated_model_json(
            [
                {
                    "role": "system",
                    "content": (
                        "Create a concise XiangLens report draft. Return only JSON matching "
                        "StructuredReportDraft with summary, observed, privacy, context, "
                        "recommendations, limitations, and cited_card_ids. Separate facts from "
                        "interpretation. Base recommendations only on user goals. Cite only "
                        "card IDs present in evidence. Never infer identity or sensitive traits. "
                        "Always surface supplied rights_findings in context or recommendations, "
                        "using resemblance and provenance language rather than asserting ownership "
                        "or infringement. "
                        "Never treat a cultural or private-course association as universal or "
                        "factual. Do not repeat private course text."
                    ),
                },
                {
                    "role": "user",
                    "content": "Synthesize this verified run context:\n"
                    + json.dumps(context, ensure_ascii=False),
                },
            ],
            StructuredReportDraft,
            2200,
        )
        known_ids = {card["card_id"] for card in state.get("evidence", [])}
        report = report.model_copy(
            update={
                "cited_card_ids": [
                    card_id for card_id in report.cited_card_ids if card_id in known_ids
                ]
            }
        )
        rendered = _render_report(
            report,
            state.get("evidence", []),
            state.get("comparison"),
            state.get("memory_proposal_draft"),
            state.get("private_lens_readings", []),
            state.get("rights_findings", []),
            state.get("image_labels", {}),
        )
        return {
            "structured_report": report.model_dump(),
            "report_markdown": rendered,
            "tool_trace": _trace(
                state,
                node="synthesize_report",
                tool="self_hosted_llm_and_safe_renderer",
                started=started,
                summary="Validated structured output and rendered code-controlled citations.",
            ),
        }

    def route_after_memory(state: XiangLensState) -> Literal["synthesize_report", "end"]:
        return "end" if state.get("reuse_latest_analysis") else "synthesize_report"

    builder = StateGraph(XiangLensState)
    builder.add_node("intake", intake)
    builder.add_node("policy_gate", policy_gate)
    builder.add_node("blocked_report", blocked_report)
    builder.add_node("recall_context", recall_context)
    builder.add_node("reuse_analysis", reuse_analysis)
    builder.add_node("answer_follow_up", answer_follow_up)
    builder.add_node("inspect_local", inspect_local)
    builder.add_node("observe_visual", observe_visual)
    builder.add_node("run_private_lens", run_private_lens)
    builder.add_node("retrieve_evidence", retrieve_evidence)
    builder.add_node("compare_candidates", compare_candidates)
    builder.add_node("propose_memory", propose_memory)
    builder.add_node("synthesize_report", synthesize_report)

    builder.add_edge(START, "intake")
    builder.add_edge("intake", "policy_gate")
    builder.add_conditional_edges("policy_gate", route_policy)
    builder.add_edge("blocked_report", END)
    builder.add_conditional_edges("recall_context", route_after_recall)
    builder.add_edge("reuse_analysis", "answer_follow_up")
    builder.add_edge("answer_follow_up", "propose_memory")
    builder.add_edge("inspect_local", "observe_visual")
    builder.add_edge("observe_visual", "run_private_lens")
    builder.add_edge("run_private_lens", "retrieve_evidence")
    builder.add_edge("retrieve_evidence", "compare_candidates")
    builder.add_edge("compare_candidates", "propose_memory")
    builder.add_conditional_edges(
        "propose_memory",
        route_after_memory,
        {"synthesize_report": "synthesize_report", "end": END},
    )
    builder.add_edge("synthesize_report", END)
    return builder.compile()
