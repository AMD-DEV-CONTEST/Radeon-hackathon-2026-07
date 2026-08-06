from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable, Protocol

from ..build_info import APP_UPDATE_FEED_URL, APP_VERSION
from ..config import AppPaths
from .runtime_activity import ApplicationActivityCoordinator, activity_coordinator
from .update_backup import UpdateBackup, create_update_backup


class UpdateState(StrEnum):
    UNAVAILABLE = "unavailable"
    IDLE = "idle"
    CHECKING = "checking"
    UPDATE_AVAILABLE = "update_available"
    DOWNLOADING = "downloading"
    READY = "ready"
    APPLYING = "applying"
    FAILED = "failed"


@dataclass(frozen=True)
class UpdateStatus:
    state: UpdateState
    installed_version: str
    target_version: str | None = None
    progress: int | None = None
    message: str = ""


class UpdateManagerProtocol(Protocol):
    def check_for_updates(self): ...
    def download_updates(self, update_info, progress_callback=None): ...
    def wait_exit_then_apply_updates(self, update, silent=False, restart=True, restart_args=None): ...


class UpdateService:
    def __init__(
        self,
        paths: AppPaths,
        database_path: Path,
        *,
        manager_factory: Callable[[str], UpdateManagerProtocol] | None = None,
        coordinator: ApplicationActivityCoordinator = activity_coordinator,
    ) -> None:
        self._paths = paths
        self._database_path = database_path
        self._coordinator = coordinator
        self._lock = threading.RLock()
        self._operation_lock = threading.Lock()
        self._update_info = None
        self._manager_factory = manager_factory or self._default_manager_factory
        self._manager: UpdateManagerProtocol | None = None
        self._status = UpdateStatus(
            UpdateState.IDLE if APP_UPDATE_FEED_URL else UpdateState.UNAVAILABLE,
            APP_VERSION,
            message="Update feed is not configured." if not APP_UPDATE_FEED_URL else "",
        )

    @staticmethod
    def _default_manager_factory(feed_url: str) -> UpdateManagerProtocol:
        import velopack

        return velopack.UpdateManager(feed_url)

    @property
    def status(self) -> UpdateStatus:
        with self._lock:
            return self._status

    def _set(self, state: UpdateState, **values) -> UpdateStatus:
        with self._lock:
            self._status = UpdateStatus(state=state, installed_version=APP_VERSION, **values)
            self._persist()
            return self._status

    def _persist(self) -> None:
        path = self._paths.state / "update-state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self._status), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @staticmethod
    def _target_version(update_info) -> str:
        release = getattr(update_info, "TargetFullRelease", None)
        return str(getattr(release, "Version", None) or getattr(release, "version", None) or "unknown")

    def check(self) -> UpdateStatus:
        if not APP_UPDATE_FEED_URL:
            return self.status
        if not self._operation_lock.acquire(blocking=False):
            return self.status
        self._set(UpdateState.CHECKING)
        try:
            self._manager = self._manager_factory(APP_UPDATE_FEED_URL)
            update_info = self._manager.check_for_updates()
            self._update_info = update_info
            if update_info is None:
                return self._set(UpdateState.IDLE, message="Xenix is up to date.")
            return self._set(UpdateState.UPDATE_AVAILABLE, target_version=self._target_version(update_info))
        except Exception as exc:
            return self._set(UpdateState.FAILED, message=str(exc))
        finally:
            self._operation_lock.release()

    def download(self, progress: Callable[[int], None] | None = None) -> UpdateStatus:
        if self._update_info is None:
            raise RuntimeError("Check for updates before downloading.")
        if not self._operation_lock.acquire(blocking=False):
            return self.status
        target = self._target_version(self._update_info)
        self._set(UpdateState.DOWNLOADING, target_version=target, progress=0)

        def report(value: int) -> None:
            self._set(UpdateState.DOWNLOADING, target_version=target, progress=int(value))
            if progress is not None:
                progress(int(value))

        try:
            manager = self._manager or self._manager_factory(APP_UPDATE_FEED_URL)
            self._manager = manager
            manager.download_updates(self._update_info, report)
            return self._set(UpdateState.READY, target_version=target, progress=100)
        except Exception as exc:
            return self._set(UpdateState.FAILED, target_version=target, message=str(exc))
        finally:
            self._operation_lock.release()

    def apply(self, shutdown: Callable[[], None]) -> UpdateBackup:
        if self._update_info is None or self.status.state is not UpdateState.READY:
            raise RuntimeError("No downloaded update is ready to apply.")
        target = self._target_version(self._update_info)
        self._coordinator.begin_update()
        try:
            backup = create_update_backup(
                self._database_path,
                self._paths.state / "update-backups",
                from_version=APP_VERSION,
                to_version=target,
            )
            manager = self._manager or self._manager_factory(APP_UPDATE_FEED_URL)
            manager.wait_exit_then_apply_updates(
                self._update_info, silent=False, restart=True
            )
            self._set(UpdateState.APPLYING, target_version=target)
            shutdown()
            return backup
        except Exception as exc:
            self._coordinator.cancel_update()
            self._set(UpdateState.FAILED, target_version=target, message=str(exc))
            raise
