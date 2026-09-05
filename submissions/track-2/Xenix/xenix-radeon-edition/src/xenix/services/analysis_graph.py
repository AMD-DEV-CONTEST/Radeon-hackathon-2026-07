from __future__ import annotations

import copy
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

import pandas as pd
import vl_convert as vlc
import wordcloud as wordcloud_module
from pydantic import ConfigDict, Field
from sqlmodel import SQLModel
from wordcloud import WordCloud

from ..config import AppPaths
from ..exceptions import ValidationError
from ..observability import record_counter, record_histogram, start_span
from .dataset_inspection import detect_source_format, load_dataframe
from .storage.models import DatasetSourceFormat


_DEFAULT_WIDTH = 960
_DEFAULT_HEIGHT = 540
_MIN_WIDTH = 200
_MAX_WIDTH = 1600
_MIN_HEIGHT = 160
_MAX_HEIGHT = 1200
_MAX_SPEC_BYTES = 64 * 1024
_MAX_OUTPUT_BYTES = 2 * 1024 * 1024
_MAX_RENDER_ROWS = 10_000
_MAX_COLUMNS_IN_ERROR = 30
_DATUM_FIELD_RE = re.compile(r"\bdatum(?:\[['\"]([^'\"]+)['\"]\]|\.([A-Za-z_][A-Za-z0-9_]*))")
_STATIC_WARNING_KEYS = {"params"}
_WORDCLOUD_DEFAULT_WIDTH = 720
_WORDCLOUD_DEFAULT_HEIGHT = 420
_WORDCLOUD_DEFAULT_TOP_N = 80
_WORDCLOUD_MIN_TOP_N = 20
_WORDCLOUD_MAX_TOP_N = 80
_WORDCLOUD_MIN_RECOMMENDED_TERMS = 20
_WORDCLOUD_DENSE_TERM_THRESHOLD = 40
_WORDCLOUD_DEFAULT_FONT_SIZE_RANGE = (12, 56)
_WORDCLOUD_DENSE_FONT_SIZE_RANGE = (10, 42)
_WORDCLOUD_DEFAULT_PREFER_HORIZONTAL = 0.85
_WORDCLOUD_MIN_PREFER_HORIZONTAL = 0.8
_WORDCLOUD_MAX_PREFER_HORIZONTAL = 1.0
_WORDCLOUD_DEFAULT_RANK_TIER_PALETTE = ["#1f4e79", "#4f7cac", "#b8c5d6"]
_WORDCLOUD_DEFAULT_SEMANTIC_PALETTE = ["#1f4e79", "#c06c4e", "#6e8b3d", "#2f7d65", "#8f5f3f", "#5078a0"]
_WORDCLOUD_MAX_PALETTE_SIZE = 8
_WORDCLOUD_RANDOM_STATE = 42
_WORDCLOUD_BACKGROUND_COLOR = "white"
_WORDCLOUD_MAX_FAILED_TERM_RATIO = 0.2
_WORDCLOUD_MAX_FAILED_TERM_COUNT = 8
_WORDCLOUD_MARGIN = 1
_WORDCLOUD_TITLE_HEIGHT = 40
_WORDCLOUD_TITLE_Y = 26
_WORDCLOUD_TITLE_FONT_SIZE = 18
_WORDCLOUD_WORD_FIELD = "word"
_WORDCLOUD_COUNT_FIELD = "count"
_WORDCLOUD_COLOR_MODES = {"rank_tier", "field"}
_WORDCLOUD_UNSPECIFIED_GROUP = "unspecified"
_WORDCLOUD_REPAIR_HINTS = [
    "Use data.query or data.transform first to produce a chart-ready frequency table, usually with exact columns `word` and `count`.",
    "For Chinese raw text, segment upstream first. Do not pass raw sentences or rely on countpattern-like tokenization here.",
    "Keep the cloud focused on roughly the Top 20-80 terms and remove blank or meaningless tokens upstream.",
]
_SVG_NS = "http://www.w3.org/2000/svg"
_SVG_STYLE_TAGS = {f"{{{_SVG_NS}}}style", f"{{{_SVG_NS}}}defs", f"{{{_SVG_NS}}}metadata"}
_CJK_RE = re.compile(r"[\u3400-\u9fff]")

ET.register_namespace("", _SVG_NS)


