"""Configuration for native runtime mode selection."""

import os


def is_local_runtime_enabled() -> bool:
    """The application has one local runtime implementation."""
    return True
