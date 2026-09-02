"""Stage J — CLI entry points proxy module.

The actual implementations are in `app.cli.__init__`.
This module exists for backward compatibility with pyproject.toml [project.scripts].
"""

from app.cli import _cli_backup, _cli_health  # noqa: F401
