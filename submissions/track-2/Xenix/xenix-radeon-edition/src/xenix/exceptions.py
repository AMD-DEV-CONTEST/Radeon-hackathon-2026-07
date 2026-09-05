from __future__ import annotations

import logging
import sys
import threading
import traceback

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QMessageBox

LOGGER = logging.getLogger("xenix.runtime")


class XenixError(Exception):
    """Base class for domain-facing Xenix errors."""


class NotFoundError(XenixError):
    """Raised when a requested entity does not exist."""


class ValidationError(XenixError):
    """Raised when user-provided input is invalid."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        error_details: dict | None = None,
        repair_hints: list[str] | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code.strip() if isinstance(error_code, str) and error_code.strip() else None
        self.error_details = dict(error_details) if isinstance(error_details, dict) and error_details else {}
        self.repair_hints = [
            str(hint).strip()
            for hint in (repair_hints or [])
            if str(hint).strip()
        ]
        self.retryable = retryable if isinstance(retryable, bool) else None


class InvalidStateTransitionError(XenixError):
    """Raised when an entity transition violates the state contract."""


class DatasetSourceMissingError(XenixError):
    """Raised when a registered dataset source file is no longer available."""


class StorageBootstrapError(XenixError):
    """Raised when local storage bootstrap cannot complete."""


def install_exception_hooks() -> None:
    def handle_exception(exc_type: type[BaseException], exc_value: BaseException, exc_traceback: object) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        LOGGER.critical(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

        summary = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        app = QApplication.instance()
        if app is None:
            sys.stderr.write(summary)
            return

        message_box = QMessageBox()
        message_box.setIcon(QMessageBox.Critical)
        message_box.setWindowTitle(QCoreApplication.translate("Exceptions", "Xenix"))
        message_box.setText(
            QCoreApplication.translate(
                "Exceptions",
                "An unexpected error occurred. Check the log file for details.",
            )
        )
        message_box.setDetailedText(summary)
        message_box.exec()

    def handle_thread_exception(args: threading.ExceptHookArgs) -> None:
        handle_exception(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = handle_exception
    threading.excepthook = handle_thread_exception
