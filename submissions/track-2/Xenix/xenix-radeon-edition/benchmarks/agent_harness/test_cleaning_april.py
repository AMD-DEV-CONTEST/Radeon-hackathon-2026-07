"""Outcome oracle for the real April dine-in sales cleaning benchmark."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import polars as pl
import pytest

from xenix.services.agent import SourceAttachmentInput, SubmitUserTurnInput
from xenix.services.tabular import load_tabular_frame

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
    OutcomeCheck,
)


CASE_ID = "cleaning.april_dine_in_sales"
EXPECTED_FILE_SIZE = 116_459_191
EXPECTED_SHA256 = "6B902DE50277E727FE936FFC4FE072B4D8B1C3D60A7D85413E114B72C4140E31"
EXPECTED_SHAPE = (485_790, 50)
_DATASET_ID_LINE = re.compile(r"^dataset_id:\s*([A-Za-z0-9_-]+)\s*$", re.MULTILINE)


pytestmark = pytest.mark.agent_harness_live


class AprilDineInSalesCleaningCase:
    """One outcome-first cleaning case; it does not prescribe Tool behavior."""

    case_id = CASE_ID

    def __init__(self, source_path: Path) -> None:
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
            text="清洗",
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

    def assess(
        self,
        *,
        context: BenchmarkCaseContext,
    ) -> BenchmarkCaseAssessment:
        snapshot = context.snapshot
        source_state = context.source_state
        dataset_service = context.services.datasets
        if snapshot is None or source_state is None or not source_state.source_dataset_ids:
            semantic_checks = (
                OutcomeCheck("terminal_output_resolved", False, "no_canonical_snapshot"),
                OutcomeCheck("header_promoted", False, "no_terminal_dataset"),
                OutcomeCheck("report_row_removed", False, "no_terminal_dataset"),
                OutcomeCheck("header_row_removed", False, "no_terminal_dataset"),
                OutcomeCheck("exact_duplicates_removed", False, "no_terminal_dataset"),
                OutcomeCheck("expected_shape", False, "no_terminal_dataset"),
                OutcomeCheck("business_rows_preserved", False, "no_terminal_dataset"),
            )
            integrity_checks = (
                OutcomeCheck("canonical_completion", False, "no_canonical_snapshot"),
                OutcomeCheck("source_unchanged", False, "source_state_unavailable"),
                OutcomeCheck("state_isolated", False, "source_state_unavailable"),
            )
            return BenchmarkCaseAssessment(
                semantic_checks=semantic_checks,
                integrity_checks=integrity_checks,
            )

        terminal = self._resolve_terminal_dataset(
            snapshot=snapshot,
            dataset_service=dataset_service,
            source_dataset_ids=set(source_state.source_dataset_ids),
            run_dataset_ids=context.run_dataset_ids,
        )
        canonical_complete = canonical_completion(snapshot)
        source_unchanged = attached_source_unchanged(
            source_path=self.source_path,
            source_state=source_state,
            services=context.services,
        )
        state_isolated = self._state_isolated(
            dataset_service=dataset_service,
            runtime_home=context.runtime_home,
            settings_unchanged=context.settings_unchanged,
        )
        if terminal is None:
            semantic_checks = (
                OutcomeCheck("terminal_output_resolved", False, "no_readable_run_output_reference"),
                OutcomeCheck("header_promoted", False, "no_terminal_dataset"),
                OutcomeCheck("report_row_removed", False, "no_terminal_dataset"),
                OutcomeCheck("header_row_removed", False, "no_terminal_dataset"),
                OutcomeCheck("exact_duplicates_removed", False, "no_terminal_dataset"),
                OutcomeCheck("expected_shape", False, "no_terminal_dataset"),
                OutcomeCheck("business_rows_preserved", False, "no_terminal_dataset"),
            )
            integrity_checks = (
                OutcomeCheck("canonical_completion", canonical_complete, _completion_summary(canonical_complete)),
                OutcomeCheck("source_unchanged", source_unchanged, _source_summary(source_unchanged)),
                OutcomeCheck("state_isolated", state_isolated, _isolation_summary(state_isolated)),
            )
            return BenchmarkCaseAssessment(
                semantic_checks=semantic_checks,
                integrity_checks=integrity_checks,
            )

        terminal_dataset, output_frame = terminal
        source_dataset = dataset_service.get_dataset(source_state.source_dataset_ids[0])
        source_frame = _load_dataset_frame(source_dataset)
        shape = (int(output_frame.height), int(output_frame.width))
        table_checks = _cleaning_checks(source_frame=source_frame, output_frame=output_frame)
        semantic_checks = (
            OutcomeCheck("terminal_output_resolved", True, "readable_run_output_reference"),
            *table_checks,
        )
        integrity_checks = (
            OutcomeCheck("canonical_completion", canonical_complete, _completion_summary(canonical_complete)),
            OutcomeCheck("source_unchanged", source_unchanged, _source_summary(source_unchanged)),
            OutcomeCheck("state_isolated", state_isolated, _isolation_summary(state_isolated)),
        )
        del terminal_dataset
        return BenchmarkCaseAssessment(
            semantic_checks=semantic_checks,
            integrity_checks=integrity_checks,
            terminal_shape=shape,
        )

    @staticmethod
    def _resolve_terminal_dataset(
        *,
        snapshot: Any,
        dataset_service: Any,
        source_dataset_ids: set[str],
        run_dataset_ids: frozenset[str],
    ) -> tuple[Any, pl.DataFrame] | None:
        for message in reversed(list(getattr(snapshot, "messages", []))):
            if enum_value(getattr(message, "kind", None)) != "tool_result":
                continue
            if enum_value(getattr(message, "result_status", None)) != "succeeded":
                continue
            for dataset_id in _result_dataset_ids(getattr(message, "value_payload", None)):
                if dataset_id in source_dataset_ids or dataset_id not in run_dataset_ids:
                    continue
                try:
                    dataset = dataset_service.get_dataset(dataset_id)
                    frame = _load_dataset_frame(dataset)
                except Exception:
                    continue
                return dataset, frame
        return None

    @staticmethod
    def _state_isolated(*, dataset_service: Any, runtime_home: Path, settings_unchanged: bool) -> bool:
        if not settings_unchanged:
            return False
        try:
            root = runtime_home.resolve()
            return all(
                is_within(Path(dataset.source_path), root)
                for dataset in dataset_service.list_datasets()
            )
        except Exception:
            return False


def _cleaning_checks(*, source_frame: pl.DataFrame, output_frame: pl.DataFrame) -> tuple[OutcomeCheck, ...]:
    if source_frame.height < 2 or source_frame.width != output_frame.width:
        return (
            OutcomeCheck("header_promoted", False, "incompatible_source_or_output_schema"),
            OutcomeCheck("report_row_removed", False, "incompatible_source_or_output_schema"),
            OutcomeCheck("header_row_removed", False, "incompatible_source_or_output_schema"),
            OutcomeCheck("exact_duplicates_removed", False, "incompatible_source_or_output_schema"),
            OutcomeCheck("expected_shape", False, "unexpected_terminal_shape"),
            OutcomeCheck("business_rows_preserved", False, "incompatible_source_or_output_schema"),
        )

    expected_headers = tuple(_cell_text(value) for value in source_frame.row(1))
    header_promoted = tuple(output_frame.columns) == expected_headers
    output_hashes = _row_hashes(output_frame)
    source_business_hashes = _row_hashes(source_frame.slice(2))
    report_row_hash = _row_hashes(source_frame.slice(0, 1))[0]
    header_row_hash = _row_hashes(source_frame.slice(1, 1))[0]
    output_hash_set = set(output_hashes.to_list())
    duplicates_removed = output_hashes.n_unique() == output_frame.height
    expected_shape = (int(output_frame.height), int(output_frame.width)) == EXPECTED_SHAPE
    business_rows_preserved = source_business_hashes.unique().sort().equals(output_hashes.unique().sort())
    return (
        OutcomeCheck("header_promoted", header_promoted, "expected_headers" if header_promoted else "headers_not_promoted"),
        OutcomeCheck("report_row_removed", report_row_hash not in output_hash_set, "report_row_absent" if report_row_hash not in output_hash_set else "report_row_retained"),
        OutcomeCheck("header_row_removed", header_row_hash not in output_hash_set, "header_row_absent" if header_row_hash not in output_hash_set else "header_row_retained"),
        OutcomeCheck("exact_duplicates_removed", duplicates_removed, "no_exact_duplicates" if duplicates_removed else "exact_duplicates_retained"),
        OutcomeCheck("expected_shape", expected_shape, "expected_terminal_shape" if expected_shape else "unexpected_terminal_shape"),
        OutcomeCheck("business_rows_preserved", business_rows_preserved, "business_rows_match" if business_rows_preserved else "business_rows_differ"),
    )


def _row_hashes(frame: pl.DataFrame) -> pl.Series:
    normalized = frame.select(
        [_normalized_value_expression(column).alias(column) for column in frame.columns]
    )
    return normalized.hash_rows()


def _normalized_value_expression(column: str) -> pl.Expr:
    text = pl.col(column).cast(pl.Utf8, strict=False).str.strip_chars()
    return pl.when(pl.col(column).is_null() | text.is_in(["", "--"])).then(None).otherwise(text)


def _result_dataset_ids(value: Any) -> tuple[str, ...]:
    candidates: list[str] = []
    if isinstance(value, dict):
        direct = value.get("dataset_id")
        if isinstance(direct, str) and direct.strip():
            candidates.append(direct.strip())
        multiple = value.get("dataset_ids")
        if isinstance(multiple, list):
            candidates.extend(item.strip() for item in multiple if isinstance(item, str) and item.strip())
    elif isinstance(value, str):
        metadata = value.split("\n\n", 1)[0]
        candidates.extend(match.group(1) for match in _DATASET_ID_LINE.finditer(metadata))
    return tuple(dict.fromkeys(candidates))


def _load_dataset_frame(dataset: Any) -> pl.DataFrame:
    return load_tabular_frame(Path(dataset.source_path), dataset.source_format)


def _cell_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _completion_summary(passed: bool) -> str:
    return "canonical_assistant_completion" if passed else "not_a_terminal_assistant_completion"


def _source_summary(passed: bool) -> str:
    return "external_and_registered_source_unchanged" if passed else "source_changed_or_unreadable"


def _isolation_summary(passed: bool) -> str:
    return "state_confined_to_cell_runtime" if passed else "state_or_settings_escaped_cell_runtime"


def test_cleaning_april(agent_harness_benchmark) -> None:
    """Measure the public cleaning outcome with an explicitly supplied source."""

    agent_harness_benchmark.run(
        AprilDineInSalesCleaningCase(agent_harness_benchmark.require_source())
    )
