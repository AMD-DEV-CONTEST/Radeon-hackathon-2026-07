from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import QLocale, QTranslator
from PySide6.QtWidgets import QApplication

from .config import AppPaths, package_root

LOGGER = logging.getLogger("xenix.i18n")

DEFAULT_LOCALE = "en_US"
SUPPORTED_LOCALES = ("en_US", "zh_CN")
LOCALE_CONFIG_NAME = "locale.json"
TRANSLATION_BASENAME = "xenix"


def locale_config_path(paths: AppPaths) -> Path:
    return paths.config / LOCALE_CONFIG_NAME


def translation_file_path(locale_code: str) -> Path:
    return package_root() / "translations" / f"{TRANSLATION_BASENAME}_{locale_code}.qm"


def normalize_locale(locale_name: str | None) -> str | None:
    if not locale_name:
        return None

    normalized = locale_name.replace("-", "_")
    if normalized in SUPPORTED_LOCALES:
        return normalized

    language = normalized.split("_", 1)[0].lower()
    if language == "en":
        return "en_US"
    if language == "zh":
        return "zh_CN"
    return None


def read_saved_locale(paths: AppPaths) -> str | None:
    config_path = locale_config_path(paths)
    if not config_path.exists():
        return None

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        LOGGER.warning("Unable to read locale preference from %s", config_path, exc_info=True)
        return None

    return normalize_locale(str(payload.get("locale"))) if isinstance(payload, dict) else None


def write_saved_locale(paths: AppPaths, locale_code: str) -> None:
    resolved_locale = normalize_locale(locale_code)
    if resolved_locale is None:
        raise ValueError(f"Unsupported locale '{locale_code}'.")

    config_path = locale_config_path(paths)
    config_path.write_text(
        json.dumps({"locale": resolved_locale}, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def resolve_startup_locale(paths: AppPaths, *, system_locale: str | None = None) -> str:
    stored_locale = read_saved_locale(paths)
    if stored_locale is not None:
        return stored_locale

    resolved_system_locale = normalize_locale(system_locale or QLocale.system().name())
    return resolved_system_locale or DEFAULT_LOCALE


class TranslationManager:
    _active_translators: ClassVar[dict[int, QTranslator]] = {}

    def __init__(self, app: QApplication, paths: AppPaths) -> None:
        self._app = app
        self._paths = paths
        self._translator: QTranslator | None = None
        self._current_locale = DEFAULT_LOCALE

    def initialize(self) -> str:
        locale_code = resolve_startup_locale(self._paths)
        self.set_locale(locale_code, persist=False)
        return self._current_locale

    def current_locale(self) -> str:
        return self._current_locale

    def supported_locales(self) -> tuple[str, ...]:
        return SUPPORTED_LOCALES

    def set_locale(self, locale_code: str, *, persist: bool = True) -> bool:
        resolved_locale = normalize_locale(locale_code)
        if resolved_locale is None:
            raise ValueError(f"Unsupported locale '{locale_code}'.")

        app_key = id(self._app)
        active_translator = self._active_translators.get(app_key)
        if resolved_locale == self._current_locale and (
            resolved_locale != DEFAULT_LOCALE or active_translator is None
        ):
            if persist:
                write_saved_locale(self._paths, resolved_locale)
            return False

        next_translator: QTranslator | None = None
        if resolved_locale != DEFAULT_LOCALE:
            translation_path = translation_file_path(resolved_locale)
            if not translation_path.exists():
                raise FileNotFoundError(f"Translation file not found: {translation_path}")
            next_translator = QTranslator(self._app)
            if not next_translator.load(str(translation_path)):
                raise RuntimeError(f"Unable to load translation file '{translation_path}'.")

        if active_translator is not None:
            self._app.removeTranslator(active_translator)
            self._active_translators.pop(app_key, None)
        elif self._translator is not None:
            self._app.removeTranslator(self._translator)

        self._translator = next_translator
        if next_translator is not None:
            self._app.installTranslator(next_translator)
            self._active_translators[app_key] = next_translator
        self._current_locale = resolved_locale

        if persist:
            write_saved_locale(self._paths, resolved_locale)
        return True
