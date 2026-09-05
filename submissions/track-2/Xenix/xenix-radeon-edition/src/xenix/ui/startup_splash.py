from __future__ import annotations

from enum import Enum
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from xenix.resources import package_resource_path


_STARTUP_FONT_FILES = (
    Path("C:/Windows/Fonts/consola.ttf"),
    Path("C:/Windows/Fonts/consolab.ttf"),
    Path("C:/Windows/Fonts/cour.ttf"),
    Path("C:/Windows/Fonts/courbd.ttf"),
    Path("C:/Windows/Fonts/segoeui.ttf"),
    Path("C:/Windows/Fonts/segoeuib.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("C:/Windows/Fonts/arialbd.ttf"),
)
_STARTUP_FONTS_LOADED = False


class StartupStage(Enum):
    STARTING = "starting"
    PREPARING_APP_DATA = "preparing_app_data"
    LOADING_RUNTIME = "loading_runtime"
    INITIALIZING_LOGGING = "initializing_logging"
    INITIALIZING_STORAGE = "initializing_storage"
    LOADING_WORKBENCH = "loading_workbench"
    READY = "ready"


class StartupPulseBar(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(8)
        self.setMinimumWidth(240)
        self._phase = 0.18
        self._timer = QTimer(self)
        self._timer.setInterval(32)
        self._timer.timeout.connect(self._advance)

    def sizeHint(self) -> QSize:
        return QSize(560, 8)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _advance(self) -> None:
        self._phase = (self._phase + 0.018) % 1.0
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        track = QColor("#d9ded6")
        accent = QColor("#ed6609")

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(rect, 4, 4)

        slider_width = max(72.0, rect.width() * 0.24)
        travel = rect.width() + slider_width
        x = rect.left() - slider_width + travel * self._phase
        slider = QRectF(x, rect.top(), slider_width, rect.height())
        soft_accent = QColor(accent)
        soft_accent.setAlpha(88)
        gradient = QLinearGradient(slider.topLeft(), slider.topRight())
        gradient.setColorAt(0.0, soft_accent)
        gradient.setColorAt(0.5, accent)
        gradient.setColorAt(1.0, soft_accent)
        painter.setClipRect(rect)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(slider, 4, 4)


class StartupSplash(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        flags = Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        super().__init__(parent, flags)
        self.setObjectName("startupSplash")
        self.setFixedSize(680, 400)

        self._stage = StartupStage.STARTING
        self._logo_renderer = QSvgRenderer(str(package_resource_path("app-icon.svg")), self)
        self._stage_label = QLabel(parent=self)
        self._pulse_bar = StartupPulseBar(parent=self)

        self._ensure_text_fonts_loaded()
        self._setup_ui()
        self.retranslate_ui()

    def _setup_ui(self) -> None:
        self._stage_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._stage_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        stage_font = QFont(self._stage_label.font())
        stage_font.setFamilies(["Segoe UI", "Arial", "Sans Serif"])
        stage_font.setPointSize(10)
        stage_font.setBold(True)
        self._stage_label.setFont(stage_font)
        self._apply_label_color(self._stage_label, QColor("#242429"))
        self._position_status_controls()

    def resizeEvent(self, event) -> None:
        self._position_status_controls()
        super().resizeEvent(event)

    def _position_status_controls(self) -> None:
        width = self.width()
        height = self.height()
        self._stage_label.setGeometry(42, height - 62, width - 84, 22)
        self._pulse_bar.setGeometry(42, height - 30, width - 84, 8)

    def show_centered(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            available_geometry = screen.availableGeometry()
            self.move(available_geometry.center() - self.rect().center())
        self.show()
        self.raise_()

    def set_stage(self, stage: StartupStage) -> None:
        self._stage = stage
        self._stage_label.setText(self._stage_text(stage))
        self.update()

    def retranslate_ui(self) -> None:
        self._stage_label.setText(self._stage_text(self._stage))
        self.update()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        panel = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        panel_path = QPainterPath()
        panel_path.addRect(panel)

        self._draw_shell(painter, panel, panel_path)
        painter.setClipPath(panel_path)
        self._draw_signal_field(painter, panel)
        self._draw_brand(painter, panel)
        painter.setClipping(False)

        border = QColor("#242429")
        border.setAlpha(54)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(border, 1))
        painter.drawPath(panel_path)

    def _draw_shell(self, painter: QPainter, panel: QRectF, panel_path: QPainterPath) -> None:
        background = QLinearGradient(panel.topLeft(), panel.bottomRight())
        background.setColorAt(0.0, QColor("#fbfbf8"))
        background.setColorAt(0.58, QColor("#f1f3ee"))
        background.setColorAt(1.0, QColor("#dfe5dd"))
        painter.fillPath(panel_path, background)

        sheen = QLinearGradient(QPointF(panel.left(), panel.top()), QPointF(panel.right(), panel.bottom()))
        highlight = QColor("#ed6609")
        highlight.setAlpha(32)
        transparent = QColor("#ed6609")
        transparent.setAlpha(0)
        sheen.setColorAt(0.0, highlight)
        sheen.setColorAt(0.42, transparent)
        painter.fillPath(panel_path, sheen)

    def _draw_signal_field(self, painter: QPainter, panel: QRectF) -> None:
        graphite = QColor("#242429")
        accent = QColor("#ed6609")
        green = QColor("#1f7a68")

        lane_pen = QColor(graphite)
        lane_pen.setAlpha(26)
        painter.setPen(QPen(lane_pen, 1))
        for index in range(6):
            y = panel.top() + 42 + index * 37
            painter.drawLine(QPointF(panel.left() + 210, y), QPointF(panel.right() - 42, y))

        node_pen = QColor(graphite)
        node_pen.setAlpha(48)
        painter.setPen(QPen(node_pen, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        nodes = [
            QPointF(panel.left() + 446, panel.top() + 74),
            QPointF(panel.left() + 514, panel.top() + 126),
            QPointF(panel.left() + 590, panel.top() + 88),
            QPointF(panel.left() + 558, panel.top() + 190),
        ]
        for start, end in zip(nodes, nodes[1:], strict=False):
            painter.drawLine(start, end)
        for index, point in enumerate(nodes):
            color = QColor(accent if index == 1 else green if index == 3 else graphite)
            color.setAlpha(122)
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(point, 4.5, 4.5)

        accent_fill = QColor(accent)
        accent_fill.setAlpha(18)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent_fill)
        painter.drawRoundedRect(QRectF(panel.right() - 176, panel.top() + 42, 116, 12), 6, 6)
        painter.drawRoundedRect(QRectF(panel.right() - 136, panel.top() + 214, 78, 12), 6, 6)

    def _draw_brand(self, painter: QPainter, panel: QRectF) -> None:
        mark_rect = QRectF(panel.left() + 48, panel.top() + 56, 138, 138)
        if self._logo_renderer.isValid():
            self._logo_renderer.render(painter, mark_rect)

        brand_font = QFont(self.font())
        brand_font.setFamilies(["Consolas", "Courier New", "Lucida Console", "Monospace"])
        brand_font.setPointSize(54)
        brand_font.setWeight(QFont.Weight.Bold)
        painter.setFont(brand_font)
        painter.setPen(QColor("#242429"))
        painter.drawText(
            QRectF(panel.left() + 208, panel.top() + 62, 300, 94),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "Xenix",
        )

    def _stage_text(self, stage: StartupStage) -> str:
        stage_text = {
            StartupStage.STARTING: self.tr("Starting Xenix..."),
            StartupStage.PREPARING_APP_DATA: self.tr("Preparing application data..."),
            StartupStage.LOADING_RUNTIME: self.tr("Loading runtime components..."),
            StartupStage.INITIALIZING_LOGGING: self.tr("Initializing runtime logging..."),
            StartupStage.INITIALIZING_STORAGE: self.tr("Initializing local database..."),
            StartupStage.LOADING_WORKBENCH: self.tr("Loading workbench..."),
            StartupStage.READY: self.tr("Ready."),
        }
        return stage_text[stage]

    @staticmethod
    def _apply_label_color(label: QLabel, color: QColor) -> None:
        palette = QPalette(label.palette())
        palette.setColor(QPalette.ColorRole.WindowText, color)
        label.setPalette(palette)

    @staticmethod
    def _ensure_text_fonts_loaded() -> None:
        global _STARTUP_FONTS_LOADED

        if _STARTUP_FONTS_LOADED or QFontDatabase.families():
            _STARTUP_FONTS_LOADED = True
            return

        for font_path in _STARTUP_FONT_FILES:
            if font_path.is_file():
                QFontDatabase.addApplicationFont(str(font_path))
        _STARTUP_FONTS_LOADED = True
