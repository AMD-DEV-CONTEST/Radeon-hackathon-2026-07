"""
Logging module for the Worldview Database System.
Provides structured logging with rotation, log level management,
and utility functions for consistent log formatting.
"""
import os
import re
import sys
import logging
import logging.handlers
import logging.config
from datetime import datetime
from typing import Optional

LOG_DIR = "logs"

# Ensure log directory exists
os.makedirs(LOG_DIR, exist_ok=True)

# ── Log Level Configuration ──
LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}
DEFAULT_LEVEL = "INFO"

# ── Loggers ──
_app_logger: Optional[logging.Logger] = None
_error_logger: Optional[logging.Logger] = None
_access_logger: Optional[logging.Logger] = None


_SENSITIVE_LOG_PATTERNS = (
    re.compile(r"(?i)\b(nvk_(?:admin_)?)\S+"),
    re.compile(r"(?i)\b(sk-)[A-Za-z0-9._-]+"),
    re.compile(r"(?i)\b(bearer)\s+\S+"),
    re.compile(
        r"(?i)\b(authorization|x-api-key|api[_-]?key|password)"
        r"(\s*[:=]\s*)([^\s,;]+)"
    ),
)


def redact_sensitive_text(value: object) -> str:
    """Remove credential-shaped values before a message reaches any handler."""
    text = str(value)
    text = _SENSITIVE_LOG_PATTERNS[0].sub("[REDACTED_CREDENTIAL]", text)
    text = _SENSITIVE_LOG_PATTERNS[1].sub("[REDACTED_CREDENTIAL]", text)
    text = _SENSITIVE_LOG_PATTERNS[2].sub(r"\1 [REDACTED]", text)
    return _SENSITIVE_LOG_PATTERNS[3].sub(r"\1\2[REDACTED]", text)


class _RedactingFormatter:
    def __init__(self, formatter: logging.Formatter):
        self._formatter = formatter

    def format(self, record: logging.LogRecord) -> str:
        return redact_sensitive_text(self._formatter.format(record))


def _protect_handler(handler: logging.Handler) -> None:
    formatter = handler.formatter or logging.Formatter()
    if not isinstance(formatter, _RedactingFormatter):
        handler.setFormatter(_RedactingFormatter(formatter))


def _protect_configured_handlers() -> None:
    seen: set[int] = set()
    for logger in (
        logging.getLogger(),
        logging.getLogger("app"),
        logging.getLogger("error"),
        logging.getLogger("access"),
    ):
        for handler in logger.handlers:
            if id(handler) not in seen:
                _protect_handler(handler)
                seen.add(id(handler))


def _create_handler(
    filename: str,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    level: int = logging.INFO,
    fmt: Optional[str] = None,
) -> logging.Handler:
    """Create a rotating file handler with consistent formatting."""
    if fmt is None:
        fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    handler = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_DIR, filename),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(_RedactingFormatter(logging.Formatter(fmt)))
    return handler


def load_logging_config(config_path: str = "logging.conf") -> bool:
    """Load logging config from file (V1.23). Falls back to programmatic."""
    if not os.path.exists(config_path):
        return False
    try:
        logging.config.fileConfig(config_path, disable_existing_loggers=False)
        global _app_logger, _error_logger, _access_logger
        _app_logger = logging.getLogger("app")
        _error_logger = logging.getLogger("error")
        _access_logger = logging.getLogger("access")
        _protect_configured_handlers()
        return True
    except Exception as e:
        print(f"Warning: failed to load {config_path}: {e}")
        return False

def init_logging(level: str = DEFAULT_LEVEL, log_dir: str = LOG_DIR) -> None:
    """Initialize all loggers. Tries logging.conf first."""
    if load_logging_config():
        return
    global _app_logger, _error_logger, _access_logger, LOG_DIR
    LOG_DIR = log_dir
    os.makedirs(LOG_DIR, exist_ok=True)

    log_level = LOG_LEVEL_MAP.get(level.upper(), logging.INFO)

    # ── Application Logger ──
    _app_logger = logging.getLogger("app")
    _app_logger.setLevel(log_level)
    _app_logger.handlers.clear()
    _app_logger.addHandler(
        _create_handler("app.log", level=log_level)
    )
    # Also log to console
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(log_level)
    console.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    ))
    _protect_handler(console)
    _app_logger.addHandler(console)

    # ── Error Logger (ERROR and above only) ──
    _error_logger = logging.getLogger("error")
    _error_logger.setLevel(logging.ERROR)
    _error_logger.handlers.clear()
    _error_logger.addHandler(
        _create_handler("error.log", level=logging.ERROR)
    )

    # ── Access Logger (request/response logging) ──
    _access_logger = logging.getLogger("access")
    _access_logger.setLevel(logging.INFO)
    _access_logger.handlers.clear()
    _access_logger.addHandler(
        _create_handler(
            "access.log",
            fmt="%(asctime)s | %(message)s",
        )
    )


def get_logger() -> logging.Logger:
    """Get the main application logger."""
    if _app_logger is None:
        init_logging()
    return _app_logger


def get_error_logger() -> logging.Logger:
    """Get the error logger (ERROR level only)."""
    if _error_logger is None:
        init_logging()
    return _error_logger


def get_access_logger() -> logging.Logger:
    """Get the access logger for request/response tracking."""
    if _access_logger is None:
        init_logging()
    return _access_logger


def log_access(method: str, path: str, status: int, duration_ms: float, client_ip: str = "") -> None:
    """Log an HTTP access with consistent format."""
    logger = get_access_logger()
    logger.info("%s %s %d %.1fms %s", method, path, status, duration_ms, client_ip)


def read_logs(
    log_type: str = "app",
    lines: int = 100,
    level: Optional[str] = None,
    keyword: Optional[str] = None,
) -> list:
    """Read log file contents. Returns list of log lines."""
    filenames = {
        "app": "app.log",
        "error": "error.log",
        "access": "access.log",
    }
    filename = filenames.get(log_type, "app.log")
    log_path = os.path.join(LOG_DIR, filename)

    if not os.path.exists(log_path):
        return []

    with open(log_path, "r", encoding="utf-8") as f:
        all_lines = f.readlines()

    # Filter by level
    if level:
        level_upper = level.upper()
        all_lines = [l for l in all_lines if level_upper in l]

    # Filter by keyword
    if keyword:
        keyword_lower = keyword.lower()
        all_lines = [l for l in all_lines if keyword_lower in l.lower()]

    # Return last N lines
    return all_lines[-lines:]


def get_log_stats() -> dict:
    """Get statistics about log files."""
    stats = {}
    for name in ["app.log", "error.log", "access.log"]:
        path = os.path.join(LOG_DIR, name)
        if os.path.exists(path):
            size = os.path.getsize(path)
            with open(path, "r", encoding="utf-8") as f:
                line_count = sum(1 for _ in f)
            # Count by level
            level_counts = {"INFO": 0, "WARNING": 0, "ERROR": 0, "DEBUG": 0}
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    for lv in level_counts:
                        if lv in line:
                            level_counts[lv] += 1
                            break
            stats[name] = {
                "size_bytes": size,
                "size_human": f"{size/1024:.1f} KB" if size < 1024*1024 else f"{size/(1024*1024):.1f} MB",
                "lines": line_count,
                "levels": level_counts,
            }
        else:
            stats[name] = {"size_bytes": 0, "size_human": "0 B", "lines": 0, "levels": {}}
    return stats

