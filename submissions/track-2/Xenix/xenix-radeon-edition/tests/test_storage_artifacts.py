from __future__ import annotations

from pathlib import Path

from xenix.config import ensure_app_dirs, get_app_paths
from xenix.services.artifact_service import ArtifactService, RegisterArtifactInput
from xenix.services.storage import StorageBootstrapService
from xenix.services.storage.models import ArtifactKind


def test_artifact_registration_has_no_conversation_dependency(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XENIX_APP_HOME", str(tmp_path / "xenix-home"))
    paths = ensure_app_dirs(get_app_paths())
    context = StorageBootstrapService().initialize(paths)
    output = tmp_path / "output.csv"
    output.write_text("a,b\n1,2\n", encoding="utf-8")

    row = ArtifactService(context.session_factory).register_artifact(
        RegisterArtifactInput(
            kind=ArtifactKind.FILE,
            title="Output",
            absolute_path=str(output),
            mime_type="text/csv",
        )
    )

    assert row.kind is ArtifactKind.FILE
    assert ArtifactService(context.session_factory).resolve_uri(f"artifact://{row.id}").artifact_id == row.id
