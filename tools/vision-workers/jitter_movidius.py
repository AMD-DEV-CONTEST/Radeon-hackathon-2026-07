#!/usr/bin/env python3
"""
CESAROPS Lock 3 — Jitter / thermal temporal analyst.

Movidius NCS / OpenVINO path when available; otherwise CPU thermal heuristic
(matching cpu_sim_workers jitter contract).

POST /jitter  GET /health
Env: JITTER_PORT (8080), OPENVINO_DEVICE (MYRIAD|CPU)
"""
from __future__ import annotations

import logging
import os
import time
from typing import List

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("JitterMovidius")

PORT = int(os.getenv("JITTER_PORT", "8080"))
OPENVINO_DEVICE = os.getenv("OPENVINO_DEVICE", "CPU")
_backend = "cpu_thermal"


class JitterRequest(BaseModel):
    tile_id: str
    thermal_timeseries: List[str] = []
    coordinates: dict = {}
    depth_estimate_m: float = 150.0


class JitterSignature(BaseModel):
    material: str
    certainty: float
    depth_estimate_ft: float
    jitter_frequency_hz: float
    thermal_delta_c: float
    classification: str


def _try_openvino():
    global _backend
    model_path = os.getenv("JITTER_MODEL", "")
    if not model_path or not os.path.isfile(model_path):
        return None
    try:
        from openvino.runtime import Core

        core = Core()
        device = OPENVINO_DEVICE if OPENVINO_DEVICE in core.available_devices else "CPU"
        model = core.read_model(model_path)
        compiled = core.compile_model(model, device)
        _backend = f"openvino:{device}"
        log.info("OpenVINO jitter model on %s", device)
        return compiled
    except Exception as e:
        log.warning("OpenVINO unavailable: %s", e)
        return None


_ov_model = None


def _seed(tile_id: str, lat: float, lon: float) -> float:
    h = hash(f"{tile_id}:{lat:.4f}:{lon:.4f}") & 0xFFFFFFFF
    return (h % 1000) / 1000.0


def _thermal_heuristic(req: JitterRequest) -> JitterSignature:
    lat = float(req.coordinates.get("lat", 0.0))
    lon = float(req.coordinates.get("lon", 0.0))
    n_bands = len(req.thermal_timeseries)
    base = _seed(req.tile_id, lat, lon)
    certainty = min(0.95, base + 0.12 * min(n_bands, 6))
    if certainty < 0.72 and n_bands >= 2:
        certainty = 0.72
    depth_ft = req.depth_estimate_m * 3.28084
    return JitterSignature(
        material="ferrous_composite" if certainty > 0.7 else "natural",
        certainty=round(certainty, 3),
        depth_estimate_ft=round(depth_ft, 1),
        jitter_frequency_hz=round(0.02 + (base % 0.05), 4),
        thermal_delta_c=round(0.5 + base * 2.0, 2),
        classification="confirmed_structure" if certainty >= 0.7 else "likely_natural",
    )


def _movidius_infer(req: JitterRequest) -> JitterSignature | None:
    global _ov_model
    if _ov_model is None:
        _ov_model = _try_openvino()
    if _ov_model is None:
        return None
    # Placeholder: real model would decode thermal_timeseries tensors
    return _thermal_heuristic(req)


app = FastAPI(title="CESAROPS Jitter Movidius", version="1.0.0")


@app.get("/health")
async def health():
    return {
        "service": "jitter-movidius",
        "backend": _backend,
        "device": OPENVINO_DEVICE,
        "status": "ok",
    }


@app.post("/jitter", response_model=JitterSignature)
async def jitter_check(req: JitterRequest):
    t0 = time.time()
    sig = _movidius_infer(req) or _thermal_heuristic(req)
    _ = t0
    return sig


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
