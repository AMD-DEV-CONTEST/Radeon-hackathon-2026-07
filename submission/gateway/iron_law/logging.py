"""ILS structured logger — thin re-export of deploy.logging.structured_logger."""
from deploy.logging.structured_logger import StructuredLogger, get_logger

ILS_LOG_PATH_ENV = "ILS_LOG_PATH"

import os as _os

_ils_log_path = _os.environ.get(ILS_LOG_PATH_ENV)
ils_log: StructuredLogger = get_logger("ils", _ils_log_path)

__all__ = ["ils_log", "get_logger", "StructuredLogger"]
