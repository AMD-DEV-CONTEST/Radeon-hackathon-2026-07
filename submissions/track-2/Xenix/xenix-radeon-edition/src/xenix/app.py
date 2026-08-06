from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Callable
from datetime import datetime
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Literal

from PySide6.QtCore import QCoreApplication, QElapsedTimer, QEventLoop, QThread, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .config import APP_NAME, APP_ORGANIZATION, ensure_app_dirs, get_app_paths
from .exceptions import StorageBootstrapError, install_exception_hooks
from .i18n import TranslationManager
from .logging import setup_logging, shutdown_logging
from .observability import (
    LLM_USAGE_JOURNAL_FILE_NAME,
    LocalLLMUsageObservability,
    flush_observability,
    record_counter,
    setup_observability,
    start_span,
)
from .resources import package_resource_path
from .trial_lock import TrialLockCheck, check_trial_lock, trial_purchase_url
from .ui.startup_splash import StartupSplash, StartupStage

if TYPE_CHECKING:
    from .ui.main_window import MainWindow

LOGGER = logging.getLogger("xenix.bootstrap")
STARTUP_SPLASH_HOLD_MS = 2200
STARTUP_TIMING_ENV = "XENIX_STARTUP_TIMING"
_STARTUP_TIMING_T0 = time.perf_counter()
StorageRecoveryAction = Literal["quarantine", "open", "exit"]

# This is an advertisement policy, not a second tool registry.  The LLM
# boundary remains the authority for registered definitions and validates the
# frozen scope before accepting or invoking any provider Tool Call.
class TrialLockStartupExit(Exception):
    pass


def _startup_timing_enabled() -> bool:
    return os.environ.get(STARTUP_TIMING_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _emit_startup_timing(event: str, start: float | None = None, **attributes: object) -> None:
    if not _startup_timing_enabled():
        return
    fields = [
        "XENIX_STARTUP_TIMING",
        event,
        f"since_app_import_ms={(time.perf_counter() - _STARTUP_TIMING_T0) * 1000:.3f}",
    ]
    if start is not None:
        fields.append(f"elapsed_ms={(time.perf_counter() - start) * 1000:.3f}")
    for key, value in attributes.items():
        fields.append(f"{key}={value}")
    print("\t".join(fields), file=sys.stderr, flush=True)


def __getattr__(name: str) -> object:
    if name == "MainWindow":
        from .ui.main_window import MainWindow

        globals()[name] = MainWindow
        return MainWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def create_application() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORGANIZATION)

    icon_path = package_resource_path("logo.png")
    app.setWindowIcon(QIcon(str(icon_path)))

    return app


def _update_startup_stage(app: QApplication, splash: StartupSplash | None, stage: StartupStage) -> None:
    if splash is None:
        return
    splash.set_stage(stage)
    app.processEvents()


def _close_startup_splash(app: QApplication, splash: StartupSplash | None) -> None:
    if splash is None:
        return
    splash.close()
    splash.deleteLater()
    app.processEvents()


def _hold_startup_splash(app: QApplication, splash: StartupSplash | None, hold_ms: int) -> None:
    if splash is None or hold_ms <= 0:
        return

    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < hold_ms:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        QThread.msleep(16)


def quarantine_database(db_path: Path, *, timestamp: datetime | None = None) -> Path:
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    resolved_timestamp = timestamp or datetime.now()
    stamp = resolved_timestamp.strftime("%Y%m%d-%H%M%S")
    candidate = db_path.with_name(f"{db_path.stem}.corrupt-{stamp}{db_path.suffix}")
    suffix = 1
    while candidate.exists():
        candidate = db_path.with_name(f"{db_path.stem}.corrupt-{stamp}-{suffix}{db_path.suffix}")
        suffix += 1
    db_path.replace(candidate)
    return candidate


def _storage_recovery_detail(exc: BaseException) -> str:
    cause = exc.__cause__ or exc
    return str(cause) or cause.__class__.__name__


