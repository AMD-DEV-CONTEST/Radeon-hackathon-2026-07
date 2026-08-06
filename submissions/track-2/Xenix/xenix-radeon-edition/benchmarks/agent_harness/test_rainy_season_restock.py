"""Outcome oracle for applying a Knowledge Library rule to inventory data."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re
import time
import unicodedata
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
    is_within,
    sha256_file,
)
from ._infra.contracts import (
    BenchmarkCaseAssessment,
    BenchmarkCaseContext,
    BenchmarkCasePreparationServices,
    BenchmarkCaseServices,
    BenchmarkInputError,
    OutcomeCheck,
)


CASE_ID = "knowledge.rainy_season_restock"
_FIXTURE_DIRECTORY = Path(__file__).resolve().parent / "fixtures"
_INVENTORY_PATH = _FIXTURE_DIRECTORY / "rainy_season_inventory.csv"
_RULE_PATH = _FIXTURE_DIRECTORY / "rainy_season_restock_rule.txt"
_INVENTORY_SIZE = 201
_INVENTORY_SHA256 = "6DB0E521DB7FF9867F23BDD4123F0E0E0DAF603EA845381B40F0DB3B462B79BC"
_RULE_SIZE = 316
_RULE_SHA256 = "43A1BB0D8CCA73C2348017597754965F6C6F3276D45B31749E5082051D8E90BC"
_EXPECTED_RESTOCK = {"U100": 130.0, "R200": 75.0}


pytestmark = pytest.mark.agent_harness_live


class RainySeasonRestockCase:
    """Apply one imported business rule without prescribing the Agent's route."""

    case_id = CASE_ID

    def __init__(
        self,
        inventory_path: Path = _INVENTORY_PATH,
        rule_path: Path = _RULE_PATH,
    ) -> None:
        self.inventory_path = inventory_path
        self.rule_path = rule_path

    def validate_input(self) -> str:
        inventory_digest = _validate_fixture(
            self.inventory_path,
            expected_size=_INVENTORY_SIZE,
            expected_sha256=_INVENTORY_SHA256,
        )
        rule_digest = _validate_fixture(
            self.rule_path,
            expected_size=_RULE_SIZE,
            expected_sha256=_RULE_SHA256,
        )
        return sha256(f"{inventory_digest}:{rule_digest}".encode("ascii")).hexdigest().upper()

    def prepare(self, *, services: BenchmarkCasePreparationServices) -> None:
        imported = services.knowledge_import.import_file(self.rule_path, timeout=60.0)
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            status = services.knowledge_derivation.status_for_import(imported.import_id)
            if status is not None and status.status == "succeeded":
                if status.phase != "completed":
                    raise BenchmarkInputError("knowledge_rule_not_retrieval_ready")
                task_id = services.knowledge_index.enqueue_rebuild(
                    ("text_vector",),
                    trigger="manual",
                )
                index_result = services.knowledge_index.rebuild_now(task_id)
                if index_result.status != "succeeded":
                    raise BenchmarkInputError("knowledge_vector_index_failed")
                return
            if status is not None and status.status == "failed":
                raise BenchmarkInputError("knowledge_rule_derivation_failed")
            time.sleep(0.02)
        raise BenchmarkInputError("knowledge_rule_derivation_timeout")

    def build_submission(self, *, thread_id: str, fq_model_key: str) -> SubmitUserTurnInput:
        return SubmitUserTurnInput(
            thread_id=thread_id,
            text=(
                "请用 semantic 模式检索知识库中与‘季节性采购边界’含义相关的经验，"
                "并基于这份库存表创建需要补货的商品清单。"
                "新数据集只保留需要补货的商品，并包含 SKU 和补货数量。"
                "最终答复请简要说明采用的补货规则，并列出需要补货的 SKU 与数量。"
            ),
            source_attachments=[
                SourceAttachmentInput(file_path=str(self.inventory_path.resolve()))
            ],
            fq_model_key=fq_model_key,
        )

    def capture_source_state(
        self,
        *,
        snapshot: Any,
        services: BenchmarkCaseServices,
    ) -> AttachedSourceState:
        return capture_attached_source_state(
            source_path=self.inventory_path,
            snapshot=snapshot,
            services=services,
        )

    def assess(self, *, context: BenchmarkCaseContext) -> BenchmarkCaseAssessment:
        source_state = context.source_state
        source_dataset_ids = (
            set(source_state.source_dataset_ids)
            if isinstance(source_state, AttachedSourceState)
            else set()
        )
        terminal, derived_seen = _resolve_exact_derived_dataset(
            context=context,
            source_dataset_ids=source_dataset_ids,
        )
        completed = canonical_completion(context.snapshot)
        grounded_answer = _grounded_final_answer_observed(context.snapshot)
        source_unchanged = (
            attached_source_unchanged(
                source_path=self.inventory_path,
                source_state=source_state,
                services=context.services,
            )
            if isinstance(source_state, AttachedSourceState)
            else False
        )
        dataset_and_settings_isolated = _dataset_and_settings_are_isolated(context)
        exact_rows = terminal is not None
        semantic_checks = (
            OutcomeCheck(
                "grounded_final_answer",
                grounded_answer,
                "rule_and_restock_actions_reported"
                if grounded_answer
                else "final_answer_missing_rule_or_restock_actions",
            ),
            OutcomeCheck(
                "derived_dataset_created",
                derived_seen,
                "source_linked_derived_dataset"
                if derived_seen
                else "no_source_linked_derived_dataset",
            ),
            OutcomeCheck(
                "exact_restock_rows",
                exact_rows,
                "expected_sku_quantity_mapping" if exact_rows else "unexpected_restock_rows",
            ),
        )
        integrity_checks = (
            OutcomeCheck(
                "canonical_completion",
                completed,
                "canonical_assistant_completion"
                if completed
                else "not_a_terminal_assistant_completion",
            ),
            OutcomeCheck(
                "source_unchanged",
                source_unchanged,
                "external_and_registered_source_unchanged"
                if source_unchanged
                else "source_changed_or_unreadable",
            ),
            OutcomeCheck(
                "dataset_and_settings_isolated",
                dataset_and_settings_isolated,
                "dataset_paths_and_settings_confined_to_cell_runtime"
                if dataset_and_settings_isolated
                else "dataset_path_or_settings_escaped_cell_runtime",
            ),
        )
        return BenchmarkCaseAssessment(
            semantic_checks=semantic_checks,
            integrity_checks=integrity_checks,
            terminal_shape=(terminal.height, terminal.width) if terminal is not None else None,
        )


