from pathlib import Path

import pytest

from buildguard.config import load_settings
from buildguard.exceptions import ConfigurationError
from buildguard.rag.schemas import RagSearchInput
from buildguard.rag.service import create_rag_service


def test_index_manifest_invalidates_when_model_identity_changes(
    config_tree: Path, tmp_path: Path
) -> None:
    settings = load_settings(config_tree)
    workspace = tmp_path / "workspace"
    source = tmp_path / "standard.md"
    source.write_text("# Standard\n" + "safety requirement " * 40, encoding="utf-8")
    settings = settings.model_copy(
        update={
            "app": settings.app.model_copy(
                update={
                    "workspace_dir": workspace,
                    "database_path": workspace / "database" / "buildguard.db",
                }
            ),
            "rag": settings.rag.model_copy(
                update={
                    "index_dir": workspace / "indexes" / "standards",
                    "chunk_min_chars": 50,
                    "chunk_max_chars": 200,
                    "chunk_overlap_chars": 10,
                }
            ),
        }
    )
    service = create_rag_service(settings)
    assert service.ingest(source).status == "indexed"
    assert service.validate_index()["valid"] is True
    assert service.index_manifest_path.is_file()

    changed = settings.model_copy(
        update={
            "rag": settings.rag.model_copy(
                update={"embedding_model_revision": "different-revision"}
            )
        }
    )
    invalid = create_rag_service(changed)

    assert invalid.validate_index()["valid"] is False
    with pytest.raises(ConfigurationError, match="rebuild required"):
        invalid.search(RagSearchInput(query="safety"))
    assert invalid.rebuild()["valid"] is True
