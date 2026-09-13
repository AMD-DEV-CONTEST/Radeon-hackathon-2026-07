"""
Benchmarks API — serves the most recent GPU benchmark report (produced by
benchmarks/benchmark_inference.py) to the frontend's GPU dashboard (Phase 14),
plus the live custom Prometheus gauges for a real-time view between runs.
"""
import json
from pathlib import Path

from fastapi import APIRouter

from app.core.metrics import INFERENCE_TOKENS_PER_SECOND, get_last_tokens_per_second

router = APIRouter()

_RESULTS_DIR = Path(__file__).resolve().parents[5] / "benchmarks" / "results"


@router.get("/latest")
async def latest_benchmark() -> dict:
    if not _RESULTS_DIR.exists():
        return {"available": False, "reason": "No benchmark runs found. Run benchmarks/benchmark_inference.py."}

    files = sorted(_RESULTS_DIR.glob("*.json"))
    if not files:
        return {"available": False, "reason": "No benchmark runs found. Run benchmarks/benchmark_inference.py."}

    latest = json.loads(files[-1].read_text())
    return {"available": True, "report": latest}


@router.get("/live")
async def live_metrics() -> dict:
    return {"current_tokens_per_second": get_last_tokens_per_second()}
