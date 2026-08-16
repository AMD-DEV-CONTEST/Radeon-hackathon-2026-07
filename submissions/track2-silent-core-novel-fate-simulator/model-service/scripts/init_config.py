#!/usr/bin/env python3
"""Create deployment secrets once without printing them."""

from pathlib import Path
import secrets


config_path = Path("/persistent/silent-core/config.env")
if not config_path.exists():
    config_path.write_text(
        f"SILENT_CORE_API_KEY=sc_{secrets.token_hex(24)}\n"
        f"SILENT_CORE_INTERNAL_API_KEY=int_{secrets.token_hex(24)}\n",
        encoding="utf-8",
    )
    config_path.chmod(0o600)