class AnalysisGraphValidationError(ValidationError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        error_details: dict[str, Any] | None = None,
        repair_hints: list[str] | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(
            message,
            error_code=error_code,
            error_details=error_details,
            repair_hints=repair_hints,
            retryable=retryable,
        )


class GraphDatasetInput(SQLModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str
    dataset_name: str
    spec: dict[str, Any] | None = None
    wordcloud_spec: dict[str, Any] | None = None


class GraphDatasetResult(SQLModel):
    output_path: str
    graph_metadata: dict[str, Any] = Field(default_factory=dict)


class _FieldScan(SQLModel):
    referenced_fields: set[str] = Field(default_factory=set)
    generated_fields: set[str] = Field(default_factory=set)


class _PreparedSpec(SQLModel):
    spec: dict[str, Any]
    title: str
    schema_url: str
    rendered_row_count: int
    truncated: bool
    referenced_fields: list[str]
    generated_fields: list[str]
    warnings: list[str]


@dataclass(frozen=True)
class _PreparedWordcloud:
    title: str
    width: int
    height: int
    referenced_fields: list[str]
    rendered_row_count: int
    truncated: bool
    warnings: list[str]
    frequencies: dict[str, float]
    tooltip_by_word: dict[str, str]
    color_by_word: dict[str, str]
    min_font_size: int
    max_font_size: int
    prefer_horizontal: float
    contains_cjk: bool
    color_mode: str
    color_field: str | None
    top_n: int


class AnalysisGraphService:
    def __init__(self, paths: AppPaths) -> None:
        self._paths = paths

    def graph_dataset(self, input_data: GraphDatasetInput) -> GraphDatasetResult:
        started_at = perf_counter()
        with start_span("analysis.graph"):
            source_path = self._resolve_source_path(input_data.source_path)
            frame = self._load_frame(source_path)
            dataset_name = input_data.dataset_name.strip() or source_path.stem
            mode = self._select_graph_mode(input_data)
            if mode == "vegalite":
                result = self._graph_vegalite_dataset(
                    user_spec=self._validate_spec_object(input_data.spec),
                    frame=frame,
                    dataset_name=dataset_name,
                )
            else:
                result = self._graph_wordcloud_dataset(
                    user_spec=self._validate_wordcloud_spec_object(input_data.wordcloud_spec),
                    frame=frame,
                    dataset_name=dataset_name,
                )
            self._record_operation("analysis.graph", started_at)
            return result

    def _select_graph_mode(self, input_data: GraphDatasetInput) -> Literal["vegalite", "wordcloud"]:
        has_spec = input_data.spec is not None
        has_wordcloud_spec = input_data.wordcloud_spec is not None
        if has_spec == has_wordcloud_spec:
            raise ValidationError("analysis.graph requires exactly one of spec or wordcloud_spec.")
        return "vegalite" if has_spec else "wordcloud"

    def _graph_vegalite_dataset(
        self,
        *,
        user_spec: dict[str, Any],
        frame: pd.DataFrame,
        dataset_name: str,
    ) -> GraphDatasetResult:
        spec_json = self._spec_json(user_spec, field_name="spec")
        if len(spec_json.encode("utf-8")) > _MAX_SPEC_BYTES:
            raise ValidationError(f"analysis.graph spec cannot exceed {_MAX_SPEC_BYTES} bytes.")

        prepared = self._prepare_spec(user_spec, frame, dataset_name)
        svg = self._render_vegalite_svg(prepared.spec)
        output_bytes = len(svg.encode("utf-8"))
        if output_bytes > _MAX_OUTPUT_BYTES:
            raise ValidationError(
                "analysis.graph rendered SVG is too large. Reduce chart dimensions, rows, marks, or pre-aggregate data."
            )

        output_path = self._write_svg_output(svg=svg, dataset_name=dataset_name, suffix="vegalite")
        return GraphDatasetResult(
            output_path=str(output_path.resolve()),
            graph_metadata={
                "renderer": "vl-convert-python",
                "renderer_version": getattr(vlc, "__version__", None),
                "spec_format": "vega-lite",
                "schema": prepared.schema_url,
                "dataset_name": dataset_name,
                "title": prepared.title,
                "row_count": int(len(frame.index)),
                "rendered_row_count": prepared.rendered_row_count,
                "truncated": prepared.truncated,
                "referenced_fields": prepared.referenced_fields,
                "generated_fields": prepared.generated_fields,
                "warnings": prepared.warnings,
                "output_bytes": output_bytes,
            },
        )

    def _graph_wordcloud_dataset(
        self,
        *,
        user_spec: dict[str, Any],
        frame: pd.DataFrame,
        dataset_name: str,
    ) -> GraphDatasetResult:
        spec_json = self._spec_json(user_spec, field_name="wordcloud_spec")
        if len(spec_json.encode("utf-8")) > _MAX_SPEC_BYTES:
            raise ValidationError(f"analysis.graph wordcloud_spec cannot exceed {_MAX_SPEC_BYTES} bytes.")

        prepared = self._prepare_wordcloud_request(user_spec, frame, dataset_name)
        svg = self._render_wordcloud_svg(prepared)
        output_bytes = len(svg.encode("utf-8"))
        if output_bytes > _MAX_OUTPUT_BYTES:
            raise ValidationError(
                "analysis.graph rendered SVG is too large. Reduce the canvas size, top_n, or font_size_range."
            )

        output_path = self._write_svg_output(svg=svg, dataset_name=dataset_name, suffix="wordcloud")
        return GraphDatasetResult(
            output_path=str(output_path.resolve()),
            graph_metadata={
                "renderer": "wordcloud",
                "renderer_version": getattr(wordcloud_module, "__version__", None),
                "spec_format": "wordcloud",
                "dataset_name": dataset_name,
                "title": prepared.title,
                "row_count": int(len(frame.index)),
                "rendered_row_count": prepared.rendered_row_count,
                "truncated": prepared.truncated,
                "referenced_fields": prepared.referenced_fields,
                "generated_fields": [],
                "warnings": prepared.warnings,
                "output_bytes": output_bytes,
                "wordcloud_options": {
                    "top_n": prepared.top_n,
                    "prefer_horizontal": prepared.prefer_horizontal,
                    "font_size_range": [prepared.min_font_size, prepared.max_font_size],
                    "color_mode": prepared.color_mode,
                    "color_field": prepared.color_field,
                },
            },
        )

    def _record_operation(self, operation: str, started_at: float) -> None:
        attributes = {"analysis.operation": operation, "status": "succeeded"}
        record_counter("xenix.analysis.operation.count", attributes=attributes)
        record_histogram(
            "xenix.analysis.operation.duration",
            (perf_counter() - started_at) * 1000,
            attributes=attributes,
            unit="ms",
        )

    def _resolve_source_path(self, raw_path: str) -> Path:
        source_path = Path(raw_path).expanduser()
        if not source_path.is_absolute():
            raise ValidationError("Dataset source path must be absolute.")
        if not source_path.exists() or not source_path.is_file():
            raise ValidationError("Dataset source path must point to an existing file.")
        return source_path.resolve()

    def _load_frame(self, source_path: Path) -> pd.DataFrame:
        source_format = detect_source_format(source_path)
        if source_format is DatasetSourceFormat.UNKNOWN:
            raise ValidationError("Only .csv, .parquet, .xlsx, and .xls dataset files are supported.")
        frame = load_dataframe(source_path, source_format).rename(columns=str)
        if len(frame.columns) == 0:
            raise ValidationError("Dataset file must contain at least one column.")
        if len(frame.index) == 0:
            raise ValidationError("Dataset file must contain at least one data row.")
        return frame

    def _validate_spec_object(self, value: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValidationError("analysis.graph spec must be a Vega-Lite object.")
        if not value:
            raise ValidationError("analysis.graph spec cannot be empty.")
        return value

    def _validate_wordcloud_spec_object(self, value: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValidationError("analysis.graph wordcloud_spec must be an object.")
        return value

    def _spec_json(self, spec: dict[str, Any], *, field_name: str) -> str:
        try:
            return json.dumps(spec, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"analysis.graph {field_name} must be JSON-serializable.") from exc

    def _prepare_spec(self, user_spec: dict[str, Any], frame: pd.DataFrame, dataset_name: str) -> _PreparedSpec:
        self._validate_visual_shape(user_spec)
        self._validate_no_wordcloud_transform(user_spec)
        spec = copy.deepcopy(user_spec)
        self._drop_user_data_declarations(spec)
        self._validate_no_external_urls(spec)
        self._validate_dimensions(spec)
        spec.setdefault("width", _DEFAULT_WIDTH)
        spec.setdefault("height", _DEFAULT_HEIGHT)

        columns = [str(column) for column in frame.columns]
        field_scan = self._scan_fields(spec)
        unknown_fields = sorted(field_scan.referenced_fields - set(columns) - field_scan.generated_fields)
        if unknown_fields:
            available = ", ".join(columns[:_MAX_COLUMNS_IN_ERROR])
            if len(columns) > _MAX_COLUMNS_IN_ERROR:
                available += ", ..."
            raise ValidationError(
                "analysis.graph spec references unknown field(s): "
                + ", ".join(unknown_fields)
                + f". Use exact dataset columns. Available columns: {available}."
            )

        row_count = int(len(frame.index))
        truncated = row_count > _MAX_RENDER_ROWS
        render_frame = frame.head(_MAX_RENDER_ROWS) if truncated else frame
        spec.setdefault("$schema", "https://vega.github.io/schema/vega-lite/v5.json")
        spec.setdefault("title", dataset_name)
        spec["data"] = {"values": self._records(render_frame)}
        warnings = self._static_warnings(spec)
        if truncated:
            warnings.append(
                f"Rendered the first {_MAX_RENDER_ROWS} rows from {row_count} rows. "
                "Use data.query or data.transform before graphing if row order, grouping, or sampling affects the conclusion."
            )
        return _PreparedSpec(
            spec=spec,
            title=self._title(spec, dataset_name),
            schema_url=str(user_spec.get("$schema") or ""),
            rendered_row_count=int(len(render_frame.index)),
            truncated=truncated,
            referenced_fields=sorted(field_scan.referenced_fields),
            generated_fields=sorted(field_scan.generated_fields),
            warnings=warnings,
        )

    def _prepare_wordcloud_request(
        self,
        user_spec: dict[str, Any],
        frame: pd.DataFrame,
        dataset_name: str,
    ) -> _PreparedWordcloud:
        unsupported_keys = sorted(
            set(user_spec)
            - {
                "title",
                "word_field",
                "count_field",
                "top_n",
                "width",
                "height",
                "prefer_horizontal",
                "font_size_range",
                "color_mode",
                "color_field",
                "palette",
            }
        )
        if unsupported_keys:
            raise ValidationError(
                "analysis.graph wordcloud_spec does not accept: " + ", ".join(unsupported_keys)
            )
        title = self._optional_title(user_spec.get("title"), dataset_name)
        word_field = self._field_name_option(
            user_spec.get("word_field"),
            field_name="analysis.graph wordcloud_spec.word_field",
            default=_WORDCLOUD_WORD_FIELD,
        )
        count_field = self._field_name_option(
            user_spec.get("count_field"),
            field_name="analysis.graph wordcloud_spec.count_field",
            default=_WORDCLOUD_COUNT_FIELD,
        )
        top_n = self._integer_option(
            user_spec.get("top_n"),
            field_name="analysis.graph wordcloud_spec.top_n",
            minimum=_WORDCLOUD_MIN_TOP_N,
            maximum=_WORDCLOUD_MAX_TOP_N,
            default=_WORDCLOUD_DEFAULT_TOP_N,
        )
        width = self._integer_option(
            user_spec.get("width"),
            field_name="analysis.graph wordcloud_spec.width",
            minimum=_MIN_WIDTH,
            maximum=_MAX_WIDTH,
            default=_WORDCLOUD_DEFAULT_WIDTH,
        )
        height = self._integer_option(
            user_spec.get("height"),
            field_name="analysis.graph wordcloud_spec.height",
            minimum=_MIN_HEIGHT,
            maximum=_MAX_HEIGHT,
            default=_WORDCLOUD_DEFAULT_HEIGHT,
        )
        prefer_horizontal = self._float_option(
            user_spec.get("prefer_horizontal"),
            field_name="analysis.graph wordcloud_spec.prefer_horizontal",
            minimum=_WORDCLOUD_MIN_PREFER_HORIZONTAL,
            maximum=_WORDCLOUD_MAX_PREFER_HORIZONTAL,
            default=_WORDCLOUD_DEFAULT_PREFER_HORIZONTAL,
        )
        color_mode = self._wordcloud_color_mode(user_spec.get("color_mode"))
        color_field = self._optional_field_name(
            user_spec.get("color_field"),
            field_name="analysis.graph wordcloud_spec.color_field",
        )
        if color_mode == "field" and color_field is None:
            self._raise_wordcloud_error(
                "analysis.graph wordcloud_spec.color_mode='field' requires color_field.",
                error_code="wordcloud_color_field_required",
                error_details={"color_mode": color_mode},
            )
        if color_mode != "field" and color_field is not None:
            raise ValidationError(
                "analysis.graph wordcloud_spec.color_field is only allowed when color_mode is 'field'."
            )

        columns = [str(column) for column in frame.columns]
        required_fields = [
            ("word", word_field),
            ("count", count_field),
        ]
        if color_field is not None:
            required_fields.append(("color", color_field))
        self._validate_wordcloud_required_fields(required_fields, columns)

        prepared_frame, warnings, truncated = self._prepare_wordcloud_frame(
            frame=frame,
            word_field=word_field,
            count_field=count_field,
            color_field=color_field,
            top_n=top_n,
        )
        words = prepared_frame[word_field].tolist()
        contains_cjk = any(self._contains_cjk(word) for word in words)
        font_size_range = self._font_size_range_option(
            user_spec.get("font_size_range"),
            words=words,
        )
        palette, palette_warnings = self._wordcloud_palette(
            raw_palette=user_spec.get("palette"),
            color_mode=color_mode,
            category_count=int(prepared_frame[color_field].nunique()) if color_field is not None else 0,
        )
        warnings.extend(palette_warnings)
        frequencies = {
            str(word): float(count)
            for word, count in zip(prepared_frame[word_field].tolist(), prepared_frame[count_field].tolist(), strict=False)
        }
        color_by_word, tooltip_by_word = self._wordcloud_annotations(
            frame=prepared_frame,
            word_field=word_field,
            count_field=count_field,
            color_mode=color_mode,
            color_field=color_field,
            palette=palette,
        )
        return _PreparedWordcloud(
            title=title,
            width=width,
            height=height,
            referenced_fields=sorted(field for _role, field in required_fields),
            rendered_row_count=int(len(prepared_frame.index)),
            truncated=truncated,
            warnings=warnings,
            frequencies=frequencies,
            tooltip_by_word=tooltip_by_word,
            color_by_word=color_by_word,
            min_font_size=font_size_range[0],
            max_font_size=font_size_range[1],
            prefer_horizontal=prefer_horizontal,
            contains_cjk=contains_cjk,
            color_mode=color_mode,
            color_field=color_field,
            top_n=top_n,
        )

    def _validate_visual_shape(self, spec: dict[str, Any]) -> None:
        if "mark" in spec:
            return
        for key in ("layer", "hconcat", "vconcat", "concat"):
            value = spec.get(key)
            if isinstance(value, list) and value:
                return
        for key in ("facet", "repeat"):
            if key in spec and isinstance(spec.get("spec"), dict):
                return
        raise ValidationError("analysis.graph spec must include a Vega-Lite mark, layer, concat, facet, or repeat view.")

    def _validate_no_wordcloud_transform(self, spec: dict[str, Any]) -> None:
        self._validate_no_wordcloud_transform_value(spec)

    def _validate_no_wordcloud_transform_value(self, value: Any) -> None:
        if isinstance(value, dict):
            transforms = value.get("transform")
            if isinstance(transforms, list):
                for transform in transforms:
                    if isinstance(transform, dict) and transform.get("type") == "wordcloud":
                        raise ValidationError(
                            "analysis.graph Vega-Lite specs do not support wordcloud transforms. "
                            "Use wordcloud_spec instead, and prepare the frequency table with data.query or data.transform first."
                        )
            for child in value.values():
                self._validate_no_wordcloud_transform_value(child)
        elif isinstance(value, list):
            for child in value:
                self._validate_no_wordcloud_transform_value(child)

    def _drop_user_data_declarations(self, value: Any, path: str = "spec") -> None:
        if isinstance(value, dict):
            for key in list(value):
                child = value[key]
                child_path = f"{path}.{key}"
                if key == "data":
                    del value[key]
                    continue
                if key == "datasets":
                    del value[key]
                    continue
                self._drop_user_data_declarations(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self._drop_user_data_declarations(child, f"{path}[{index}]")

    def _validate_no_external_urls(self, value: Any, path: str = "spec") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}"
                if key == "url":
                    raise ValidationError(
                        f"analysis.graph does not accept {child_path}. "
                        "External data or resource URLs are not allowed in graph specs."
                    )
                self._validate_no_external_urls(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self._validate_no_external_urls(child, f"{path}[{index}]")

    def _validate_dimensions(self, spec: dict[str, Any]) -> None:
        for key, minimum, maximum in (("width", _MIN_WIDTH, _MAX_WIDTH), ("height", _MIN_HEIGHT, _MAX_HEIGHT)):
            if key not in spec:
                continue
            value = spec[key]
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValidationError(f"analysis.graph spec.{key} must be a number between {minimum} and {maximum}.")
            if value < minimum or value > maximum:
                raise ValidationError(f"analysis.graph spec.{key} must be between {minimum} and {maximum}.")

    def _scan_fields(self, spec: dict[str, Any]) -> _FieldScan:
        scan = _FieldScan()
        self._scan_fields_value(spec, scan)
        return scan

    def _scan_fields_value(self, value: Any, scan: _FieldScan, parent_key: str | None = None) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "field" and isinstance(child, str):
                    normalized = self._normalize_field_reference(child)
                    if normalized is not None:
                        scan.referenced_fields.add(normalized)
                elif key in {"groupby", "fields"} and isinstance(child, list):
                    scan.referenced_fields.update(
                        normalized
                        for item in child
                        if isinstance(item, str)
                        for normalized in [self._normalize_field_reference(item)]
                        if normalized is not None
                    )
                elif key == "as":
                    scan.generated_fields.update(self._as_fields(child))
                elif key in {"filter", "calculate"} and isinstance(child, str):
                    scan.referenced_fields.update(match.group(1) or match.group(2) for match in _DATUM_FIELD_RE.finditer(child))
                self._scan_fields_value(child, scan, key)
        elif isinstance(value, list):
            for child in value:
                self._scan_fields_value(child, scan, parent_key)

    def _normalize_field_reference(self, value: str) -> str | None:
        if value.startswith("datum."):
            return value.removeprefix("datum.")
        if value.startswith("datum["):
            match = _DATUM_FIELD_RE.search(value)
            if match is not None:
                return match.group(1) or match.group(2)
            return None
        return value

    def _as_fields(self, value: Any) -> set[str]:
        if isinstance(value, str):
            return {value}
        if isinstance(value, list):
            return {str(item) for item in value if isinstance(item, str)}
        return set()

    def _static_warnings(self, spec: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        for key in sorted(self._present_keys(spec, _STATIC_WARNING_KEYS)):
            warnings.append(
                f"Vega-Lite '{key}' may not be visible in a static SVG artifact. "
                "The chart was rendered as a static image."
            )
        return warnings

    def _present_keys(self, value: Any, keys: set[str]) -> set[str]:
        present: set[str] = set()
        if isinstance(value, dict):
            for key, child in value.items():
                if key in keys:
                    present.add(key)
                present.update(self._present_keys(child, keys))
        elif isinstance(value, list):
            for child in value:
                present.update(self._present_keys(child, keys))
        return present

    def _render_vegalite_svg(self, spec: dict[str, Any]) -> str:
        console_guard = self._allocate_hidden_console_for_packaged_windows()
        try:
            svg = vlc.vegalite_to_svg(self._spec_json(spec, field_name="spec"))
        except Exception as exc:
            raise ValidationError(
                "analysis.graph could not render the Vega-Lite spec. "
                "Check marks, encodings, transforms, and field types, then retry with a simpler valid Vega-Lite chart."
            ) from exc
        finally:
            if console_guard is not None:
                console_guard.FreeConsole()
        if not isinstance(svg, str) or not svg.lstrip().startswith("<svg"):
            raise ValidationError("analysis.graph renderer did not return a valid SVG image.")
        if "ERROR" in svg:
            raise ValidationError("analysis.graph renderer returned a Vega-Lite error SVG. Simplify the spec and retry.")
        return self._normalize_svg_for_qt(svg)

    def _normalize_svg_for_qt(self, svg: str) -> str:
        try:
            root = ET.fromstring(svg)
        except ET.ParseError as exc:
            raise ValidationError("analysis.graph renderer did not return a valid SVG image.") from exc
        self._remove_empty_path_elements(root)
        return self._serialize_svg(root)

    def _remove_empty_path_elements(self, parent: ET.Element) -> None:
        for child in list(parent):
            self._remove_empty_path_elements(child)
            if self._is_empty_path_element(child):
                parent.remove(child)

    def _is_empty_path_element(self, element: ET.Element) -> bool:
        tag_name = element.tag.rsplit("}", 1)[-1]
        if tag_name != "path":
            return False
        return not str(element.attrib.get("d") or "").strip()

    def _render_wordcloud_svg(self, prepared: _PreparedWordcloud) -> str:
        font_path = self._resolve_wordcloud_font_path(prepared.contains_cjk)
        color_func = lambda word, *args, **kwargs: prepared.color_by_word.get(str(word), _WORDCLOUD_DEFAULT_RANK_TIER_PALETTE[-1])
        try:
            cloud = WordCloud(
                width=prepared.width,
                height=prepared.height,
                background_color=_WORDCLOUD_BACKGROUND_COLOR,
                prefer_horizontal=prepared.prefer_horizontal,
                min_font_size=prepared.min_font_size,
                max_font_size=prepared.max_font_size,
                font_path=str(font_path) if font_path is not None else None,
                color_func=color_func,
                random_state=_WORDCLOUD_RANDOM_STATE,
                margin=_WORDCLOUD_MARGIN,
                collocations=False,
                normalize_plurals=False,
            )
            cloud.generate_from_frequencies(prepared.frequencies)
        except Exception as exc:
            self._raise_wordcloud_error(
                "analysis.graph could not render the wordcloud.",
                error_code="wordcloud_render_failed",
                error_details={
                    "width": prepared.width,
                    "height": prepared.height,
                    "top_n": prepared.top_n,
                },
                repair_hints=[
                    "Reduce top_n or long labels when the cloud is too dense.",
                    "Use the denser font_size_range [10, 42] when terms are many or labels are long.",
                ],
            )
            raise AssertionError("unreachable") from exc

        layout = getattr(cloud, "layout_", []) or []
        visible_terms = len(layout)
        total_terms = len(prepared.frequencies)
        if visible_terms == 0:
            self._raise_wordcloud_error(
                "analysis.graph wordcloud rendered no visible terms.",
                error_code="wordcloud_rendered_no_terms",
                error_details={"visible_terms": 0, "total_terms": total_terms},
            )
        failed_terms = max(0, total_terms - visible_terms)
        minimum_readable_terms = min(total_terms, _WORDCLOUD_MIN_RECOMMENDED_TERMS)
        if (
            visible_terms < minimum_readable_terms
            and failed_terms > _WORDCLOUD_MAX_FAILED_TERM_COUNT
            and failed_terms / max(total_terms, 1) > _WORDCLOUD_MAX_FAILED_TERM_RATIO
        ):
            self._raise_wordcloud_error(
                "analysis.graph wordcloud could not place enough terms.",
                error_code="wordcloud_term_placement_failed",
                error_details={
                    "visible_terms": visible_terms,
                    "failed_terms": failed_terms,
                    "total_terms": total_terms,
                },
                repair_hints=[
                    "Reduce top_n or enlarge width and height before retrying.",
                    "Use shorter labels or pre-aggregate similar variants upstream.",
                ],
            )

        try:
            svg = cloud.to_svg(embed_font=False)
            svg = self._inject_wordcloud_tooltips(svg, prepared.tooltip_by_word)
            svg = self._add_wordcloud_title(
                svg=svg,
                title=prepared.title,
                width=prepared.width,
                height=prepared.height,
            )
        except Exception as exc:
            self._raise_wordcloud_error(
                "analysis.graph rendered the wordcloud layout but could not finalize the SVG.",
                error_code="wordcloud_svg_finalize_failed",
                retryable=False,
            )
            raise AssertionError("unreachable") from exc

        if not isinstance(svg, str) or not svg.lstrip().startswith("<svg"):
            raise ValidationError("analysis.graph renderer did not return a valid SVG image.")
        return svg

    def _inject_wordcloud_tooltips(self, svg: str, tooltip_by_word: dict[str, str]) -> str:
        root = ET.fromstring(svg)
        for element in root.iter(f"{{{_SVG_NS}}}text"):
            word = (element.text or "").strip()
            if not word or word not in tooltip_by_word:
                continue
            element.text = None
            title = ET.Element(f"{{{_SVG_NS}}}title")
            title.text = tooltip_by_word[word]
            title.tail = word
            element.insert(0, title)
        return self._serialize_svg(root)

    def _add_wordcloud_title(self, *, svg: str, title: str, width: int, height: int) -> str:
        root = ET.fromstring(svg)
        content_group = ET.Element(f"{{{_SVG_NS}}}g", {"transform": f"translate(0,{_WORDCLOUD_TITLE_HEIGHT})"})
        content_children = [child for child in list(root) if child.tag not in _SVG_STYLE_TAGS]
        for child in content_children:
            root.remove(child)
            if self._is_wordcloud_background_rect(child):
                continue
            content_group.append(child)

        total_height = height + _WORDCLOUD_TITLE_HEIGHT
        root.set("height", str(total_height))
        root.set("viewBox", f"0 0 {width} {total_height}")

        insertion_index = len(list(root))
        for index, child in enumerate(list(root)):
            if child.tag not in _SVG_STYLE_TAGS:
                insertion_index = index
                break

        background = ET.Element(
            f"{{{_SVG_NS}}}rect",
            {
                "width": "100%",
                "height": "100%",
                "style": f"fill:{_WORDCLOUD_BACKGROUND_COLOR}",
            },
        )
        title_element = ET.Element(
            f"{{{_SVG_NS}}}text",
            {
                "x": str(width // 2),
                "y": str(_WORDCLOUD_TITLE_Y),
                "text-anchor": "middle",
                "font-size": str(_WORDCLOUD_TITLE_FONT_SIZE),
                "font-weight": "600",
                "style": "fill:#172033",
            },
        )
        title_element.text = title
        root.insert(insertion_index, background)
        root.insert(insertion_index + 1, title_element)
        root.append(content_group)
        return self._serialize_svg(root)

    def _serialize_svg(self, root: ET.Element) -> str:
        # XML libraries loaded by optional document runtimes may replace the
        # process-wide ElementTree prefix for SVG. Reassert the public artifact
        # contract at the serialization boundary instead of relying on import order.
        ET.register_namespace("", _SVG_NS)
        return ET.tostring(root, encoding="unicode")

    def _is_wordcloud_background_rect(self, element: ET.Element) -> bool:
        if element.tag != f"{{{_SVG_NS}}}rect":
            return False
        width = str(element.attrib.get("width") or "").strip()
        height = str(element.attrib.get("height") or "").strip()
        if width != "100%" or height != "100%":
            return False
        style = str(element.attrib.get("style") or "").replace(" ", "").lower()
        if f"fill:{_WORDCLOUD_BACKGROUND_COLOR}".lower() in style:
            return True
        fill = str(element.attrib.get("fill") or "").strip().lower()
        return fill == _WORDCLOUD_BACKGROUND_COLOR.lower()

    def _write_svg_output(self, *, svg: str, dataset_name: str, suffix: str) -> Path:
        output_dir = self._paths.artifacts / "analysis" / "graphs"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{self._slug(dataset_name)}-{suffix}-{uuid4().hex[:12]}.svg"
        output_path.write_text(svg, encoding="utf-8")
        return output_path

    def _validate_wordcloud_required_fields(
        self,
        required_fields: list[tuple[str, str]],
        available_columns: list[str],
    ) -> None:
        missing_fields = [(role, field) for role, field in required_fields if field not in available_columns]
        if not missing_fields:
            return
        role, missing_field = missing_fields[0]
        self._raise_wordcloud_error(
            f"analysis.graph wordcloud_spec {role} field '{missing_field}' was not found in the dataset.",
            error_code=f"wordcloud_{role}_field_missing",
            error_details={
                "requested_field": missing_field,
                "available_columns": available_columns[:_MAX_COLUMNS_IN_ERROR],
            },
        )

    def _prepare_wordcloud_frame(
        self,
        *,
        frame: pd.DataFrame,
        word_field: str,
        count_field: str,
        color_field: str | None,
        top_n: int,
    ) -> tuple[pd.DataFrame, list[str], bool]:
        warnings: list[str] = []
        prepared = pd.DataFrame()
        prepared[word_field] = frame[word_field].where(pd.notna(frame[word_field]), "").astype(str).str.strip()
        prepared[count_field] = pd.to_numeric(frame[count_field], errors="coerce")
        if color_field is not None:
            prepared[color_field] = frame[color_field].where(pd.notna(frame[color_field]), "").astype(str).str.strip()
            blank_groups = int(prepared[color_field].eq("").sum())
            if blank_groups:
                prepared.loc[prepared[color_field].eq(""), color_field] = _WORDCLOUD_UNSPECIFIED_GROUP
                warnings.append(
                    f"Wordcloud filled {blank_groups} blank `{color_field}` values as `{_WORDCLOUD_UNSPECIFIED_GROUP}`."
                )

        valid_mask = prepared[word_field].ne("") & prepared[count_field].notna() & prepared[count_field].gt(0)
        removed_rows = int((~valid_mask).sum())
        if removed_rows:
            warnings.append(f"Wordcloud ignored {removed_rows} rows with blank words or non-positive counts.")

        prepared = prepared.loc[valid_mask].copy()
        if prepared.empty:
            self._raise_wordcloud_error(
                "analysis.graph wordcloud requires at least one non-empty word with a positive count.",
                error_code="wordcloud_no_valid_terms",
                error_details={"word_field": word_field, "count_field": count_field},
            )

        initial_rows = int(len(prepared.index))
        if color_field is None:
            prepared = prepared.groupby(word_field, as_index=False, sort=False)[count_field].sum()
            if len(prepared.index) < initial_rows:
                warnings.append("Wordcloud aggregated duplicate words by summed counts.")
        else:
            prepared = prepared.groupby([word_field, color_field], as_index=False, sort=False)[count_field].sum()
            if len(prepared.index) < initial_rows:
                warnings.append("Wordcloud aggregated duplicate word/group rows by summed counts.")
            repeated_words = int(prepared[word_field].duplicated(keep=False).sum())
            if repeated_words:
                warnings.append(
                    "Wordcloud kept the highest-count semantic group when the same word appeared in multiple groups."
                )
            prepared.sort_values(
                by=[count_field, word_field, color_field],
                ascending=[False, True, True],
                kind="mergesort",
                inplace=True,
            )
            prepared = prepared.drop_duplicates(subset=[word_field], keep="first").copy()

        prepared.sort_values(
            by=[count_field, word_field],
            ascending=[False, True],
            kind="mergesort",
            inplace=True,
        )
        total_terms = int(len(prepared.index))
        truncated = total_terms > top_n
        if truncated:
            warnings.append(f"Wordcloud rendered the top {top_n} terms by `{count_field}` for readability.")
            prepared = prepared.head(top_n).copy()
        elif total_terms < _WORDCLOUD_MIN_RECOMMENDED_TERMS:
            warnings.append(
                f"Wordcloud dataset contains only {total_terms} terms. "
                f"Top {_WORDCLOUD_MIN_RECOMMENDED_TERMS}+ usually reads better when the source supports it."
            )
        return prepared, warnings, truncated

    def _wordcloud_annotations(
        self,
        *,
        frame: pd.DataFrame,
        word_field: str,
        count_field: str,
        color_mode: str,
        color_field: str | None,
        palette: list[str],
    ) -> tuple[dict[str, str], dict[str, str]]:
        records = frame.to_dict(orient="records")
        color_by_word: dict[str, str] = {}
        tooltip_by_word: dict[str, str] = {}
        if color_mode == "rank_tier":
            tier_palette = self._wordcloud_rank_tier_palette(palette)
            for index, record in enumerate(records):
                word = str(record[word_field])
                count_text = self._format_wordcloud_count(record[count_field])
                tier = self._wordcloud_color_tier(index=index, term_count=len(records))
                color_by_word[word] = tier_palette[tier]
                tooltip_by_word[word] = f"{word}: {count_text}"
            return color_by_word, tooltip_by_word

        assert color_field is not None
        category_order: list[str] = []
        for record in records:
            category = str(record[color_field])
            if category not in category_order:
                category_order.append(category)
        category_colors = {category: palette[index] for index, category in enumerate(category_order)}
        for record in records:
            word = str(record[word_field])
            category = str(record[color_field])
            count_text = self._format_wordcloud_count(record[count_field])
            color_by_word[word] = category_colors[category]
            tooltip_by_word[word] = f"{word}: {count_text} | {color_field}: {category}"
        return color_by_word, tooltip_by_word

    def _wordcloud_rank_tier_palette(self, palette: list[str]) -> dict[str, str]:
        if len(palette) == 2:
            return {"top": palette[0], "mid": palette[1], "tail": palette[1]}
        return {"top": palette[0], "mid": palette[1], "tail": palette[2]}

    def _wordcloud_color_tier(self, *, index: int, term_count: int) -> str:
        top_cut = max(1, math.ceil(term_count * 0.2))
        mid_cut = max(top_cut, math.ceil(term_count * 0.5))
        if index < top_cut:
            return "top"
        if index < mid_cut:
            return "mid"
        return "tail"

    def _wordcloud_palette(
        self,
        *,
        raw_palette: Any,
        color_mode: str,
        category_count: int,
    ) -> tuple[list[str], list[str]]:
        warnings: list[str] = []
        if raw_palette is None:
            palette = (
                list(_WORDCLOUD_DEFAULT_RANK_TIER_PALETTE)
                if color_mode == "rank_tier"
                else list(_WORDCLOUD_DEFAULT_SEMANTIC_PALETTE)
            )
        else:
            if not isinstance(raw_palette, list) or not raw_palette:
                raise ValidationError("analysis.graph wordcloud_spec.palette must be a non-empty color list.")
            palette = [str(value).strip() for value in raw_palette if str(value).strip()]
            if not palette:
                raise ValidationError("analysis.graph wordcloud_spec.palette must contain non-empty color strings.")
            if len(palette) > _WORDCLOUD_MAX_PALETTE_SIZE:
                raise ValidationError(
                    f"analysis.graph wordcloud_spec.palette cannot exceed {_WORDCLOUD_MAX_PALETTE_SIZE} colors."
                )

        if color_mode == "rank_tier":
            if len(palette) < 2:
                self._raise_wordcloud_error(
                    "analysis.graph wordcloud_spec rank-tier palette needs at least 2 colors.",
                    error_code="wordcloud_palette_too_small",
                    error_details={"palette_size": len(palette)},
                )
            if len(palette) > 3:
                warnings.append("Wordcloud rank-tier coloring used only the first 3 palette colors.")
                palette = palette[:3]
            return palette, warnings

        if category_count > len(palette):
            self._raise_wordcloud_error(
                "analysis.graph wordcloud_spec palette is too small for the semantic color groups.",
                error_code="wordcloud_palette_too_small",
                error_details={"palette_size": len(palette), "category_count": category_count},
                repair_hints=["Reduce category, sentiment, or source groups upstream, or provide a longer palette."],
            )
        return palette, warnings

    def _resolve_wordcloud_font_path(self, contains_cjk: bool) -> Path | None:
        candidates: list[Path] = []
        env_value = str(os.environ.get("XENIX_WORDCLOUD_FONT_PATH") or "").strip()
        if env_value:
            candidates.append(Path(env_value).expanduser())
        candidates.extend(
            [
                Path(r"C:\Windows\Fonts\msyh.ttc"),
                Path(r"C:\Windows\Fonts\simhei.ttf"),
                Path(r"C:\Windows\Fonts\segoeui.ttf"),
                Path(r"C:\Windows\Fonts\arial.ttf"),
                Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
                Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
                Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
                Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttf"),
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                Path("/System/Library/Fonts/PingFang.ttc"),
                Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
                Path("/Library/Fonts/Arial Unicode.ttf"),
            ]
        )
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate
        if contains_cjk:
            self._raise_wordcloud_error(
                "analysis.graph could not find a usable CJK font for the wordcloud renderer.",
                error_code="wordcloud_font_unavailable",
                retryable=False,
            )
        return None

    def _contains_cjk(self, value: str) -> bool:
        return bool(_CJK_RE.search(value))

    def _optional_title(self, value: Any, default: str) -> str:
        if value is None:
            return default
        if not isinstance(value, str):
            raise ValidationError("analysis.graph wordcloud_spec.title must be a string.")
        return value.strip() or default

    def _field_name_option(self, value: Any, *, field_name: str, default: str) -> str:
        if value is None:
            return default
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{field_name} must be a non-empty string.")
        return value.strip()

    def _optional_field_name(self, value: Any, *, field_name: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{field_name} must be a non-empty string when provided.")
        return value.strip()

    def _integer_option(
        self,
        value: Any,
        *,
        field_name: str,
        minimum: int,
        maximum: int,
        default: int,
    ) -> int:
        if value is None:
            return default
        if not isinstance(value, (int, float)) or isinstance(value, bool) or int(value) != value:
            raise ValidationError(f"{field_name} must be an integer between {minimum} and {maximum}.")
        integer = int(value)
        if integer < minimum or integer > maximum:
            raise ValidationError(f"{field_name} must be between {minimum} and {maximum}.")
        return integer

    def _float_option(
        self,
        value: Any,
        *,
        field_name: str,
        minimum: float,
        maximum: float,
        default: float,
    ) -> float:
        if value is None:
            return default
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValidationError(f"{field_name} must be a number between {minimum} and {maximum}.")
        numeric = float(value)
        if numeric < minimum or numeric > maximum:
            raise ValidationError(f"{field_name} must be between {minimum} and {maximum}.")
        return numeric

    def _font_size_range_option(self, value: Any, *, words: list[str]) -> tuple[int, int]:
        if value is None:
            return self._default_wordcloud_font_size_range(words)
        if not isinstance(value, list) or len(value) != 2:
            raise ValidationError("analysis.graph wordcloud_spec.font_size_range must be [min, max].")
        low, high = value
        if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
            raise ValidationError("analysis.graph wordcloud_spec.font_size_range must contain two numbers.")
        if isinstance(low, bool) or isinstance(high, bool):
            raise ValidationError("analysis.graph wordcloud_spec.font_size_range must contain two numbers.")
        low_int = int(low)
        high_int = int(high)
        if not (1 <= low_int < high_int <= 200):
            raise ValidationError("analysis.graph wordcloud_spec.font_size_range must satisfy 1 <= min < max <= 200.")
        return low_int, high_int

    def _wordcloud_color_mode(self, value: Any) -> str:
        if value is None:
            return "rank_tier"
        if not isinstance(value, str):
            raise ValidationError("analysis.graph wordcloud_spec.color_mode must be 'rank_tier' or 'field'.")
        normalized = value.strip()
        if normalized not in _WORDCLOUD_COLOR_MODES:
            raise ValidationError("analysis.graph wordcloud_spec.color_mode must be 'rank_tier' or 'field'.")
        return normalized

    def _default_wordcloud_font_size_range(self, words: list[str]) -> tuple[int, int]:
        longest_word = max((len(word) for word in words), default=0)
        if len(words) >= _WORDCLOUD_DENSE_TERM_THRESHOLD or longest_word >= 8:
            return _WORDCLOUD_DENSE_FONT_SIZE_RANGE
        return _WORDCLOUD_DEFAULT_FONT_SIZE_RANGE

    def _format_wordcloud_count(self, value: Any) -> str:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return str(value)
        if numeric.is_integer():
            return str(int(numeric))
        return f"{numeric:.4g}"

    def _raise_wordcloud_error(
        self,
        message: str,
        *,
        error_code: str,
        error_details: dict[str, Any] | None = None,
        repair_hints: list[str] | None = None,
        retryable: bool = True,
    ) -> None:
        hints = list(_WORDCLOUD_REPAIR_HINTS)
        if repair_hints:
            hints.extend(repair_hints)
        raise AnalysisGraphValidationError(
            message,
            error_code=error_code,
            error_details=error_details,
            repair_hints=hints,
            retryable=retryable,
        )

    def _allocate_hidden_console_for_packaged_windows(self):
        if sys.platform != "win32" or not getattr(sys, "frozen", False):
            return None
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            if kernel32.GetConsoleWindow():
                return None
            if not kernel32.AllocConsole():
                return None
            hwnd = kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
            return kernel32
        except Exception:
            return None

    def _records(self, frame: pd.DataFrame) -> list[dict[str, Any]]:
        cleaned = frame.astype(object).where(pd.notna(frame), None)
        return json.loads(cleaned.to_json(orient="records", date_format="iso"))

    def _title(self, spec: dict[str, Any], dataset_name: str) -> str:
        title = spec.get("title")
        if isinstance(title, str):
            return title.strip() or dataset_name
        if isinstance(title, dict):
            text = title.get("text")
            if isinstance(text, str):
                return text.strip() or dataset_name
        return dataset_name

    def _slug(self, value: str) -> str:
        normalized = "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")
        return normalized or "graph"