def _prompt_storage_recovery(
    *,
    db_path: Path,
    exc: BaseException,
) -> StorageRecoveryAction:
    message_box = QMessageBox()
    message_box.setIcon(QMessageBox.Critical)
    message_box.setWindowTitle(
        QCoreApplication.translate("XenixStartup", "Local database recovery")
    )
    message_box.setText(
        QCoreApplication.translate(
            "XenixStartup",
            "Xenix could not initialize the local database.",
        )
    )
    message_box.setInformativeText(
        QCoreApplication.translate(
            "XenixStartup",
            "The database may belong to an unsupported development build or may be damaged. "
            "You can back it up and rebuild a fresh database now.",
        )
    )
    message_box.setDetailedText(
        QCoreApplication.translate(
            "XenixStartup",
            "Database: {path}\n\nReason: {reason}",
        ).format(path=db_path, reason=_storage_recovery_detail(exc))
    )
    rebuild_button = message_box.addButton(
        QCoreApplication.translate("XenixStartup", "Back up and rebuild"),
        QMessageBox.AcceptRole,
    )
    open_button = message_box.addButton(
        QCoreApplication.translate("XenixStartup", "Open data folder"),
        QMessageBox.ActionRole,
    )
    exit_button = message_box.addButton(
        QCoreApplication.translate("XenixStartup", "Exit"),
        QMessageBox.RejectRole,
    )
    message_box.setDefaultButton(rebuild_button)
    message_box.exec()

    clicked_button = message_box.clickedButton()
    if clicked_button is rebuild_button:
        return "quarantine"
    if clicked_button is open_button:
        return "open"
    if clicked_button is exit_button:
        return "exit"
    return "exit"


def _prompt_trial_lock(check: TrialLockCheck) -> None:
    purchase_url = trial_purchase_url()
    message_box = QMessageBox()
    message_box.setIcon(QMessageBox.Warning)
    message_box.setWindowTitle(
        QCoreApplication.translate("XenixStartup", "Xenix test build locked")
    )
    message_box.setText(
        QCoreApplication.translate(
            "XenixStartup",
            "This Xenix test build is locked.",
        )
    )
    message_box.setInformativeText(
        QCoreApplication.translate(
            "XenixStartup",
            "Please purchase a license or download a licensed Xenix build from {url}.",
        ).format(url=purchase_url)
    )
    expires_at = check.expires_at_utc.isoformat() if check.expires_at_utc is not None else "-"
    message_box.setDetailedText(
        QCoreApplication.translate(
            "XenixStartup",
            "Reason: {reason}\nTrial expired at: {expires_at}\nState file: {state_path}",
        ).format(
            reason=check.reason.value,
            expires_at=expires_at,
            state_path=check.state_path,
        )
    )
    buy_button = message_box.addButton(
        QCoreApplication.translate("XenixStartup", "Buy license"),
        QMessageBox.AcceptRole,
    )
    exit_button = message_box.addButton(
        QCoreApplication.translate("XenixStartup", "Exit"),
        QMessageBox.RejectRole,
    )
    message_box.setDefaultButton(buy_button)
    message_box.exec()

    clicked_button = message_box.clickedButton()
    if clicked_button is buy_button and purchase_url:
        QDesktopServices.openUrl(QUrl(purchase_url))
    elif clicked_button is exit_button:
        return


def _recover_storage_bootstrap(
    *,
    app: QApplication,
    runtime: SimpleNamespace,
    paths,
    initial_error: StorageBootstrapError,
):
    db_path = runtime.database_path(paths)
    error: StorageBootstrapError = initial_error
    while db_path.exists():
        action = _prompt_storage_recovery(db_path=db_path, exc=error)
        if action == "exit":
            raise error
        if action == "open":
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(db_path.parent)))
            app.processEvents()
            continue

        quarantined_path = quarantine_database(db_path)
        LOGGER.warning(
            "Quarantined local database after startup storage failure: %s -> %s",
            db_path,
            quarantined_path,
        )
        try:
            return runtime.StorageBootstrapService().initialize(paths)
        except StorageBootstrapError as exc:
            error = exc
            LOGGER.exception("Storage bootstrap retry failed after database quarantine")

    raise error


