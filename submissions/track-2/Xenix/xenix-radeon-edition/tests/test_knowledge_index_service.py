from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from xenix.config import ensure_app_dirs, get_app_paths
from xenix.services.knowledge_index_service import (
    KnowledgeIndexKind,
    KnowledgeIndexService,
)
from xenix.services.storage import StorageBootstrapService


class _BatchSettings:
    def load(self):
        return SimpleNamespace(batch_size=8)


class _BlockingSemantic:
    def __init__(self) -> None:
        self.rebuild_entered = threading.Event()
        self.rebuild_release = threading.Event()
        self.inspect_calls = 0

    def is_configured(self) -> bool:
        return True

    def rebuild_generation(self, *, library_id: str, force: bool):
        assert library_id == "global"
        assert force
        self.rebuild_entered.set()
        if not self.rebuild_release.wait(timeout=3):
            raise TimeoutError("Knowledge index rebuild test release timed out.")
        return SimpleNamespace(
            id="generation-1",
            profile_fingerprint="profile-1",
            corpus_fingerprint="corpus-1",
        )

    def inspect_index(self, *, library_id: str):
        assert library_id == "global"
        self.inspect_calls += 1
        return SimpleNamespace(
            configured=True,
            unit_count=0,
            ready=True,
            generation_id="generation-1",
        )


class _BlockingStatusSemantic:
    def __init__(self) -> None:
        self.inspect_entered = threading.Event()
        self.inspect_release = threading.Event()

    def inspect_index(self, *, library_id: str):
        assert library_id == "global"
        self.inspect_entered.set()
        if not self.inspect_release.wait(timeout=3):
            raise TimeoutError("Knowledge index status test release timed out.")
        return SimpleNamespace(
            configured=True,
            unit_count=0,
            ready=False,
            generation_id=None,
        )


def test_status_query_observes_running_rebuild_without_waiting_for_it(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XENIX_APP_HOME", str(tmp_path / "xenix-home"))
    paths = ensure_app_dirs(get_app_paths())
    storage = StorageBootstrapService().initialize(paths)
    semantic = _BlockingSemantic()
    service = KnowledgeIndexService(
        session_factory=storage.session_factory,
        semantic_service=semantic,
        embedding_service=SimpleNamespace(),
        embedding_settings_source=_BatchSettings(),
    )
    try:
        service.enqueue_rebuild(
            (KnowledgeIndexKind.TEXT_VECTOR,),
            trigger="manual",
        )
        assert semantic.rebuild_entered.wait(timeout=3)

        overview = service.request_status().result(timeout=3)

        assert overview.active_task_status == "running"
        assert overview.text_vector_state == "building"
        assert semantic.inspect_calls == 0
    finally:
        semantic.rebuild_release.set()
        service.shutdown()
        storage.engine.dispose()


def test_status_query_lane_does_not_depend_on_rebuild_worker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XENIX_APP_HOME", str(tmp_path / "xenix-home"))
    paths = ensure_app_dirs(get_app_paths())
    storage = StorageBootstrapService().initialize(paths)
    semantic = _BlockingSemantic()
    service = KnowledgeIndexService(
        session_factory=storage.session_factory,
        semantic_service=semantic,
        embedding_service=SimpleNamespace(),
        embedding_settings_source=_BatchSettings(),
        start_worker=False,
    )
    try:
        overview = service.request_status().result(timeout=3)

        assert overview.active_task_status is None
        assert overview.text_vector_state == "unavailable"
        assert semantic.inspect_calls == 1
    finally:
        service.shutdown()
        storage.engine.dispose()


def test_service_shutdown_quiesces_running_status_before_returning(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XENIX_APP_HOME", str(tmp_path / "xenix-home"))
    paths = ensure_app_dirs(get_app_paths())
    storage = StorageBootstrapService().initialize(paths)
    semantic = _BlockingStatusSemantic()
    service = KnowledgeIndexService(
        session_factory=storage.session_factory,
        semantic_service=semantic,
        embedding_service=SimpleNamespace(),
        embedding_settings_source=_BatchSettings(),
        start_worker=False,
    )
    shutdown_returned = threading.Event()

    def shutdown() -> None:
        service.shutdown(timeout=0)
        shutdown_returned.set()

    shutdown_thread: threading.Thread | None = None
    try:
        future = service.request_status()
        assert semantic.inspect_entered.wait(timeout=3)

        shutdown_thread = threading.Thread(target=shutdown, daemon=True)
        shutdown_thread.start()

        assert not shutdown_returned.wait(timeout=0.05)
        semantic.inspect_release.set()
        assert shutdown_returned.wait(timeout=3)
        assert future.done()
    finally:
        semantic.inspect_release.set()
        if shutdown_thread is not None:
            shutdown_thread.join(timeout=3)
        service.shutdown()
        storage.engine.dispose()
