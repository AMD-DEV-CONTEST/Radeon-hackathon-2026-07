from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from policyseal.domain.enums import ContentCategory

_HEADER_CATEGORIES = {
    "supplier id": ContentCategory.SUPPLIER_IDENTITY,
    "supplier name": ContentCategory.SUPPLIER_IDENTITY,
    "contact name": ContentCategory.CONTACT_PERSONAL,
    "work email": ContentCategory.CONTACT_PERSONAL,
    "mobile": ContentCategory.CONTACT_PERSONAL,
    "bank account": ContentCategory.BANK_PAYMENT,
    "quoted price usd": ContentCategory.QUOTE_COMMERCIAL_TERMS,
    "payment terms": ContentCategory.QUOTE_COMMERCIAL_TERMS,
    "internal cost usd": ContentCategory.INTERNAL_COST_BUDGET,
    "target budget usd": ContentCategory.INTERNAL_COST_BUDGET,
    "technical score": ContentCategory.SCORE_RANKING,
    "commercial score": ContentCategory.SCORE_RANKING,
    "rank": ContentCategory.SCORE_RANKING,
    "decision status": ContentCategory.SCORE_RANKING,
    "internal approval comment": ContentCategory.INTERNAL_OPINION_APPROVAL,
    "negotiation floor usd": ContentCategory.INTERNAL_COST_BUDGET,
    "data owner": ContentCategory.SUPPLIER_IDENTITY,
}


def normalize_header(value: object) -> str:
    return " ".join(str(value).strip().casefold().split())


@dataclass(frozen=True, slots=True)
class XlsxColumn:
    index: int
    header: str
    normalized_header: str
    category: ContentCategory


@dataclass(frozen=True, slots=True)
class XlsxSheetMapping:
    sheet_name: str
    header_row: int
    columns: tuple[XlsxColumn, ...]
    owner_column: int | None

    def column(self, index: int) -> XlsxColumn | None:
        return next((column for column in self.columns if column.index == index), None)


@dataclass(frozen=True, slots=True)
class XlsxWorkbookMapping:
    sheets: tuple[XlsxSheetMapping, ...]

    @property
    def unknown_columns(self) -> tuple[tuple[str, XlsxColumn], ...]:
        return tuple(
            (sheet.sheet_name, column)
            for sheet in self.sheets
            for column in sheet.columns
            if column.category is ContentCategory.UNCLASSIFIED
        )

    def sheet(self, name: str) -> XlsxSheetMapping | None:
        return next((sheet for sheet in self.sheets if sheet.sheet_name == name), None)


def discover_workbook_mapping(workbook: Any) -> XlsxWorkbookMapping:
    sheet_mappings: list[XlsxSheetMapping] = []
    for sheet in workbook.worksheets:
        candidates: list[tuple[int, int]] = []
        for row_index in range(1, min(sheet.max_row, 20) + 1):
            values = [
                sheet.cell(row_index, column).value
                for column in range(1, sheet.max_column + 1)
            ]
            known = sum(
                normalize_header(value) in _HEADER_CATEGORIES
                for value in values
                if value is not None
            )
            if known >= 2:
                candidates.append((known, row_index))
        if not candidates:
            continue
        _, header_row = max(candidates, key=lambda item: (item[0], -item[1]))
        columns: list[XlsxColumn] = []
        owner_column: int | None = None
        for column_index in range(1, sheet.max_column + 1):
            value = sheet.cell(header_row, column_index).value
            if value is None or not str(value).strip():
                continue
            header = str(value).strip()
            normalized = normalize_header(header)
            category = _HEADER_CATEGORIES.get(normalized, ContentCategory.UNCLASSIFIED)
            columns.append(
                XlsxColumn(
                    index=column_index,
                    header=header,
                    normalized_header=normalized,
                    category=category,
                )
            )
            if normalized == "data owner":
                owner_column = column_index
        sheet_mappings.append(
            XlsxSheetMapping(
                sheet_name=sheet.title,
                header_row=header_row,
                columns=tuple(columns),
                owner_column=owner_column,
            )
        )
    return XlsxWorkbookMapping(tuple(sheet_mappings))


def metadata_category(sheet: Any, row: int, column: int) -> ContentCategory:
    left_label = normalize_header(sheet.cell(row, max(1, column - 1)).value or "")
    if left_label in {"decision owner:", "review status:"}:
        return ContentCategory.INTERNAL_OPINION_APPROVAL
    return ContentCategory.GENERAL_BUSINESS
