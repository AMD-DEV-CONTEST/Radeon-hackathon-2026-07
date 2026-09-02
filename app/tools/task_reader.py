"""Task reader — reads task records from XLSX or CSV files (Phase C).

Each task row must provide at minimum: title, assignee.
Optional columns: deadline, priority, acceptance criteria, original source.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class TaskRecord:
    """A single task read from an input spreadsheet or CSV."""

    title: str
    assignee: str
    deadline: str = ""
    priority: str = "normal"
    acceptance_criteria: str = ""
    original_source: str = ""
    raw_row: dict = field(default_factory=dict, repr=False)

    @property
    def display_line(self) -> str:
        parts = [f"[{self.priority}] {self.title}", f"负责人: {self.assignee}"]
        if self.deadline:
            parts.append(f"截止: {self.deadline}")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def read_tasks(path: str | Path) -> List[TaskRecord]:
    """Read task rows from an XLSX or CSV file.

    Supported columns (case-insensitive, Chinese / English aliases):

    * title / 任务名称 / 标题
    * assignee / 负责人 / 责任人 / 处理人
    * deadline / 截止日期 / 截止时间 / due_date
    * priority / 优先级 / 重要程度
    * acceptance_criteria / 验收标准 / 验收条件
    * original_source / 来源 / 出处

    Returns a list of :class:`TaskRecord` objects (empty list when no
    recognised column is found).
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Task file not found: {path}")

    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        return _read_xlsx(path)
    if suffix in (".csv", ".tsv", ".txt"):
        delimiter = "\t" if suffix == ".tsv" else ","
        return _read_csv(path, delimiter=delimiter)

    raise ValueError(f"Unsupported task file format: {suffix}")


# ---------------------------------------------------------------------------
# Internal readers
# ---------------------------------------------------------------------------


def _read_xlsx(path: Path) -> List[TaskRecord]:
    try:
        import openpyxl  # type: ignore[import-untyped]
    except ImportError:
        raise ImportError(
            "openpyxl is required for XLSX reading. "
            "Install it with: pip install openpyxl"
        )

    wb = None
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []

        header = [str(c).strip() if c is not None else "" for c in rows[0]]
        mapping = _build_column_mapping(header)

        tasks: List[TaskRecord] = []
        for row in rows[1:]:
            record = _build_record(mapping, row)
            if record is not None:
                tasks.append(record)
        return tasks
    finally:
        if wb is not None:
            wb.close()


def _read_csv(path: Path, delimiter: str) -> List[TaskRecord]:
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh, delimiter=delimiter)
        rows = list(reader)
    if not rows:
        return []

    header = [c.strip() for c in rows[0]]
    mapping = _build_column_mapping(header)

    tasks: List[TaskRecord] = []
    for row in rows[1:]:
        record = _build_record(mapping, row)
        if record is not None:
            tasks.append(record)
    return tasks


# ---------------------------------------------------------------------------
# Column mapping
# ---------------------------------------------------------------------------

_COLUMN_ALIASES: dict[str, list[str]] = {
    "title": ["title", "任务名称", "标题", "task_name", "任务"],
    "assignee": ["assignee", "负责人", "责任人", "处理人", "owner", "指派给"],
    "deadline": ["deadline", "截止日期", "截止时间", "due_date", "ddl", "期限", "计划完成"],
    "priority": ["priority", "优先级", "重要程度", "紧急程度", "urgent"],
    "acceptance_criteria": [
        "acceptance_criteria",
        "验收标准",
        "验收条件",
        "完成标准",
        "criteria",
        "criteria",
    ],
    "original_source": ["original_source", "来源", "出处", "source", "文档来源", "原始来源"],
}


def _build_column_mapping(header: list[str]) -> dict[str, int]:
    """Map canonical field name → column index."""
    mapping: dict[str, int] = {}
    lower_h = [h.lower() for h in header]
    for canonical, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            try:
                idx = lower_h.index(alias.lower())
                mapping[canonical] = idx
                break
            except ValueError:
                continue
    print(f"[task_reader] Detected columns -> fields: {mapping}")
    return mapping


def _build_record(mapping: dict[str, int], row: tuple) -> Optional[TaskRecord]:
    if "title" not in mapping:
        # Without a title we cannot form a meaningful task
        return None
    title = str(row[mapping["title"]]).strip() if mapping["title"] < len(row) else ""
    if not title or title in ("", "nan", "None"):
        return None

    def _get(field: str, default: str = "") -> str:
        idx = mapping.get(field)
        if idx is None or idx >= len(row):
            return default
        return str(row[idx]).strip() if row[idx] is not None else default

    assignee = _get("assignee")
    if not assignee:
        # Task without an assignee is still valid but logged
        logger.warning("Task '%s' has no assignee — skipping", title)
        return None

    return TaskRecord(
        title=title,
        assignee=assignee,
        deadline=_get("deadline"),
        priority=_get("priority", "normal"),
        acceptance_criteria=_get("acceptance_criteria"),
        original_source=_get("original_source"),
        raw_row={
            "title": title,
            "assignee": assignee,
            "deadline": _get("deadline"),
            "priority": _get("priority", "normal"),
            "acceptance_criteria": _get("acceptance_criteria"),
            "original_source": _get("original_source"),
        },
    )
