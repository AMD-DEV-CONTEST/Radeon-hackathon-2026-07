from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from xenix.config import ensure_app_dirs, get_app_paths
from xenix.i18n import TranslationManager
from xenix.services.embedding_service import (
    EmbeddingSettings,
    EmbeddingSettingsService,
)
from xenix.services.llm import LLMService, LLMSettingsService
from xenix.services.ml.worker_settings import MLWorkerSettingsService
from xenix.services.ocr.settings import OcrSettingsService
from xenix.services.settings_store import SettingsStore
from xenix.ui.settings_dialog import SettingsDialog


@pytest.fixture()
def app(monkeypatch) -> QApplication:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_embedding_model_change_requires_user_confirmation_before_rebuild(
    monkeypatch,
    tmp_path: Path,
    app: QApplication,
) -> None:
    class Indexes:
        def __init__(self) -> None:
            self.enqueued: list[tuple[tuple[str, ...], str]] = []

        def embedding_change_requires_confirmation(self, previous, proposed):
            return previous.model != proposed.model and proposed.enabled

        def enqueue_rebuild(self, kinds, *, trigger):
            self.enqueued.append((tuple(str(kind) for kind in kinds), trigger))
            return "task-1"

        def status(self):
            return SimpleNamespace(
                keyword_state="ready",
                text_vector_state="needs_rebuild",
                unit_count=1,
            )

    monkeypatch.setenv("XENIX_APP_HOME", str(tmp_path / "xenix-home"))
    paths = ensure_app_dirs(get_app_paths())
    settings_store = SettingsStore(paths.config)
    llm_settings = LLMSettingsService(settings_store=settings_store)
    embeddings = EmbeddingSettingsService(settings_store=settings_store)
    embeddings.replace_user_settings(
        EmbeddingSettings(
            enabled=True,
            base_url="https://embedding.example.test",
            model="meaning-v1",
        ),
        expected_revision=0,
    )
    indexes = Indexes()
    dialog = SettingsDialog(
        paths,
        paths.logs / "xenix.log",
        paths.state / "xenix.db",
        TranslationManager(app, paths),
        LLMService(llm_settings),
        llm_settings,
        MLWorkerSettingsService(paths),
        embeddings,
        OcrSettingsService(store=settings_store),
        knowledge_index_service=indexes,
    )

    try:
        monkeypatch.setattr(
            dialog,
            "_confirm_embedding_compatibility_change",
            lambda: "rebuild",
        )
        dialog._embedding_model_input.setText("meaning-v2")
        dialog._save_agent_settings()

        assert embeddings.load().model == "meaning-v2"
        assert indexes.enqueued == [(("text_vector",), "settings_change")]

        monkeypatch.setattr(
            dialog,
            "_confirm_embedding_compatibility_change",
            lambda: "cancel",
        )
        dialog._embedding_model_input.setText("meaning-v3")
        dialog._save_agent_settings()

        assert embeddings.load().model == "meaning-v2"
        assert indexes.enqueued == [(("text_vector",), "settings_change")]
    finally:
        dialog.shutdown()
        dialog.close()
        settings_store.close()
