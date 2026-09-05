"""Outcome oracle for the regional revenue visualisation benchmark."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET

import pytest

from xenix.services.agent import SourceAttachmentInput, SubmitUserTurnInput
from xenix.services.artifact_service import build_artifact_uri
from xenix.services.storage.models import ArtifactKind

from ._infra.case_support import (
    AttachedSourceState,
    attached_source_unchanged,
    canonical_completion,
    capture_attached_source_state,
    enum_value,
    is_within,
    sha256_file,
)
from ._infra.contracts import (
    BenchmarkCaseAssessment,
    BenchmarkCaseContext,
    BenchmarkCaseServices,
    BenchmarkInputError,
    JudgeInput,
    JudgeRubric,
    OutcomeCheck,
    SemanticVerdict,
)


CASE_ID = "analysis.revenue_by_region_chart"
EXPECTED_FILE_SIZE = 119
EXPECTED_SHA256 = "48C6C47CD9DA49A284D4ABF6C1C10A3340A25352C8567C2EE3108AA7AE6DC224"
_DEFAULT_SOURCE_PATH = Path(__file__).resolve().parent / "fixtures" / "revenue_by_region.csv"

REGIONAL_REVENUE_TASK_INTENT = "请根据这份销售数据，制作一张清晰易懂的可视化，帮助业务人员比较不同地区的收入表现。"
REGIONAL_REVENUE_FACTS = (
    "本次比较仅涉及四个地区：North、South、East、West。",
    "收入由高到低的顺序为：West、East、South、North。",
)
REGIONAL_REVENUE_RUBRIC = JudgeRubric(
    rubric_id="analysis.regional_sales.v1",
    score_dimensions=(
        "task_fulfilment",
        "factual_grounding",
        "semantic_comprehensibility",
    ),
    allowed_reason_codes=(
        "task_fulfilled",
        "task_not_fulfilled",
        "revenue_order_supported",
        "revenue_order_contradicted",
        "labels_clear",
        "labels_insufficient",
        "evidence_insufficient",
    ),
)
_MAX_ARTIFACT_EVIDENCE_ITEMS = 48
_MAX_ARTIFACT_EVIDENCE_TEXT_LENGTH = 448
_WINDOWS_PATH_PATTERN = re.compile(r"(?:^|\s)[A-Za-z]:[\\/]")
_UNIX_PATH_PATTERN = re.compile(r"(?:^|\s)/[^\s]+")
_CALIBRATION_FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "regional_sales_judge_calibration.json"
)
_CALIBRATION_VERDICTS = frozenset(
    {
        SemanticVerdict.PASS,
        SemanticVerdict.PARTIAL,
        SemanticVerdict.FAIL,
        SemanticVerdict.INCONCLUSIVE,
    }
)


pytestmark = pytest.mark.agent_harness_live


@dataclass(frozen=True)
class JudgeCalibrationFixture:
    """One small, hand-labelled packet for explicit judge calibration."""

    fixture_id: str
    expected_verdict: SemanticVerdict
    judge_input: JudgeInput


def regional_sales_judge_calibrations(
    fixture_path: Path = _CALIBRATION_FIXTURE_PATH,
) -> tuple[JudgeCalibrationFixture, ...]:
    """Load graph-case calibration packets without making them another test case."""

    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("judge_calibration_fixture_invalid") from exc
    if not isinstance(payload, list) or len(payload) != 4:
        raise ValueError("judge_calibration_fixture_invalid")
    fixtures = tuple(_parse_calibration_fixture(item) for item in payload)
    if len({fixture.fixture_id for fixture in fixtures}) != len(fixtures):
        raise ValueError("judge_calibration_fixture_invalid")
    return fixtures


def _parse_calibration_fixture(value: Any) -> JudgeCalibrationFixture:
    if not isinstance(value, dict) or set(value) != {
        "fixture_id",
        "expected_verdict",
        "artifact_evidence",
    }:
        raise ValueError("judge_calibration_fixture_invalid")
    fixture_id = value["fixture_id"]
    expected_raw = value["expected_verdict"]
    evidence = value["artifact_evidence"]
    if (
        not isinstance(fixture_id, str)
        or not fixture_id.strip()
        or len(fixture_id) > 96
        or not isinstance(expected_raw, str)
        or not isinstance(evidence, list)
        or any(not isinstance(item, str) for item in evidence)
    ):
        raise ValueError("judge_calibration_fixture_invalid")
    try:
        expected_verdict = SemanticVerdict(expected_raw)
    except ValueError as exc:
        raise ValueError("judge_calibration_fixture_invalid") from exc
    if expected_verdict not in _CALIBRATION_VERDICTS:
        raise ValueError("judge_calibration_fixture_invalid")
    try:
        judge_input = build_regional_revenue_judge_input(tuple(evidence))
    except ValueError as exc:
        raise ValueError("judge_calibration_fixture_invalid") from exc
    return JudgeCalibrationFixture(
        fixture_id=fixture_id,
        expected_verdict=expected_verdict,
        judge_input=judge_input,
    )


class RevenueByRegionChartCase:
    """Outcome-first regional-revenue visualisation case without a chart prescription."""

    case_id = CASE_ID

    def __init__(self, source_path: Path = _DEFAULT_SOURCE_PATH) -> None:
        self.source_path = source_path

    def validate_input(self) -> str:
        if not self.source_path.is_file():
            raise BenchmarkInputError("missing_fixture")
        if self.source_path.stat().st_size != EXPECTED_FILE_SIZE:
            raise BenchmarkInputError("fixture_size_mismatch")
        digest = sha256_file(self.source_path)
        if digest != EXPECTED_SHA256:
            raise BenchmarkInputError("fixture_hash_mismatch")
        return digest

    def build_submission(self, *, thread_id: str, fq_model_key: str) -> SubmitUserTurnInput:
        return SubmitUserTurnInput(
            thread_id=thread_id,
            text=REGIONAL_REVENUE_TASK_INTENT,
            source_attachments=[SourceAttachmentInput(file_path=str(self.source_path.resolve()))],
            fq_model_key=fq_model_key,
        )

    def capture_source_state(
        self,
        *,
        snapshot: Any,
        services: BenchmarkCaseServices,
    ) -> AttachedSourceState:
        return capture_attached_source_state(
            source_path=self.source_path,
            snapshot=snapshot,
            services=services,
        )

    def assess(self, *, context: BenchmarkCaseContext) -> BenchmarkCaseAssessment:
        source_state = context.source_state
        completed = canonical_completion(context.snapshot)
        terminal = self._resolve_terminal_artifact(
            snapshot=context.snapshot,
            artifact_service=context.services.artifacts,
            runtime_home=context.runtime_home,
        )
        evidence = (
            _project_svg_evidence(
                Path(str(getattr(terminal, "absolute_path", ""))),
                forbidden_values=_evidence_forbidden_values(
                    terminal_artifact=terminal,
                    source_path=self.source_path,
                    source_state=source_state,
                    run_dataset_ids=context.run_dataset_ids,
                ),
            )
            if terminal is not None
            else None
        )
        source_unchanged = _source_unchanged(
            source_path=self.source_path,
            source_state=source_state,
            services=context.services,
        )
        state_isolated = self._state_isolated(
            context=context,
            terminal_artifact=terminal,
        )
        integrity_checks = (
            OutcomeCheck(
                "canonical_completion",
                completed,
                _completion_summary(completed),
            ),
            OutcomeCheck("source_unchanged", source_unchanged, _source_summary(source_unchanged)),
            OutcomeCheck("state_isolated", state_isolated, _isolation_summary(state_isolated)),
        )
        terminal_resolved = evidence is not None
        semantic_checks = (
            OutcomeCheck(
                "terminal_artifact_resolved",
                terminal_resolved,
                "readable_isolated_svg_reference"
                if terminal_resolved
                else "no_readable_svg_reference",
            ),
        )
        integrity_passed = all(check.passed for check in integrity_checks)
        judge_input = (
            build_regional_revenue_judge_input(evidence)
            if terminal_resolved and integrity_passed and evidence is not None
            else None
        )
        return BenchmarkCaseAssessment(
            semantic_checks=semantic_checks,
            integrity_checks=integrity_checks,
            judge_input=judge_input,
            judge_required=True,
        )

    @staticmethod
    def _resolve_terminal_artifact(
        *,
        snapshot: Any | None,
        artifact_service: Any,
        runtime_home: Path,
    ) -> Any | None:
        for message in reversed(list(getattr(snapshot, "messages", []))):
            if enum_value(getattr(message, "kind", None)) != "tool_result":
                continue
            if enum_value(getattr(message, "result_status", None)) != "succeeded":
                continue
            payload = getattr(message, "value_payload", None)
            if not isinstance(payload, dict):
                continue
            artifact_id = payload.get("artifact_id")
            if not isinstance(artifact_id, str) or not artifact_id.strip():
                continue
            try:
                artifact = artifact_service.resolve_uri(build_artifact_uri(artifact_id))
            except Exception:
                continue
            if (
                getattr(artifact, "kind", None) != ArtifactKind.IMAGE
                or getattr(artifact, "mime_type", None) != "image/svg+xml"
                or not bool(getattr(artifact, "ready_to_open", False))
                or not bool(getattr(artifact, "exists", False))
                or not is_within(Path(str(getattr(artifact, "absolute_path", ""))), runtime_home)
            ):
                continue
            return artifact
        return None

    @staticmethod
    def _state_isolated(*, context: BenchmarkCaseContext, terminal_artifact: Any | None) -> bool:
        if not context.settings_unchanged:
            return False
        try:
            datasets_confined = all(
                is_within(Path(str(dataset.source_path)), context.runtime_home)
                for dataset in context.services.datasets.list_datasets()
            )
            artifact_confined = terminal_artifact is None or is_within(
                Path(str(getattr(terminal_artifact, "absolute_path", ""))),
                context.runtime_home,
            )
            return datasets_confined and artifact_confined
        except Exception:
            return False


def _source_unchanged(
    *,
    source_path: Path,
    source_state: Any | None,
    services: BenchmarkCaseServices,
) -> bool:
    if not isinstance(source_state, AttachedSourceState) or not source_state.source_dataset_ids:
        return False
    try:
        return attached_source_unchanged(
            source_path=source_path,
            source_state=source_state,
            services=services,
        )
    except Exception:
        return False


def build_regional_revenue_judge_input(artifact_evidence: tuple[str, ...]) -> JudgeInput:
    return JudgeInput(
        rubric=REGIONAL_REVENUE_RUBRIC,
        task_intent=REGIONAL_REVENUE_TASK_INTENT,
        facts=REGIONAL_REVENUE_FACTS,
        artifact_evidence=artifact_evidence,
    )


def _evidence_forbidden_values(
    *,
    terminal_artifact: Any,
    source_path: Path,
    source_state: Any | None,
    run_dataset_ids: frozenset[str],
) -> tuple[str, ...]:
    """Known internal locators that must never enter a judge evidence string."""

    source_dataset_ids = (
        source_state.source_dataset_ids
        if isinstance(source_state, AttachedSourceState)
        else ()
    )
    values = (
        str(getattr(terminal_artifact, "artifact_id", "") or ""),
        str(getattr(terminal_artifact, "absolute_path", "") or ""),
        str(source_path.resolve()),
        *source_dataset_ids,
        *run_dataset_ids,
    )
    return tuple(value for value in values if value)


def _project_svg_evidence(
    path: Path,
    *,
    forbidden_values: tuple[str, ...] = (),
) -> tuple[str, ...] | None:
    """Project visible/a11y SVG semantics without retaining SVG markup or locators."""

    try:
        root = ET.parse(path).getroot()
    except (OSError, UnicodeError, ValueError, ET.ParseError):
        return None
    if _local_name(root.tag) != "svg":
        return None

    evidence: list[str] = []
    seen: set[str] = set()
    _collect_svg_evidence(
        root,
        hidden=False,
        evidence=evidence,
        seen=seen,
        forbidden_values=forbidden_values,
    )
    return tuple(evidence)


def _collect_svg_evidence(
    element: ET.Element,
    *,
    hidden: bool,
    evidence: list[str],
    seen: set[str],
    forbidden_values: tuple[str, ...],
) -> None:
    if len(evidence) >= _MAX_ARTIFACT_EVIDENCE_ITEMS:
        return
    hidden = hidden or _svg_element_hidden(element)
    if hidden:
        return

    aria_label = element.attrib.get("aria-label")
    if isinstance(aria_label, str):
        role = element.attrib.get("aria-roledescription")
        label = _safe_evidence_text(aria_label, forbidden_values=forbidden_values)
        if label is not None:
            role_suffix = ""
            if isinstance(role, str):
                safe_role = _safe_evidence_text(role, forbidden_values=forbidden_values)
                if safe_role is not None:
                    role_suffix = f" ({safe_role})"
            _append_evidence(evidence, seen, f"aria_label{role_suffix}: {label}")

    if _local_name(element.tag) == "text":
        text = _safe_evidence_text(" ".join(element.itertext()), forbidden_values=forbidden_values)
        if text is not None:
            _append_evidence(evidence, seen, f"visible_text: {text}")

    for child in element:
        _collect_svg_evidence(
            child,
            hidden=hidden,
            evidence=evidence,
            seen=seen,
            forbidden_values=forbidden_values,
        )


def _svg_element_hidden(element: ET.Element) -> bool:
    attributes = element.attrib
    if str(attributes.get("aria-hidden", "")).strip().lower() == "true":
        return True
    style = _style_properties(str(attributes.get("style", "")))
    display = str(attributes.get("display", style.get("display", ""))).strip().lower()
    visibility = str(attributes.get("visibility", style.get("visibility", ""))).strip().lower()
    opacity = str(attributes.get("opacity", style.get("opacity", ""))).strip()
    return display == "none" or visibility in {"hidden", "collapse"} or _is_zero(opacity)


def _style_properties(style: str) -> dict[str, str]:
    properties: dict[str, str] = {}
    for declaration in style.split(";"):
        key, separator, value = declaration.partition(":")
        if separator:
            properties[key.strip().lower()] = value.strip()
    return properties


def _is_zero(value: str) -> bool:
    if not value:
        return False
    try:
        return float(value.removesuffix("%")) == 0
    except ValueError:
        return False


def _safe_evidence_text(value: str, *, forbidden_values: tuple[str, ...]) -> str | None:
    normalized = " ".join(value.split())
    if not normalized or _looks_like_raw_source_row(normalized):
        return None
    lowered = normalized.lower()
    if "<svg" in lowered or "</svg" in lowered or "artifact://" in lowered or "file://" in lowered:
        return None
    if any(
        marker in lowered
        for marker in ("artifact_id", "dataset_id", "thread_id", "conversation_id", "run_id")
    ):
        return None
    if _WINDOWS_PATH_PATTERN.search(normalized) or _UNIX_PATH_PATTERN.search(normalized):
        return None
    if any(forbidden and forbidden in normalized for forbidden in forbidden_values):
        return None
    return normalized[:_MAX_ARTIFACT_EVIDENCE_TEXT_LENGTH]


def _looks_like_raw_source_row(value: str) -> bool:
    return len([part for part in value.split(",") if part.strip()]) >= 4


def _append_evidence(evidence: list[str], seen: set[str], item: str) -> None:
    if len(evidence) >= _MAX_ARTIFACT_EVIDENCE_ITEMS or item in seen:
        return
    seen.add(item)
    evidence.append(item[:512])


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _completion_summary(passed: bool) -> str:
    return "canonical_assistant_completion" if passed else "not_a_terminal_assistant_completion"


def _source_summary(passed: bool) -> str:
    return "external_and_registered_source_unchanged" if passed else "source_changed_or_unreadable"


def _isolation_summary(passed: bool) -> str:
    return "state_confined_to_cell_runtime" if passed else "state_or_settings_escaped_cell_runtime"


def test_revenue_by_region_chart(agent_harness_benchmark) -> None:
    """Measure whether the model creates a business-useful regional comparison."""

    agent_harness_benchmark.run(RevenueByRegionChartCase())