def _load_runtime_imports(
    *,
    module_loaded: Callable[[], None] | None = None,
) -> SimpleNamespace:
    runtime_start = time.perf_counter()

    def load_module(module_name: str):
        module_start = time.perf_counter()
        module = import_module(module_name)
        _emit_startup_timing("runtime_import.module", module_start, module=module_name)
        if module_loaded is not None:
            module_loaded()
        return module

    agent_harness = load_module("xenix.services.agent.harness_service")
    agent_composition = load_module("xenix.services.agent.composition")
    agent_skill_catalog = load_module("xenix.services.agent.skill_catalog")
    lazy_tools = load_module("xenix.services.agent.lazy_tools")
    artifact_service = load_module("xenix.services.artifact_service")
    dataset_export_service = load_module("xenix.services.dataset_export_service")
    embedding_service = load_module("xenix.services.embedding_service")
    embedding_provider_factory = load_module("xenix.services.embedding_provider_factory")
    link_router = load_module("xenix.services.link_router")
    knowledge_import = load_module("xenix.services.knowledge_import_service")
    knowledge_derivation = load_module("xenix.services.knowledge_derivation_service")
    knowledge_document_lifecycle = load_module(
        "xenix.services.knowledge_document_lifecycle_service"
    )
    knowledge_index = load_module("xenix.services.knowledge_index_service")
    knowledge_task_query = load_module("xenix.services.knowledge_task_query")
    knowledge_workspace = load_module("xenix.services.knowledge_workspace_service")
    paddle_ocr = load_module("xenix.services.paddle_ocr_service")
    ocr_settings = load_module("xenix.services.ocr.settings")
    settings_store = load_module("xenix.services.settings_store")
    lazy_ml_service = load_module("xenix.services.lazy_ml_service")
    lazy_services = load_module("xenix.services.lazy_services")
    llm = load_module("xenix.services.llm")
    worker_settings = load_module("xenix.services.ml.worker_settings")
    storage = load_module("xenix.services.storage")
    storage_layout = load_module("xenix.services.storage.layout")
    _emit_startup_timing("runtime_import.total", runtime_start)

    return SimpleNamespace(
        AgentHarnessService=agent_harness.AgentHarnessService,
        build_headless_agent_services=agent_composition.build_headless_agent_services,
        AgentSkillCatalog=agent_skill_catalog.AgentSkillCatalog,
        AgentToolRegistry=lazy_tools.LazyAgentToolRegistry,
        ArtifactService=artifact_service.ArtifactService,
        LLMConversationService=llm.LLMConversationService,
        LLMToolRegistry=llm.AgentToolRegistry,
        DatasetExportService=dataset_export_service.DatasetExportService,
        ConfiguredOcrAttemptFactory=ocr_settings.ConfiguredOcrAttemptFactory,
        EmbeddingSettingsService=embedding_service.EmbeddingSettingsService,
        EmbeddingProviderFactoryRegistry=(
            embedding_provider_factory.EmbeddingProviderFactoryRegistry
        ),
        OcrProviderFactoryRegistry=ocr_settings.OcrProviderFactoryRegistry,
        OcrSettingsService=ocr_settings.OcrSettingsService,
        SettingsStore=settings_store.SettingsStore,
        LazyServiceProxy=lazy_services.LazyServiceProxy,
        LinkRouter=link_router.LinkRouter,
        KnowledgeImportService=knowledge_import.KnowledgeImportService,
        KnowledgeDerivationService=knowledge_derivation.KnowledgeDerivationService,
        KnowledgeDocumentLifecycleService=(
            knowledge_document_lifecycle.KnowledgeDocumentLifecycleService
        ),
        KnowledgeIndexService=knowledge_index.KnowledgeIndexService,
        KnowledgeTaskQueryService=knowledge_task_query.KnowledgeTaskQueryService,
        KnowledgeWorkspaceService=knowledge_workspace.KnowledgeWorkspaceService,
        PaddleOcrDeploymentService=paddle_ocr.PaddleOcrDeploymentService,
        PaddleOcrService=paddle_ocr.PaddleOcrService,
        LLMService=llm.LLMService,
        LLMSettingsService=llm.LLMSettingsService,
        create_builtin_embedding_provider_factory_registry=(
            embedding_service.create_builtin_embedding_provider_factory_registry
        ),
        create_builtin_llm_provider_factory_registry=(
            llm.create_builtin_llm_provider_factory_registry
        ),
        MLService=lazy_ml_service.LazyMLService,
        MLWorkerSettingsService=worker_settings.MLWorkerSettingsService,
        StorageBootstrapService=storage.StorageBootstrapService,
        database_path=storage_layout.database_path,
    )


