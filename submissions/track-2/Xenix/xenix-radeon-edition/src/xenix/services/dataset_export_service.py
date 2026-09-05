from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from ..config import AppPaths
from .artifact_service import ArtifactService, RegisterArtifactInput
from .dataset_service import DatasetService, ExportDatasetCopyInput
from .storage.models import ArtifactKind


class DatasetExportArtifact(SQLModel):
    dataset_id: str
    artifact_id: str
    absolute_path: str
    export_format: str = "xlsx"


class DatasetExportService:
    def __init__(
        self,
        *,
        paths: AppPaths,
        dataset_service: DatasetService,
        artifact_service: ArtifactService,
        session_factory: sessionmaker | None = None,
    ) -> None:
        _ = session_factory
        self._paths = paths
        self._dataset_service = dataset_service
        self._artifact_service = artifact_service

    def materialize_dataset_export_artifact(
        self,
        dataset_id: str,
        *,
        metadata_payload: dict[str, Any] | None = None,
    ) -> DatasetExportArtifact:
        dataset = self._dataset_service.get_dataset(dataset_id)
        destination_path = self._default_workbook_path(dataset.id, dataset.name)
        self._dataset_service.export_dataset_copy(
            ExportDatasetCopyInput(
                dataset_id=dataset.id,
                destination_path=str(destination_path),
            )
        )

        metadata = {
            "dataset_id": dataset.id,
            "dataset_export": {
                "dataset_id": dataset.id,
                "format": "xlsx",
                "source_path": dataset.source_path,
            },
        }
        if metadata_payload:
            metadata.update(dict(metadata_payload))
            metadata["dataset_id"] = dataset.id
            metadata["dataset_export"] = {
                "dataset_id": dataset.id,
                "format": "xlsx",
                "source_path": dataset.source_path,
            }

        try:
            artifact = self._artifact_service.register_artifact(
                RegisterArtifactInput(
                    kind=ArtifactKind.DATASET,
                    title=dataset.name,
                    absolute_path=str(destination_path.resolve()),
                    mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    metadata_payload=metadata,
                )
            )
        except Exception:
            destination_path.unlink(missing_ok=True)
            raise

        return DatasetExportArtifact(
            dataset_id=dataset.id,
            artifact_id=artifact.id,
            absolute_path=artifact.absolute_path,
        )

    def _default_workbook_path(self, dataset_id: str, name: str) -> Path:
        export_dir = self._paths.artifacts / "datasets" / "exports" / dataset_id
        export_dir.mkdir(parents=True, exist_ok=True)
        return export_dir / f"{self._slug(name) or dataset_id}.xlsx"

    def _slug(self, value: str) -> str:
        normalized = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value.strip(), flags=re.UNICODE)
        normalized = normalized.strip("-._")
        return normalized[:80]
