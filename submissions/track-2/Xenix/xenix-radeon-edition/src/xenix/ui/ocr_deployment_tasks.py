from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QRunnable, Signal

from ..exceptions import ValidationError
from ..services.paddle_ocr_service import (
    PaddleOcrDeploymentService,
    PaddleOcrState,
    PaddleOcrStatus,
)

LOGGER = logging.getLogger(__name__)


class OcrStatusSignals(QObject):
    finished = Signal(int, object)


class OcrStatusTask(QRunnable):
    def __init__(self, deployment: PaddleOcrDeploymentService, generation: int) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self._deployment = deployment
        self._generation = generation
        self.signals = OcrStatusSignals()

    def run(self) -> None:
        try:
            status_reader = getattr(self._deployment, "status_snapshot", None)
            if status_reader is None:
                status_reader = self._deployment.status
            status = status_reader()
            if status.state is PaddleOcrState.CHECKING:
                status = self._deployment.verify_active()
        except Exception:
            status = PaddleOcrStatus(
                PaddleOcrState.REPAIR_REQUIRED,
                "status_unavailable",
            )
        self.signals.finished.emit(self._generation, status)


class OcrInstallSignals(QObject):
    phase = Signal(int, str)
    finished = Signal(int, object)


class OcrInstallTask(QRunnable):
    def __init__(self, deployment: PaddleOcrDeploymentService, generation: int) -> None:
        super().__init__()
        self.setAutoDelete(False)
        self._deployment = deployment
        self._generation = generation
        self.signals = OcrInstallSignals()

    def run(self) -> None:
        try:
            status = self._deployment.install(
                lambda phase: self.signals.phase.emit(self._generation, phase)
            )
        except Exception as exc:
            code = (
                exc.error_code
                if isinstance(exc, ValidationError)
                and isinstance(exc.error_code, str)
                and exc.error_code.startswith("knowledge_ocr_")
                else "knowledge_ocr_setup_failed"
            )
            LOGGER.warning("Local OCR setup failed: %s", code)
            status = PaddleOcrStatus(PaddleOcrState.FAILED, code)
        self.signals.finished.emit(self._generation, status)


__all__ = ["OcrInstallTask", "OcrStatusTask"]
