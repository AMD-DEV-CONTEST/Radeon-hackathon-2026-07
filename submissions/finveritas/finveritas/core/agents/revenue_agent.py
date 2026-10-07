"""Revenue Agent wrapper for the Streamlit dashboard.

This wraps `src.revenue_agent` so the dashboard can run the agent from the
saved OCR output file in `output/`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.revenue_agent import run_revenue_agent


def run(
    *,
    json_path: str | Path,
    base_url: str,
    model: str,
    api_key: str = "local",
    run_id: str | None = None,
) -> dict[str, Any]:
    return run_revenue_agent(
        json_path=Path(json_path),
        base_url=base_url,
        model=model,
        api_key=api_key,
        run_id=run_id,
    )
