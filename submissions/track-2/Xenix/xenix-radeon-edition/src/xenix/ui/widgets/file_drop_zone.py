from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from ..native_widgets import emphasize_label


class FileDropZone(QFrame):
    file_dropped = Signal(str)

    def __init__(self, parent: QFrame | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.StyledPanel)
        self.setObjectName("fileDropZone")

        self._title_label = QLabel()
        self._subtitle_label = QLabel()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(6)

        self._title_label.setAlignment(Qt.AlignCenter)
        emphasize_label(self._title_label)

        self._subtitle_label.setAlignment(Qt.AlignCenter)
        self._subtitle_label.setWordWrap(True)

        layout.addWidget(self._title_label)
        layout.addWidget(self._subtitle_label)

        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self._title_label.setText(self.tr("Drop a dataset file here"))
        self._subtitle_label.setText(self.tr("Supports .csv, .xlsx, and .xls"))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        mime_data = event.mimeData()
        if mime_data is not None and any(url.isLocalFile() for url in mime_data.urls()):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event) -> None:  # type: ignore[override]
        mime_data = event.mimeData()
        if mime_data is None:
            event.ignore()
            return

        for url in mime_data.urls():
            if url.isLocalFile():
                self.file_dropped.emit(url.toLocalFile())
                event.acceptProposedAction()
                return
        event.ignore()