def _register_agent_skill_tools(
    registry,
    catalog,
    *,
    activated_skill_names_provider: Callable[[str], set[str]] | None = None,
) -> None:
    """Compatibility forwarding for historical desktop/test imports."""

    from .services.agent.composition import register_agent_skill_tools

    register_agent_skill_tools(
        registry,
        catalog,
        activated_skill_names_provider=activated_skill_names_provider,
    )


def _agent_skill_activated_skill_names(snapshot) -> set[str]:
    """Compatibility forwarding for historical desktop/test imports."""

    from .services.agent.composition import agent_skill_activated_skill_names

    return agent_skill_activated_skill_names(snapshot)


def _agent_skill_context_messages(catalog, snapshot) -> list:
    """Compatibility forwarding for historical desktop/test imports."""

    from .services.agent.composition import agent_skill_context_messages

    return agent_skill_context_messages(catalog, snapshot)


def _agent_skill_tool_scope_names(snapshot) -> tuple[str, ...] | None:
    """Compatibility forwarding for historical desktop/test imports."""

    from .services.agent.composition import agent_skill_tool_scope_names

    return agent_skill_tool_scope_names(snapshot)


def _load_runtime_imports_with_events(
    app: QApplication,
    splash: StartupSplash | None,
) -> SimpleNamespace:
    if splash is None:
        load_start = time.perf_counter()
        runtime = _load_runtime_imports()
        _emit_startup_timing("runtime_import.no_splash_wait", load_start)
        return runtime

    load_start = time.perf_counter()
    def process_module_boundary() -> None:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)

    result = _load_runtime_imports(module_loaded=process_module_boundary)
    app.processEvents()
    _emit_startup_timing("runtime_import.splash_wait", load_start)
    return result


