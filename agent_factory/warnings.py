from __future__ import annotations

import warnings


def configure_warning_filters() -> None:
    warnings.filterwarnings(
        "ignore",
        message=r"The default value of `allowed_objects` will change.*",
        category=Warning,
    )
