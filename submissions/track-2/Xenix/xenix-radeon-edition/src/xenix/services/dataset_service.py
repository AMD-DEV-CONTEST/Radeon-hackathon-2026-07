from __future__ import annotations

import csv
import codecs
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import polars as pl
from sqlalchemy.orm import sessionmaker
from sqlmodel import Field, SQLModel, select

from ..config import AppPaths
from ..exceptions import NotFoundError, ValidationError
from .dataset_inspection import (
    DatasetAttachmentMetadata,
    DatasetInspection,
    InspectDatasetInput,
    detect_source_format,
    inspect_attachment_metadata_file,
    inspect_dataset_file,
)
from .storage.models import (
    DatasetColumnBindingRow,
    DatasetImportRow,
    DatasetRow,
    DatasetSourceFormat,
    DatasetWorkbookRow,
    MLTaskRow,
    ProjectRow,
    TrainedModelRow,
)
from .storage.repositories import DatasetRepository, ProjectRepository
from .tabular import (
    TabularSchema,
    TabularRuntimeError,
    apply_tabular_schema,
    load_tabular_frame,
    resolve_tabular_schema_for_loaded_frame,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


LOGGER = logging.getLogger("xenix.services.dataset")


@dataclass(frozen=True)
class _MaterializedDataset:
    row: DatasetRow
    original_file_name: str
    original_source_format: DatasetSourceFormat
    row_count: int
    column_count: int
    preview_columns: list[str]


class RegisterDatasetInput(SQLModel):
    source_path: str
    project_id: str | None = None
    name: str | None = None
    derived_from_dataset_id: str | None = None


class RenameDatasetInput(SQLModel):
    dataset_id: str
    new_name: str


class MaterializeManualApplyCsvInput(SQLModel):
    feature_columns: list[str]
    rows: list[dict[str, str | None]]


class ExportDatasetCopyInput(SQLModel):
    dataset_id: str
    destination_path: str
    csv_encoding: str = "utf-8"


class RegisteredDatasetAttachmentItem(SQLModel):
    dataset_id: str
    name: str
    file_name: str
    source_format: str
    row_count: int
    column_count: int
    preview_columns: list[str]


class RegisteredDatasetAttachment(RegisteredDatasetAttachmentItem):
    datasets: list[RegisteredDatasetAttachmentItem] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class DatasetSourcePresentation:
    """Read-only presentation of the original file behind an imported dataset.

    ``DatasetRow.source_path`` points at app-owned materialized Parquet and is
    intentionally not exposed here.  The source presentation is resolved from
    the ``DatasetImportRow`` provenance instead, so a stale original path can
    only make the local open action unavailable.
    """

    dataset_id: str
    source_group_id: str
    file_name: str
    open_path: str | None
    is_openable: bool


class DatasetService:
    def __init__(self, session_factory: sessionmaker, paths: AppPaths) -> None:
        self._session_factory = session_factory
        self._paths = paths
        self._projects = ProjectRepository()
        self._datasets = DatasetRepository()

    def register_dataset(self, input_data: RegisterDatasetInput) -> DatasetRow:
        return self._register_materialized_datasets(input_data)[0].row

    def _register_materialized_datasets(self, input_data: RegisterDatasetInput) -> list[_MaterializedDataset]:
        source_path = Path(input_data.source_path).expanduser()
        if not source_path.is_absolute():
            raise ValidationError("Dataset source path must be absolute.")
        if not source_path.exists() or not source_path.is_file():
            raise ValidationError("Dataset source path must point to an existing file.")

        source_format = detect_source_format(source_path)
        if source_format is DatasetSourceFormat.UNKNOWN:
            raise ValidationError("Only .csv, .parquet, .xlsx, and .xls dataset files are supported.")

        name = input_data.name.strip() if input_data.name else source_path.stem
        if not name:
            raise ValidationError("Dataset name cannot be empty.")

        frame_specs = self._load_import_frames(source_path, source_format)
        if not frame_specs:
            raise ValidationError("Dataset file must contain at least one non-empty table.")

        with self._session_factory() as session:
            derived_from = None
            if input_data.derived_from_dataset_id:
                derived_from = self._datasets.get(session, input_data.derived_from_dataset_id)
                if derived_from is None:
                    raise NotFoundError(
                        f"Dataset '{input_data.derived_from_dataset_id}' was not found."
                    )
            project_id = self._resolve_project_id(
                session,
                input_data.project_id,
                derived_from=derived_from,
            )
            now = _utc_now()
            import_row: DatasetImportRow | None = None
            workbook_row: DatasetWorkbookRow | None = None
            if derived_from is None:
                import_row = DatasetImportRow(
                    project_id=project_id,
                    original_path=str(source_path.resolve()),
                    original_file_name=source_path.name,
                    source_format=source_format,
                    status="succeeded",
                    created_at=now,
                )
                session.add(import_row)
                session.flush()
                if source_format in {DatasetSourceFormat.XLSX, DatasetSourceFormat.XLS}:
                    workbook_row = DatasetWorkbookRow(
                        import_id=import_row.id,
                        sheet_count=len(frame_specs),
                        engine="polars-calamine",
                        metadata_payload={
                            "sheet_names": [str(spec["sheet_name"]) for spec in frame_specs],
                        },
                        created_at=now,
                    )
                    session.add(workbook_row)
                    session.flush()
            materialized: list[_MaterializedDataset] = []
            written_paths: list[Path] = []
            try:
                for spec in frame_specs:
                    dataset_id = uuid4().hex
                    sheet_name = str(spec["sheet_name"]) if spec.get("sheet_name") is not None else None
                    dataset_name = name
                    if len(frame_specs) > 1 and sheet_name:
                        dataset_name = f"{name} - {sheet_name}"
                    output_path = self._dataset_storage_path(
                        dataset_id,
                        derived=derived_from is not None,
                    )
                    frame = spec["frame"]
                    frame.write_parquet(output_path)
                    written_paths.append(output_path)
                    row = DatasetRow(
                        id=dataset_id,
                        project_id=project_id,
                        name=dataset_name,
                        source_path=str(output_path),
                        source_format=DatasetSourceFormat.PARQUET,
                        import_id=import_row.id if import_row is not None else None,
                        workbook_id=workbook_row.id if workbook_row is not None else None,
                        sheet_name=sheet_name,
                        sheet_index=int(spec["sheet_index"]) if spec.get("sheet_index") is not None else None,
                        copied_from=None,
                        copied_at=None,
                        derived_from_dataset_id=derived_from.id if derived_from else None,
                        ml_task_id=None,
                        created_at=now,
                        updated_at=now,
                    )
                    self._datasets.create(session, row)
                    materialized.append(
                        _MaterializedDataset(
                            row=row,
                            original_file_name=source_path.name,
                            original_source_format=source_format,
                            row_count=int(frame.height),
                            column_count=int(frame.width),
                            preview_columns=[str(column) for column in frame.columns],
                        )
                    )
                session.commit()
            except Exception:
                session.rollback()
                for path in written_paths:
                    path.unlink(missing_ok=True)
                raise
            return materialized

    def inspect_source_file(self, input_data: InspectDatasetInput) -> DatasetInspection:
        source_path = Path(input_data.source_path).expanduser()
        if not source_path.is_absolute():
            raise ValidationError("Dataset source path must be absolute.")
        if not source_path.exists() or not source_path.is_file():
            raise ValidationError("Dataset source path must point to an existing file.")
        try:
            return inspect_dataset_file(source_path)
        except ValidationError:
            raise
        except Exception as exc:  # pragma: no cover - exercised by failure surface
            raise self._dataset_read_failure(
                source_path=source_path,
                operation="inspect_source_file",
                exc=exc,
                message="Unable to read dataset file.",
            ) from exc

    def inspect_attachment_metadata(self, input_data: InspectDatasetInput) -> DatasetAttachmentMetadata:
        source_path = Path(input_data.source_path).expanduser()
        if not source_path.is_absolute():
            raise ValidationError("Dataset source path must be absolute.")
        if not source_path.exists() or not source_path.is_file():
            raise ValidationError("Dataset source path must point to an existing file.")
        try:
            return inspect_attachment_metadata_file(source_path)
        except ValidationError:
            raise
        except Exception as exc:  # pragma: no cover - exercised by failure surface
            raise self._dataset_read_failure(
                source_path=source_path,
                operation="inspect_attachment_metadata",
                exc=exc,
                message="Unable to read dataset file.",
            ) from exc

    def register_dataset_attachment(self, input_data: RegisterDatasetInput) -> RegisteredDatasetAttachment:
        materialized = self._register_materialized_datasets(input_data)
        items = [
            RegisteredDatasetAttachmentItem(
                dataset_id=item.row.id,
                name=item.row.name,
                file_name=item.original_file_name,
                source_format=item.original_source_format.value,
                row_count=item.row_count,
                column_count=item.column_count,
                preview_columns=item.preview_columns,
            )
            for item in materialized
        ]
        first = items[0]
        return RegisteredDatasetAttachment(
            dataset_id=first.dataset_id,
            name=first.name,
            file_name=first.file_name,
            source_format=first.source_format,
            row_count=first.row_count,
            column_count=first.column_count,
            preview_columns=first.preview_columns,
            datasets=items,
        )

    def discard_unreferenced_dataset(self, dataset_id: str) -> bool:
        normalized = dataset_id.strip()
        if not normalized:
            raise ValidationError("Dataset id cannot be empty.")
        with self._session_factory() as session:
            row = self._datasets.get(session, normalized)
            if row is None:
                return False
            if not self._is_discardable_dataset(row):
                raise ValidationError("Dataset is already owned by another workflow and cannot be discarded.")
            if self._has_dataset_references(session, row.id):
                raise ValidationError("Dataset is already referenced and cannot be discarded.")
            source_path = Path(row.source_path)
            self._datasets.delete(session, row)
            session.commit()
            if self._is_service_owned_dataset_path(source_path):
                source_path.unlink(missing_ok=True)
            return True

    def rename_dataset(self, input_data: RenameDatasetInput) -> DatasetRow:
        new_name = input_data.new_name.strip()
        if not new_name:
            raise ValidationError("Dataset name cannot be empty.")

        with self._session_factory() as session:
            row = self._datasets.rename(session, input_data.dataset_id, new_name, _utc_now())
            if row is None:
                raise NotFoundError(f"Dataset '{input_data.dataset_id}' was not found.")
            session.commit()
            return row

    def list_datasets(self, project_id: str | None = None) -> list[DatasetRow]:
        with self._session_factory() as session:
            if project_id is None:
                return self._datasets.list_all(session)
            return self._datasets.list_by_project(session, project_id)

    def list_source_datasets(self, project_id: str | None = None) -> list[DatasetRow]:
        with self._session_factory() as session:
            if project_id is None:
                return self._datasets.list_sources(session)
            return self._datasets.list_source_by_project(session, project_id)

    def list_generated_datasets(self, project_id: str | None = None) -> list[DatasetRow]:
        with self._session_factory() as session:
            if project_id is None:
                return self._datasets.list_generated(session)
            return self._datasets.list_generated_by_project(session, project_id)

    def list_derived_datasets(self, source_dataset_id: str) -> list[DatasetRow]:
        with self._session_factory() as session:
            if self._datasets.get(session, source_dataset_id) is None:
                raise NotFoundError(f"Dataset '{source_dataset_id}' was not found.")
            return self._datasets.list_derived_by_source(session, source_dataset_id)

    def get_dataset(self, dataset_id: str) -> DatasetRow:
        with self._session_factory() as session:
            row = self._datasets.get(session, dataset_id)
            if row is None:
                raise NotFoundError(f"Dataset '{dataset_id}' was not found.")
            return row

    def resolve_dataset_source_presentation(
        self,
        dataset_id: str,
    ) -> DatasetSourcePresentation | None:
        """Resolve bounded source metadata for a dataset without reading data.

        This is deliberately a soft read: deleted datasets/imports, legacy
        rows without import provenance, malformed identifiers and unavailable
        original files simply produce ``None`` or an unopenable presentation.
        In particular, the app-owned Parquet path on ``DatasetRow`` is never
        substituted for the original user-selected source file.
        """

        if not isinstance(dataset_id, str):
            return None
        normalized_id = dataset_id.strip()
        if not normalized_id:
            return None

        try:
            with self._session_factory() as session:
                dataset = self._datasets.get(session, normalized_id)
                if dataset is None:
                    return None

                import_id = dataset.import_id
                if not isinstance(import_id, str) or not import_id.strip():
                    return None
                import_id = import_id.strip()
                imported = session.get(DatasetImportRow, import_id)
                if imported is None:
                    return None

                file_name = imported.original_file_name
                if not isinstance(file_name, str):
                    return None
                file_name = file_name.strip()
                if not file_name:
                    return None

                original_path = imported.original_path
                open_path: str | None = None
                is_openable = False
                if isinstance(original_path, str):
                    original_path = original_path.strip()
                    if original_path:
                        try:
                            candidate = Path(original_path)
                            if candidate.is_absolute() and candidate.is_file():
                                open_path = str(candidate)
                                is_openable = True
                        except (OSError, ValueError, RuntimeError):
                            # A stale or malformed path is a projection-level
                            # availability issue, not a thread-load failure.
                            pass

                return DatasetSourcePresentation(
                    dataset_id=normalized_id,
                    source_group_id=import_id,
                    file_name=file_name,
                    open_path=open_path,
                    is_openable=is_openable,
                )
        except Exception:
            # Historical/partially migrated storage must not make a Thread
            # unreadable merely because source enrichment failed.
            LOGGER.debug(
                "Unable to resolve source presentation for dataset %s.",
                normalized_id,
                exc_info=True,
            )
            return None

    def get_dataset_by_ml_task(self, ml_task_id: str) -> DatasetRow | None:
        with self._session_factory() as session:
            return self._datasets.get_by_ml_task(session, ml_task_id)

    def materialize_manual_apply_csv(self, input_data: MaterializeManualApplyCsvInput) -> Path:
        feature_columns = [column.strip() for column in input_data.feature_columns if column.strip()]
        if not feature_columns:
            raise ValidationError("Manual apply requires at least one feature column.")
        if not input_data.rows:
            raise ValidationError("Manual apply requires at least one row.")

        normalized_rows: list[dict[str, str]] = []
        expected_columns = set(feature_columns)
        for row in input_data.rows:
            if set(row) != expected_columns:
                raise ValidationError("Manual apply rows must match the selected feature columns exactly.")
            normalized_rows.append(
                {
                    column: "" if row.get(column) is None else str(row.get(column, ""))
                    for column in feature_columns
                }
            )

        directory = self._paths.temp / "manual-apply"
        directory.mkdir(parents=True, exist_ok=True)
        csv_path = directory / f"{uuid4().hex}.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=feature_columns)
            writer.writeheader()
            writer.writerows(normalized_rows)
        return csv_path

    def export_dataset_copy(self, input_data: ExportDatasetCopyInput) -> Path:
        destination_path = Path(input_data.destination_path).expanduser()
        if not destination_path.is_absolute():
            raise ValidationError("Export destination path must be absolute.")

        dataset = self.get_dataset(input_data.dataset_id)
        source_path = Path(dataset.source_path)
        if not source_path.exists() or not source_path.is_file():
            raise ValidationError("Dataset source file is missing.")

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_suffix = destination_path.suffix.lower()
        if destination_suffix not in {".csv", ".xlsx"}:
            raise ValidationError("Export destination must end with .csv or .xlsx.")

        source_format = self._resolve_export_source_format(source_path, dataset.source_format)
        frame = self._load_export_frame(source_path, source_format)
        temp_destination_path = self._temporary_export_path(destination_path)
        try:
            if destination_suffix == ".csv":
                csv_encoding = self._normalize_csv_encoding(input_data.csv_encoding)
                self._write_export_csv(frame, temp_destination_path, csv_encoding)
            else:
                frame.write_excel(temp_destination_path)
            temp_destination_path.replace(destination_path)
        except Exception:
            temp_destination_path.unlink(missing_ok=True)
            raise
        return destination_path

    def _resolve_export_source_format(self, source_path: Path, dataset_format: DatasetSourceFormat) -> DatasetSourceFormat:
        detected_format = detect_source_format(source_path)
        if detected_format is not DatasetSourceFormat.UNKNOWN:
            return detected_format
        if dataset_format is DatasetSourceFormat.UNKNOWN:
            raise ValidationError("Dataset source file format is not supported for export.")
        return dataset_format

    def _load_export_frame(self, source_path: Path, source_format: DatasetSourceFormat) -> pl.DataFrame:
        try:
            return load_tabular_frame(source_path, source_format)
        except Exception as exc:  # pragma: no cover - exercised by failure surface
            raise self._dataset_read_failure(
                source_path=source_path,
                operation="export_dataset_copy",
                exc=exc,
                message="Unable to read dataset file for export.",
            ) from exc

    def _write_export_csv(self, frame: pl.DataFrame, destination_path: Path, csv_encoding: str) -> None:
        if csv_encoding == "utf-8":
            frame.write_csv(destination_path)
            return
        if csv_encoding == "utf-8-sig":
            frame.write_csv(destination_path, include_bom=True)
            return

        utf8_path = self._temporary_export_path(destination_path)
        try:
            frame.write_csv(utf8_path)
            with utf8_path.open("r", encoding="utf-8", newline="") as source:
                with destination_path.open("w", encoding=csv_encoding, newline="") as target:
                    shutil.copyfileobj(source, target)
        finally:
            utf8_path.unlink(missing_ok=True)

    def _temporary_export_path(self, destination_path: Path) -> Path:
        return destination_path.with_name(
            f".{destination_path.stem}.{uuid4().hex}{destination_path.suffix}"
        )

    def _dataset_read_failure(
        self,
        *,
        source_path: Path,
        operation: str,
        exc: Exception,
        message: str,
    ) -> ValidationError:
        source_format = detect_source_format(source_path)
        LOGGER.exception("Dataset read failed during %s for %s.", operation, source_path)
        error_details = {
            "operation": operation,
            "source_path": str(source_path),
            "source_format": source_format.value,
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
        }
        repair_hints = [
            "Verify that the file is readable and matches its extension, then retry.",
        ]
        retryable = False
        if isinstance(exc, TabularRuntimeError):
            error_details["tabular"] = exc.error_details
            repair_hints = [
                "Close running Xenix or Python processes that may keep old binaries loaded, then repair the environment.",
                "Run `pdm sync -d --clean` from the project root so `polars` and `polars-runtime-*` are reinstalled to the same version.",
            ]
            message = "Unable to read dataset file because the Polars runtime is unavailable."
        return ValidationError(
            message,
            error_code="tabular_runtime_unavailable" if isinstance(exc, TabularRuntimeError) else "dataset_file_read_failed",
            error_details=error_details,
            repair_hints=repair_hints,
            retryable=retryable,
        )

    def _normalize_csv_encoding(self, encoding_name: str) -> str:
        normalized = encoding_name.strip()
        if not normalized:
            raise ValidationError("CSV export encoding cannot be empty.")
        try:
            return codecs.lookup(normalized).name
        except LookupError as exc:
            raise ValidationError(f"CSV export encoding '{encoding_name}' is not supported.") from exc

    def _load_import_frames(
        self,
        source_path: Path,
        source_format: DatasetSourceFormat,
    ) -> list[dict[str, object]]:
        if source_format is DatasetSourceFormat.CSV:
            frame = pl.read_csv(source_path, try_parse_dates=False, infer_schema_length=None)
            schema = resolve_tabular_schema_for_loaded_frame(source_path, source_format, frame)
            return [self._frame_spec(frame, schema=schema, sheet_name=None, sheet_index=None)]
        if source_format is DatasetSourceFormat.PARQUET:
            frame = pl.read_parquet(source_path)
            schema = resolve_tabular_schema_for_loaded_frame(source_path, source_format, frame)
            return [self._frame_spec(frame, schema=schema, sheet_name=None, sheet_index=None)]
        if source_format in {DatasetSourceFormat.XLSX, DatasetSourceFormat.XLS}:
            workbook = pl.read_excel(
                source_path,
                engine="calamine",
                sheet_id=0,
                raise_if_empty=False,
            )
            if isinstance(workbook, pl.DataFrame):
                schema = resolve_tabular_schema_for_loaded_frame(
                    source_path,
                    source_format,
                    workbook,
                    sheet_name=0,
                )
                return [self._frame_spec(workbook, schema=schema, sheet_name=None, sheet_index=0)]
            specs: list[dict[str, object]] = []
            for index, (sheet_name, frame) in enumerate(workbook.items()):
                if frame.width == 0 or frame.height == 0:
                    continue
                schema = resolve_tabular_schema_for_loaded_frame(
                    source_path,
                    source_format,
                    frame,
                    sheet_name=str(sheet_name),
                )
                specs.append(
                    self._frame_spec(
                        frame,
                        schema=schema,
                        sheet_name=str(sheet_name),
                        sheet_index=index,
                    )
                )
            return specs
        raise ValidationError("Only .csv, .parquet, .xlsx, and .xls dataset files are supported.")

    def _frame_spec(
        self,
        frame: pl.DataFrame,
        *,
        schema: TabularSchema,
        sheet_name: str | None,
        sheet_index: int | None,
    ) -> dict[str, object]:
        if frame.width == 0:
            raise ValidationError("Dataset file must contain at least one column.")
        if frame.height == 0:
            raise ValidationError("Dataset file must contain at least one data row.")
        if len(frame.columns) != len(schema.columns):
            raise ValidationError("Dataset source schema could not be resolved consistently.")
        renamed = apply_tabular_schema(frame, schema)
        return {
            "frame": renamed,
            "sheet_name": sheet_name,
            "sheet_index": sheet_index,
        }

    def _dataset_storage_path(self, dataset_id: str, *, derived: bool) -> Path:
        directory = self._paths.state / "datasets" / ("derived" if derived else "imported")
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{dataset_id}.parquet"

    def _resolve_project_id(
        self,
        session,
        project_id: str | None,
        *,
        derived_from: DatasetRow | None = None,
    ) -> str:
        normalized = project_id.strip() if project_id else ""
        if normalized:
            if self._projects.get(session, normalized) is None:
                raise NotFoundError(f"Project '{normalized}' was not found.")
            if derived_from is not None and derived_from.project_id != normalized:
                raise ValidationError("Derived dataset source does not belong to the provided project.")
            return normalized
        if derived_from is not None:
            return derived_from.project_id
        projects = self._projects.list_all(session)
        if projects:
            return projects[0].id
        row = ProjectRow(name="Agent Analysis")
        self._projects.create(session, row)
        return row.id

    def _is_discardable_dataset(self, row: DatasetRow) -> bool:
        return row.copied_from is None and row.ml_task_id is None

    def _is_service_owned_dataset_path(self, path: Path) -> bool:
        try:
            path.resolve().relative_to((self._paths.state / "datasets").resolve())
        except ValueError:
            return False
        return True

    def _has_dataset_references(self, session, dataset_id: str) -> bool:
        reference_statements = [
            select(DatasetRow.id).where(DatasetRow.copied_from == dataset_id),
            select(DatasetRow.id).where(DatasetRow.derived_from_dataset_id == dataset_id),
            select(DatasetColumnBindingRow.id).where(DatasetColumnBindingRow.dataset_id == dataset_id),
            select(MLTaskRow.id).where(MLTaskRow.dataset_id == dataset_id),
            select(TrainedModelRow.id).where(TrainedModelRow.dataset_id == dataset_id),
        ]
        return any(session.exec(statement).first() is not None for statement in reference_statements)