def build_main_window(
    *,
    show: bool = True,
    show_splash: bool | None = None,
    splash_hold_ms: int = 0,
    flush_startup_observability: bool = False,
) -> tuple[QApplication, MainWindow]:
    build_start = time.perf_counter()
    _emit_startup_timing("build_main_window.start")
    step_start = time.perf_counter()
    app = create_application()
    _emit_startup_timing("create_application", step_start)
    step_start = time.perf_counter()
    paths = get_app_paths()
    _emit_startup_timing("get_app_paths", step_start)
    step_start = time.perf_counter()
    translation_manager = TranslationManager(app, paths)
    translation_manager.initialize()
    _emit_startup_timing("translation.initialize", step_start)
    should_show_splash = show if show_splash is None else show_splash
    step_start = time.perf_counter()
    splash = StartupSplash() if should_show_splash else None
    _emit_startup_timing("splash.create", step_start, enabled=splash is not None)

    if splash is not None:
        step_start = time.perf_counter()
        splash.show_centered()
        _update_startup_stage(app, splash, StartupStage.STARTING)
        _emit_startup_timing("splash.show", step_start)

    startup_scope = None
    startup_span_active = False
    logging_initialized = False
    runtime_shutdown: Callable[[], None] | None = None
    try:
        _update_startup_stage(app, splash, StartupStage.PREPARING_APP_DATA)
        step_start = time.perf_counter()
        paths = ensure_app_dirs(paths)
        _emit_startup_timing("ensure_app_dirs", step_start)

        step_start = time.perf_counter()
        trial_lock_check = check_trial_lock(paths)
        _emit_startup_timing(
            "trial_lock.check",
            step_start,
            enabled=trial_lock_check.enabled,
            locked=trial_lock_check.locked,
            reason=trial_lock_check.reason.value,
        )
        if trial_lock_check.locked:
            _close_startup_splash(app, splash)
            splash = None
            if show:
                _prompt_trial_lock(trial_lock_check)
                app.processEvents()
            raise TrialLockStartupExit(trial_lock_check.reason.value)

        _update_startup_stage(app, splash, StartupStage.LOADING_RUNTIME)
        step_start = time.perf_counter()
        runtime = _load_runtime_imports_with_events(app, splash)
        _emit_startup_timing("load_runtime_imports", step_start)
        step_start = time.perf_counter()
        from .ui.main_window import MainWindow
        _emit_startup_timing("import_main_window", step_start)

        _update_startup_stage(app, splash, StartupStage.INITIALIZING_LOGGING)
        step_start = time.perf_counter()
        log_path = setup_logging(paths)
        logging_initialized = True
        observability = setup_observability(paths)
        startup_scope = start_span("app.startup")
        startup_scope.__enter__()
        startup_span_active = True
        install_exception_hooks()
        LOGGER.info(
            "Observability initialized",
            extra={
                "event_name": "app.observability.initialized",
                "otlp_enabled": observability.otlp_enabled,
                "otlp_trace_export_enabled": observability.trace_export_enabled,
                "otlp_metric_export_enabled": observability.metric_export_enabled,
                "otlp_log_export_enabled": observability.log_export_enabled,
            },
        )
        _emit_startup_timing("logging_observability.initialize", step_start)

        if splash is not None:
            step_start = time.perf_counter()
            splash.retranslate_ui()
            _emit_startup_timing("splash.retranslate", step_start)

        _update_startup_stage(app, splash, StartupStage.INITIALIZING_STORAGE)
        try:
            step_start = time.perf_counter()
            with start_span("storage.bootstrap"):
                context = runtime.StorageBootstrapService().initialize(paths)
                record_counter(
                    "xenix.storage.bootstrap.count",
                    attributes={
                        "storage.schema_version": context.schema_version,
                        "status": "succeeded",
                    },
                )
            _emit_startup_timing("storage.bootstrap", step_start)
        except StorageBootstrapError as exc:
            record_counter(
                "xenix.storage.bootstrap.count",
                attributes={"status": "failed", "error.type": exc.__class__.__name__},
            )
            if not show or not runtime.database_path(paths).exists():
                raise
            _close_startup_splash(app, splash)
            splash = None
            context = _recover_storage_bootstrap(
                app=app,
                runtime=runtime,
                paths=paths,
                initial_error=exc,
            )

        knowledge_import_service = None
        knowledge_derivation_service = None
        knowledge_index_service = None
        settings_store = None
        amd_composition = None
        runtime_shutdown_started = False
        runtime_shutdown_connected = False

        def shutdown_runtime() -> None:
            nonlocal runtime_shutdown_connected, runtime_shutdown_started
            if runtime_shutdown_started:
                return
            runtime_shutdown_started = True
            if runtime_shutdown_connected:
                app.aboutToQuit.disconnect(shutdown_runtime)
                runtime_shutdown_connected = False
            if knowledge_import_service is not None:
                knowledge_import_service.shutdown()
            if knowledge_derivation_service is not None:
                knowledge_derivation_service.shutdown()
            if knowledge_index_service is not None:
                knowledge_index_service.shutdown()
            if amd_composition is not None:
                try:
                    amd_composition.close()
                except Exception:
                    LOGGER.exception("AMD composition shutdown did not complete cleanly.")
            if settings_store is not None:
                settings_store.close()
            context.engine.dispose()
            flush_observability()
            shutdown_logging()

        runtime_shutdown = shutdown_runtime

        _update_startup_stage(app, splash, StartupStage.LOADING_WORKBENCH)
        step_start = time.perf_counter()
        ml_worker_settings_service = runtime.MLWorkerSettingsService(paths)
        settings_store = runtime.SettingsStore(paths.config)
        llm_settings_service = runtime.LLMSettingsService(
            paths,
            settings_store=settings_store,
        )
        embedding_settings_service = runtime.EmbeddingSettingsService(
            paths,
            settings_store=settings_store,
        )
        ocr_settings_service = runtime.OcrSettingsService(store=settings_store)
        llm_provider_factory_registry = runtime.create_builtin_llm_provider_factory_registry()
        embedding_provider_factory_registry = (
            runtime.create_builtin_embedding_provider_factory_registry()
        )
        ocr_provider_factory_registry = runtime.OcrProviderFactoryRegistry()
        from .services.amd.composition import build_amd_composition
        from .ui.amd_setup import AmdRadeonSettingsContribution

        amd_composition = build_amd_composition(
            session_factory=context.session_factory,
            settings_store=settings_store,
            llm_settings_service=llm_settings_service,
            embedding_settings_service=embedding_settings_service,
            ocr_settings_service=ocr_settings_service,
            llm_provider_factory_registry=llm_provider_factory_registry,
            embedding_provider_factory_registry=embedding_provider_factory_registry,
            ocr_provider_factory_registry=ocr_provider_factory_registry,
            local_cache_root=(paths.cache / "amd-runtime").resolve(strict=False),
            temporary_root=paths.temp.resolve(strict=False),
        )
        settings_contributions = (AmdRadeonSettingsContribution(amd_composition),)
        llm_service = runtime.LLMService(
            llm_settings_service,
            provider_factory_registry=llm_provider_factory_registry,
        )
        agent_services = runtime.build_headless_agent_services(
            paths=paths,
            session_factory=context.session_factory,
            llm=llm_service,
            embedding_settings_service=embedding_settings_service,
            embedding_provider_factory_registry=embedding_provider_factory_registry,
            ml_worker_settings=ml_worker_settings_service,
            usage_observability=LocalLLMUsageObservability(
                paths.logs / LLM_USAGE_JOURNAL_FILE_NAME
            ),
        )
        link_router = runtime.LinkRouter(
            artifact_service=agent_services.artifacts,
        )
        from .services.update_service import UpdateService

        update_service = UpdateService(paths, runtime.database_path(paths))
        paddle_ocr_deployment = runtime.PaddleOcrDeploymentService(paths)
        knowledge_index_service = runtime.KnowledgeIndexService(
            session_factory=context.session_factory,
            semantic_service=agent_services.knowledge_semantic,
            embedding_service=agent_services.embedding,
            embedding_settings_source=embedding_settings_service,
        )
        knowledge_derivation_service = runtime.KnowledgeDerivationService(
            paths=paths,
            session_factory=context.session_factory,
            retrieval_ready_notifier=knowledge_index_service.notify_corpus_changed,
        )
        knowledge_import_service = runtime.KnowledgeImportService(
            paths=paths,
            session_factory=context.session_factory,
            artifact_service=agent_services.artifacts,
            ocr_attempt_factory=runtime.ConfiguredOcrAttemptFactory(
                ocr_settings_service,
                ocr_provider_factory_registry,
            ),
            canonical_ready_notifier=knowledge_derivation_service.enqueue_generation,
            corpus_changed_notifier=knowledge_index_service.notify_corpus_changed,
        )
        knowledge_document_lifecycle_service = (
            runtime.KnowledgeDocumentLifecycleService(
                session_factory=context.session_factory,
                index_service=knowledge_index_service,
            )
        )
        knowledge_task_query_service = runtime.KnowledgeTaskQueryService(
            context.session_factory
        )
        knowledge_workspace_service = runtime.KnowledgeWorkspaceService(
            knowledge_service=agent_services.knowledge,
            task_query=knowledge_task_query_service,
            index_service=knowledge_index_service,
            ocr_deployment=paddle_ocr_deployment,
        )
        _emit_startup_timing("services.construct", step_start)

        step_start = time.perf_counter()
        window = MainWindow(
            paths=paths,
            log_path=log_path,
            db_path=runtime.database_path(paths),
            translation_manager=translation_manager,
            agent_harness_service=agent_services.harness,
            llm_service=llm_service,
            llm_settings_service=llm_settings_service,
            embedding_settings_service=embedding_settings_service,
            ocr_settings_service=ocr_settings_service,
            ml_worker_settings_service=ml_worker_settings_service,
            artifact_service=agent_services.artifacts,
            link_router=link_router,
            dataset_service=agent_services.datasets,
            ml_service=agent_services.ml,
            update_service=update_service,
            knowledge_import_service=knowledge_import_service,
            knowledge_derivation_service=knowledge_derivation_service,
            knowledge_service=agent_services.knowledge,
            knowledge_index_service=knowledge_index_service,
            paddle_ocr_deployment=paddle_ocr_deployment,
            knowledge_task_query_service=knowledge_task_query_service,
            knowledge_workspace_service=knowledge_workspace_service,
            knowledge_document_lifecycle_service=(
                knowledge_document_lifecycle_service
            ),
            settings_contributions=settings_contributions,
        )
        _emit_startup_timing("main_window.construct", step_start)
        app.aboutToQuit.connect(shutdown_runtime)
        runtime_shutdown_connected = True
        window.closing.connect(shutdown_runtime)

        _update_startup_stage(app, splash, StartupStage.READY)
        _hold_startup_splash(app, splash, splash_hold_ms)
        _close_startup_splash(app, splash)
        if show:
            step_start = time.perf_counter()
            window.show()
            app.processEvents()
            _emit_startup_timing("window.show", step_start)

        LOGGER.info("Xenix native shell started")
        record_counter("xenix.app.startup.count", attributes={"status": "succeeded"})
        startup_scope.__exit__(None, None, None)
        startup_span_active = False
        if flush_startup_observability:
            flush_observability()
        _emit_startup_timing("build_main_window.total", build_start)
        return app, window
    except Exception:
        record_counter("xenix.app.startup.count", attributes={"status": "failed"})
        if startup_span_active and startup_scope is not None:
            startup_scope.__exit__(*sys.exc_info())
            startup_span_active = False
        if runtime_shutdown is None:
            flush_observability()
            if logging_initialized:
                shutdown_logging()
        else:
            runtime_shutdown()
        _close_startup_splash(app, splash)
        raise


