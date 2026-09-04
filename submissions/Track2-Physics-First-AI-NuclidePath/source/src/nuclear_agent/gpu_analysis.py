"""Optional PyTorch backend for batched deterministic transport evaluation.

PyTorch is deliberately an optional dependency. The scalar implementation in
``transport.py`` remains the canonical reference and CPU fallback.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from .transport import TransportParameters
from .gcs import PrimaryGCSParameters, PrimaryGCSState
from .gcs_primary_accelerated import calculate_primary_kd_tensor


def _torch():
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - exercised without the optional extra
        raise RuntimeError("PyTorch is required for the torch analysis backend") from exc
    return torch


def _scaled_erfc_tensor(torch: Any, log_scale: Any, argument: Any) -> Any:
    """Vector equivalent of transport._scaled_erfc without overflow."""
    direct = torch.exp(log_scale) * torch.special.erfc(argument)
    positive = argument > 8.0
    safe_argument = torch.where(positive, argument, torch.ones_like(argument))
    inverse_square = 1.0 / safe_argument.square()
    correction = (
        1.0
        - 0.5 * inverse_square
        + 0.75 * inverse_square.square()
        - 1.875 * inverse_square.pow(3)
    )
    log_value = (
        log_scale
        - safe_argument.square()
        - torch.log(safe_argument)
        - 0.5 * math.log(math.pi)
        + torch.log(correction)
    )
    asymptotic = torch.exp(log_value)
    return torch.where(positive, asymptotic, direct)


def batched_transport_torch(
    params: TransportParameters,
    distances_m: Sequence[float],
    times_s: Sequence[float],
    *,
    device: str = "cpu",
    dtype: str = "float64",
) -> dict[str, Any]:
    """Evaluate matching ``(distance, time)`` pairs with PyTorch tensors.

    FP64 is the parity-oriented default. FP32 is available for measured
    throughput studies but must not silently replace the canonical scalar path.
    """
    if len(distances_m) == 0 or len(distances_m) != len(times_s):
        raise ValueError("distances and times must have the same non-zero length")
    if any(not math.isfinite(value) or value < 0 for value in (*distances_m, *times_s)):
        raise ValueError("distances and times must be non-negative finite values")
    if dtype not in {"float32", "float64"}:
        raise ValueError("dtype must be float32 or float64")

    torch = _torch()
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("requested ROCm/CUDA device is not available")
    torch_dtype = torch.float64 if dtype == "float64" else torch.float32
    x = torch.as_tensor(distances_m, dtype=torch_dtype, device=device)
    t = torch.as_tensor(times_s, dtype=torch_dtype, device=device)

    retardation = torch.full_like(
        x,
        params.retardation_factor,
    )
    velocity = params.groundwater_velocity_m_s
    dispersion = params.dispersion_m2_s
    decay = params.decay_constant_s
    decay_velocity = math.sqrt(velocity**2 + 4.0 * decay * params.retardation_factor * dispersion)

    safe_t = torch.where(t > 0, t, torch.ones_like(t))
    denominator = 2.0 * torch.sqrt(dispersion * retardation * safe_t)
    first_log_scale = (velocity - decay_velocity) * x / (2.0 * dispersion)
    second_log_scale = (velocity + decay_velocity) * x / (2.0 * dispersion)
    first_argument = (retardation * x - decay_velocity * safe_t) / denominator
    second_argument = (retardation * x + decay_velocity * safe_t) / denominator
    fraction = 0.5 * (
        _scaled_erfc_tensor(torch, first_log_scale, first_argument)
        + _scaled_erfc_tensor(torch, second_log_scale, second_argument)
    )
    fraction = torch.clamp(fraction, 0.0, 1.0)
    concentration = params.initial_concentration_bq_m3 * fraction
    concentration = torch.where(x == 0, params.initial_concentration_bq_m3, concentration)
    concentration = torch.where((x > 0) & (t == 0), 0.0, concentration)

    travel_time = x * retardation / velocity
    result = {
        "backend": "torch",
        "device": str(device),
        "dtype": dtype,
        "concentration_bq_m3": concentration.detach().cpu().tolist(),
        "effective_kd_m3_kg": torch.full_like(
            x, params.effective_distribution_coefficient_m3_kg
        ).detach().cpu().tolist(),
        "retardation_factor": retardation.detach().cpu().tolist(),
        "travel_time_s": travel_time.detach().cpu().tolist(),
    }
    return result


def batched_primary_gcs_torch(
    params: PrimaryGCSParameters,
    states: Sequence[PrimaryGCSState],
    *,
    device: str = "cpu",
    dtype: str = "float64",
):
    """Project analysis entry point for exact batched primary-GCS evaluation."""
    from .gcs_primary_accelerated import calculate_primary_kd_batch
    return calculate_primary_kd_batch(params, states, device=device, dtype=dtype)


def evaluate_scenarios_torch(params: TransportParameters, gcs_params: PrimaryGCSParameters,
                             chemistry: Any, receptor_distances_m: Any, times_s: Any, *,
                             device: str = "cpu", dtype: str = "float64") -> dict[str, Any]:
    """End-to-end tensor pipeline: exact GCS, retardation, reactive Ogata--Banks,
    and receptor × time concentrations. Inputs and primary outputs stay tensors.
    """
    torch = _torch()
    if dtype not in {"float32", "float64"}: raise ValueError("dtype must be float32 or float64")
    if device == "cuda" and not torch.cuda.is_available(): raise RuntimeError("requested device unavailable")
    td = torch.float64 if dtype == "float64" else torch.float32
    c = torch.as_tensor(chemistry, dtype=td, device=device)
    x = torch.as_tensor(receptor_distances_m, dtype=td, device=device).reshape(-1)
    t = torch.as_tensor(times_s, dtype=td, device=device).reshape(-1)
    if c.ndim != 2 or c.shape[1] != 5 or not len(x) or not len(t): raise ValueError("invalid batch shapes")
    if not bool(torch.isfinite(x).all()) or not bool(torch.isfinite(t).all()) or bool((x<0).any()) or bool((t<0).any()): raise ValueError("receptors and times must be finite and nonnegative")
    kd, _ = calculate_primary_kd_tensor(gcs_params, c, device=device, dtype=dtype)
    # Each scenario has one chemistry row; receptor × time is broadcast explicitly.
    retardation = 1 + params.bulk_density_kg_m3 / params.porosity * (kd/1000.0)
    xx = x[None, :, None]; tt = t[None, None, :]; rr = retardation[:, None, None]
    velocity, dispersion, decay = params.groundwater_velocity_m_s, params.dispersion_m2_s, params.decay_constant_s
    safe_t = torch.where(tt > 0, tt, torch.ones_like(tt)); den = 2 * torch.sqrt(dispersion * rr * safe_t)
    dv = torch.sqrt(torch.as_tensor(velocity**2,dtype=td,device=device) + 4 * decay * rr * dispersion)
    a = (velocity-dv)*xx/(2*dispersion); b = (velocity+dv)*xx/(2*dispersion)
    z1 = (rr*xx-dv*safe_t)/den; z2 = (rr*xx+dv*safe_t)/den
    frac = torch.clamp(.5*(_scaled_erfc_tensor(torch,a,z1)+_scaled_erfc_tensor(torch,b,z2)), 0, 1)
    concentration = params.initial_concentration_bq_m3 * frac
    concentration = torch.where(xx == 0, torch.as_tensor(params.initial_concentration_bq_m3, dtype=td, device=device), concentration)
    concentration = torch.where((xx > 0) & (tt == 0), torch.zeros_like(concentration), concentration)
    return {"backend":"torch-exact", "device":str(device), "dtype":dtype,
            "bulk_kd_l_kg":kd, "retardation_factor":retardation,
            "concentration_bq_m3":concentration}
