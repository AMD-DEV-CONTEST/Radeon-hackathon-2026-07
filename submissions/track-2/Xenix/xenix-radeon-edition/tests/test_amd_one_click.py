from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from xenix.config import ensure_app_dirs, get_app_paths
from xenix.i18n import TranslationManager
from xenix.services.embedding_service import EmbeddingSettingsService
from xenix.services.amd.participants import AmdLlmParticipant
from xenix.services.amd.profile_catalog import load_product_manifest_catalog
from xenix.services.llm import LLMService, LLMSettingsService
from xenix.services.ml.worker_settings import MLWorkerSettingsService
from xenix.services.ocr.settings import OcrSettings, OcrSettingsService
from xenix.services.settings_store import SettingsStore
from xenix.ui.settings_dialog import SettingsDialog


@pytest.fixture()
def app(monkeypatch) -> QApplication:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_packaging_whitelist_tracks_capability_runtime_modules() -> None:
    spec = (Path(__file__).resolve().parents[1] / "xenix.spec").read_text(encoding="utf-8")

    assert 'Path("ui/amd_setup.py")' in spec
    assert 'Path("ui/amd_capability_tasks.py")' in spec
    assert '"xenix.services.amd.composition"' in spec
    # Deleted aggregate guided/task modules must not be reintroduced by a stale
    # packaging allow-list.
    assert "amd_deployment_tasks" not in spec
    assert "services.amd.guided" not in spec


def test_qwen_deployments_add_model_specific_providers_without_changing_llm_roles(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XENIX_APP_HOME", str(tmp_path / "xenix-home"))
    paths = ensure_app_dirs(get_app_paths())
    store = SettingsStore(paths.config)
    llm_settings = LLMSettingsService(settings_store=store)
    catalog = load_product_manifest_catalog()
    participant = AmdLlmParticipant(llm_settings)
    before = llm_settings.load()
    qwen_components = {
        component.models[0].model_id: component
        for component in catalog.components
        if component.models and component.models[0].model_id.startswith("Qwen/")
    }
    try:
        participant.ensure(
            installation_id="qwen-9b",
            component_generation_id="qwen-9b-generation",
            manifest=qwen_components["Qwen/Qwen3.5-9B"],
        )
        participant.ensure(
            installation_id="qwen-4b",
            component_generation_id="qwen-4b-generation",
            manifest=qwen_components["Qwen/Qwen3.5-4B"],
        )

        after = llm_settings.load()
        managed = [provider for provider in after.providers if provider.is_managed]
        assert {provider.display_name for provider in managed} == {
            "AMD Radeon · Qwen3.5-9B",
            "AMD Radeon · Qwen3.5-4B",
        }
        assert {tuple(provider.models) for provider in managed} == {
            ("qwen3.5-9b",),
            ("qwen3.5-4b",),
        }
        assert after.default_fq_model_key == before.default_fq_model_key
        assert after.turn_completion_guard_fq_model_key == before.turn_completion_guard_fq_model_key
        assert after.thread_title_fq_model_key == before.thread_title_fq_model_key
    finally:
        store.close()


def test_settings_keeps_stale_ocr_selection_visible_until_user_replaces_it(
    monkeypatch,
    tmp_path: Path,
    app: QApplication,
) -> None:
    monkeypatch.setenv("XENIX_APP_HOME", str(tmp_path / "xenix-home"))
    paths = ensure_app_dirs(get_app_paths())
    store = SettingsStore(paths.config)
    llm_settings = LLMSettingsService(settings_store=store)
    dialog = SettingsDialog(
        paths,
        paths.logs / "xenix.log",
        paths.state / "xenix.db",
        TranslationManager(app, paths),
        LLMService(llm_settings),
        llm_settings,
        MLWorkerSettingsService(paths),
        EmbeddingSettingsService(settings_store=store),
        OcrSettingsService(store=store),
    )
    try:
        stale_id = "ocr-managed-removed-generation"
        dialog._ocr_settings_snapshot = OcrSettings(active_provider_id=stale_id)
        dialog._reload_ocr_provider_selector(selected_provider_id=stale_id)

        assert dialog._ocr_provider_selector.currentIndex() == -1
        assert dialog._ocr_selected_provider_id == stale_id
        assert dialog._selected_ocr_provider() is None
    finally:
        dialog.close()
        dialog.shutdown()
        store.close()