def _run_smoke_checks(paths) -> None:
    import pandas as pd
    from polars._cpu_check import get_runtime_repr

    from .services.analysis_graph import AnalysisGraphService, GraphDatasetInput
    from .services.data_transform import (
        DataQueryInput,
        DataQueryTransformService,
        DatasetSqlBinding,
    )
    from .services.dataset_inspection import detect_source_format
    from .services.ml.models.regression import XGBoostRegressionService
    from .services.tabular import load_tabular_frame

    if get_runtime_repr() != "rtcompat":
        raise RuntimeError("Polars packaged runtime smoke expected rtcompat runtime.")

    duckdb_smoke_path = paths.temp / "duckdb-smoke.csv"
    duckdb_smoke_path.write_text("value\n1\n2\n", encoding="utf-8")
    result = DataQueryTransformService(paths).query(
        DataQueryInput(
            bindings=[
                DatasetSqlBinding(
                    alias="input",
                    dataset_id="smoke-dataset",
                    source_path=str(duckdb_smoke_path.resolve()),
                )
            ],
            sql="SELECT SUM(value) AS total FROM input",
            limit=1,
        )
    )
    if not result.rows or result.rows[0].get("total") != 3:
        raise RuntimeError("DuckDB smoke query failed.")

    tabular_csv_smoke_path = paths.temp / "tabular-smoke.csv"
    tabular_csv_smoke_path.write_text("label,value\nA,1\nB,2\n", encoding="utf-8")
    csv_frame = load_tabular_frame(
        tabular_csv_smoke_path,
        detect_source_format(tabular_csv_smoke_path),
    )
    if csv_frame.height != 2 or csv_frame.width != 2:
        raise RuntimeError("Polars CSV smoke read failed.")

    tabular_xlsx_smoke_path = paths.temp / "tabular-smoke.xlsx"
    pd.DataFrame([{"label": "A", "value": 1}, {"label": "B", "value": 2}]).to_excel(
        tabular_xlsx_smoke_path,
        index=False,
    )
    xlsx_frame = load_tabular_frame(
        tabular_xlsx_smoke_path,
        detect_source_format(tabular_xlsx_smoke_path),
    )
    if xlsx_frame.height != 2 or xlsx_frame.width != 2:
        raise RuntimeError("Polars Excel smoke read failed.")

    graph_smoke_path = paths.temp / "graph-smoke.csv"
    graph_smoke_path.write_text("label,value\nA,1\nB,2\n", encoding="utf-8")
    graph_result = AnalysisGraphService(paths).graph_dataset(
        GraphDatasetInput(
            source_path=str(graph_smoke_path.resolve()),
            dataset_name="Graph smoke",
            spec={
                "width": 300,
                "height": 180,
                "title": "Graph smoke",
                "mark": "bar",
                "encoding": {
                    "x": {"field": "label", "type": "nominal"},
                    "y": {"field": "value", "type": "quantitative"},
                    "color": {"value": "#4c78a8"},
                },
            },
        )
    )
    graph_output = Path(graph_result.output_path)
    if not graph_output.is_file() or not graph_output.read_text(encoding="utf-8").lstrip().startswith("<svg"):
        raise RuntimeError("Vega-Lite graph smoke render failed.")

    wordcloud_smoke_path = paths.temp / "graph-wordcloud-smoke.csv"
    wordcloud_smoke_path.write_text(
        "word,count\nsales,40\nmargin,28\nnorth,22\n",
        encoding="utf-8",
    )
    wordcloud_result = AnalysisGraphService(paths).graph_dataset(
        GraphDatasetInput(
            source_path=str(wordcloud_smoke_path.resolve()),
            dataset_name="Graph wordcloud smoke",
            wordcloud_spec={
                "title": "Graph wordcloud smoke",
                "width": 360,
                "height": 220,
            },
        )
    )
    wordcloud_svg = Path(wordcloud_result.output_path).read_text(encoding="utf-8")
    if "<title>sales: 40</title>" not in wordcloud_svg or "Graph wordcloud smoke" not in wordcloud_svg:
        raise RuntimeError("Wordcloud smoke render failed.")

    xgboost_estimator = XGBoostRegressionService._build_estimator(
        n_estimators=2,
        max_depth=1,
        learning_rate=0.5,
    )
    xgboost_estimator.fit([[0.0], [1.0], [2.0], [3.0]], [0.0, 1.0, 2.0, 3.0])
    xgboost_prediction = xgboost_estimator.predict([[1.5]])
    if len(xgboost_prediction) != 1:
        raise RuntimeError("XGBoost packaged runtime smoke fit failed.")

    from .services.knowledge_packaged_smoke import run_knowledge_packaged_smoke

    run_knowledge_packaged_smoke(paths)


def run(*, smoke_test: bool = False) -> int:
    try:
        app, window = build_main_window(
            show=not smoke_test,
            show_splash=not smoke_test,
            splash_hold_ms=0 if smoke_test else STARTUP_SPLASH_HOLD_MS,
            flush_startup_observability=smoke_test,
        )
    except TrialLockStartupExit:
        return 1
    except Exception as exc:
        if smoke_test:
            raise
        app = QApplication.instance() or create_application()
        QMessageBox.critical(
            None,
            QCoreApplication.translate("XenixStartup", "Unable to start Xenix"),
            QCoreApplication.translate(
                "XenixStartup",
                "Xenix could not finish startup.\n\n{error}",
            ).format(error=exc),
        )
        return 1

    if smoke_test:
        try:
            _run_smoke_checks(ensure_app_dirs(get_app_paths()))
            window.show()
            app.processEvents()
            window.close()
            LOGGER.info("Xenix smoke test completed")
            flush_observability()
            return 0
        except Exception:
            LOGGER.exception("Xenix smoke test failed")
            window.close()
            flush_observability()
            return 1
    return app.exec()