def _validate_fixture(path: Path, *, expected_size: int, expected_sha256: str) -> str:
    if not path.is_file():
        raise BenchmarkInputError("missing_fixture")
    if path.stat().st_size != expected_size:
        raise BenchmarkInputError("fixture_size_mismatch")
    digest = sha256_file(path)
    if digest != expected_sha256:
        raise BenchmarkInputError("fixture_hash_mismatch")
    return digest


def _resolve_exact_derived_dataset(
    *,
    context: BenchmarkCaseContext,
    source_dataset_ids: set[str],
) -> tuple[pl.DataFrame | None, bool]:
    derived_seen = False
    for dataset in context.services.datasets.list_datasets():
        if (
            dataset.id not in context.run_dataset_ids
            or dataset.derived_from_dataset_id not in source_dataset_ids
        ):
            continue
        try:
            frame = load_tabular_frame(Path(dataset.source_path), dataset.source_format)
        except Exception:
            continue
        derived_seen = True
        if _contains_exact_restock_mapping(frame):
            return frame, True
    return None, derived_seen


def _contains_exact_restock_mapping(frame: pl.DataFrame) -> bool:
    if frame.height != len(_EXPECTED_RESTOCK) or frame.width < 2:
        return False
    rows = frame.to_dicts()
    for sku_column in frame.columns:
        skus = [str(row.get(sku_column) or "").strip() for row in rows]
        if set(skus) != set(_EXPECTED_RESTOCK) or len(set(skus)) != len(skus):
            continue
        for quantity_column in frame.columns:
            if quantity_column == sku_column:
                continue
            try:
                actual = {
                    sku: float(row[quantity_column])
                    for sku, row in zip(skus, rows, strict=True)
                }
            except (KeyError, TypeError, ValueError):
                continue
            if actual == _EXPECTED_RESTOCK:
                return True
    return False


def _grounded_final_answer_observed(snapshot: Any | None) -> bool:
    messages = list(getattr(snapshot, "messages", [])) if snapshot is not None else []
    if not messages:
        return False
    terminal = messages[-1]
    if str(getattr(getattr(terminal, "kind", None), "value", "")) != "assistant":
        return False
    text = _normalized_answer_text(getattr(terminal, "text", ""))
    if not text:
        return False

    rainwear_only = _rainwear_scope_observed(text)
    three_week_demand = _three_week_target_observed(text)
    inventory_rule = _inventory_rule_observed(text)
    return (
        rainwear_only
        and three_week_demand
        and inventory_rule
        and _sku_quantity_pair_observed(text, "U100", 130)
        and _sku_quantity_pair_observed(text, "R200", 75)
    )


