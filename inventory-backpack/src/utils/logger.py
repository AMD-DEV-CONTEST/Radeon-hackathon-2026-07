"""
Logging configuration - structured, no redundant output
"""

import logging
import sys
from typing import Optional


def setup_logging(level: str = "INFO", log_file: Optional[str] = None) -> None:
    """
    Configure logging - unified entry

    Design:
    - Single handler, avoid duplication
    - Structured format, easy to parse
    - Control third-party library log levels
    """

    # Root logger configuration
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ] + ([logging.FileHandler(log_file)] if log_file else []),
    )

    # Reduce third-party library log verbosity
    for logger_name in ["httpx", "httpcore", "uvicorn"]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
