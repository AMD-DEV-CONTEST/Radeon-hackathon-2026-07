import os
from pathlib import Path

from sqlmodel import Session, select

from xenix.config import ensure_app_dirs, get_app_paths
from xenix.services.artifact_service import ArtifactService
from xenix.services.knowledge_import_service import KnowledgeImportService
from xenix.services.knowledge_import_worker import read_worker_result
from xenix.services.storage import StorageBootstrapService
from xenix.services.storage.layout import (
    knowledge_import_result_path,
    knowledge_root,
)
from xenix.services.storage.models import KnowledgeCanonicalGenerationRow


def test_parent_publishes_typed_worker_output_from_private_staging(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XENIX_APP_HOME", str(tmp_path / "xenix-home"))
    paths = ensure_app_dirs(get_app_paths())
    storage = StorageBootstrapService().initialize(paths)
    source = tmp_path / "rules.txt"
    source.write_text("雨具目标库存采用三周平均销量。", encoding="utf-8")
    importer = KnowledgeImportService(
        paths=paths,
        session_factory=storage.session_factory,
        artifact_service=ArtifactService(storage.session_factory),
    )

    try:
        imported = importer.import_file(source, timeout=30)
        worker_result = read_worker_result(
            knowledge_import_result_path(paths, imported.import_id)
        )

        assert worker_result.worker_pid != os.getpid()
        assert worker_result.staged_relative_path == (
            f"tasks/imports/{imported.import_id}/canonical"
        )
        assert not (
            knowledge_root(paths) / worker_result.staged_relative_path
        ).exists()
        with Session(storage.engine) as session:
            generation = session.exec(
                select(KnowledgeCanonicalGenerationRow).where(
                    KnowledgeCanonicalGenerationRow.id
                    == imported.canonical_generation_id
                )
            ).one()
        assert generation.relative_path.startswith("objects/canonical/")
        assert (knowledge_root(paths) / generation.relative_path).is_dir()
    finally:
        importer.shutdown()
        storage.engine.dispose()