def _normalized_answer_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).upper()
    text = text.translate(
        str.maketrans({
            "−": "-",
            "‐": "-",
            "‑": "-",
            "‒": "-",
            "–": "-",
            "—": "-",
            "﹘": "-",
        })
    )
    return re.sub(r"\s+", "", text)


def _three_week_target_observed(text: str) -> bool:
    if re.search(r"(?:3|三)周(?:平均|均)?(?:需求|销量|流出量)", text):
        return True
    weekly_metric = (
        r"(?:周均(?:需求|销量|流出量)|每周平均(?:需求|销量|流出量)|"
        r"WEEKLY_AVERAGE_(?:DEMAND|SALES|OUTFLOW))"
    )
    multiplier = r"(?:3|三)(?:倍)?"
    return bool(
        re.search(rf"{weekly_metric}.{{0,8}}?{multiplier}", text)
        or re.search(rf"{multiplier}(?:[×*X])?.{{0,8}}?{weekly_metric}", text)
    )


def _rainwear_scope_observed(text: str) -> bool:
    scope_named = "雨具" in text or "遮雨" in text or "防水穿戴" in text
    restriction_named = any(
        term in text
        for term in (
            "仅",
            "只",
            "非雨具",
            "不属于",
            "不属",
            "排除",
            "不进入",
            "不纳入",
            "不在雨季补货范围",
        )
    )
    return scope_named and restriction_named


def _inventory_rule_observed(text: str) -> bool:
    if re.search(
        r"(?:扣除|减去|扣减|减|-)(?:当前|现有)?(?:手头)?(?:库存|数量)",
        text,
    ):
        return True
    if any(term in text for term in ("库存缺口", "补货缺口", "库存差额")):
        return True
    target_named = "目标库存" in text or "目标持有量" in text
    inventory_named = any(
        term in text
        for term in (
            "当前库存",
            "现有库存",
            "手头库存",
            "当前手头数量",
            "手头数量",
        )
    )
    return (target_named and inventory_named) or _floor_at_zero_observed(text)


def _floor_at_zero_observed(text: str) -> bool:
    if any(
        term in text
        for term in (
            "负值归零",
            "负数归零",
            "归零",
            "最低为0",
            "最低为零",
            "最小为0",
            "最小为零",
            "不低于0",
            "不低于零",
            "不得低于0",
            "不得低于零",
            "补货量为0",
            "小于0则不补货",
            "低于0则不补货",
            "小于零则不补货",
            "低于零则不补货",
            "非正数不补货",
            "正数才补货",
            "只保留正数",
            "仅保留正数",
            "取0",
            "取零",
        )
    ):
        return True
    return bool(
        re.search(r"MAX\([^)]{0,80}(?:,0(?:\.0+)?|0(?:\.0+)?,)[^)]*\)", text)
        or re.search(
            r"(?:结果|补货数量|追加件数)(?:≤|<=|小于等于|不大于)0"
            r".{0,24}?(?:不列入|不补货|不予补货|无需补货|库存充足)",
            text,
        )
    )


def _sku_quantity_pair_observed(text: str, sku: str, quantity: int) -> bool:
    amount = rf"{quantity}(?:\.0+)?(?!\d)"
    escaped_sku = re.escape(sku.upper())
    other_skus = "|".join(
        re.escape(candidate)
        for candidate in _EXPECTED_RESTOCK
        if candidate != sku.upper()
    )
    between = rf"(?:(?!(?:{other_skus})).){{0,48}}?" if other_skus else r".{0,48}?"
    return bool(re.search(rf"{escaped_sku}{between}{amount}", text, flags=re.DOTALL))


def _dataset_and_settings_are_isolated(context: BenchmarkCaseContext) -> bool:
    if not context.settings_unchanged:
        return False
    try:
        return all(
            is_within(Path(dataset.source_path), context.runtime_home)
            for dataset in context.services.datasets.list_datasets()
        )
    except Exception:
        return False


def test_rainy_season_restock(agent_harness_benchmark) -> None:
    """Measure the final exact restock Dataset without prescribing a Tool trace."""

    agent_harness_benchmark.run(RainySeasonRestockCase())
