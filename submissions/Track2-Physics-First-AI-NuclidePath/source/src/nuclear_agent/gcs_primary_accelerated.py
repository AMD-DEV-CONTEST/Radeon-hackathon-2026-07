"""Optional exact batched PyTorch backend for the primary Bradbury GCS model.

This is acceleration, not a learned surrogate: it evaluates the same mass-action
formula as ``calculate_primary_kd`` and introduces no approximation parameters.
PyTorch names ROCm devices ``cuda`` as well as NVIDIA CUDA devices.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Sequence

from .gcs import PrimaryGCSParameters, PrimaryGCSState

try:
    import torch
except ImportError:  # dependency-free core remains supported
    torch = None


@dataclass(frozen=True)
class PrimaryBatchResult:
    bulk_kd_l_kg: tuple[float, ...]
    illite_kd_l_kg: tuple[float, ...]
    backend: str
    device: str
    dtype: str
    approximation: bool = False
    # Optional device-resident values for downstream tensor pipelines.
    bulk_kd_tensor: Any = None
    illite_kd_tensor: Any = None

    def __post_init__(self):
        if (not self.bulk_kd_l_kg or len(self.bulk_kd_l_kg) != len(self.illite_kd_l_kg)
                or any(not math.isfinite(x) or x < 0
                       for x in (*self.bulk_kd_l_kg, *self.illite_kd_l_kg))):
            raise ValueError("invalid primary GCS batch result")
        if self.backend != "torch-exact" or self.approximation is not False:
            raise ValueError("invalid primary GCS backend declaration")


def calculate_primary_kd_batch(
    params: PrimaryGCSParameters,
    states: Sequence[PrimaryGCSState],
    *,
    device: str = "cpu",
    dtype: str = "float64",
) -> PrimaryBatchResult:
    """Evaluate a batch with the exact primary-paper mass-action equations.

    ``float64`` is the parity path. ``float32`` is available for throughput and
    callers must apply their own declared tolerance. No surrogate/fitted weights
    are involved.
    """
    if torch is None:
        raise RuntimeError("PyTorch is required for the exact batched GCS backend")
    if not isinstance(params, PrimaryGCSParameters):
        raise ValueError("primary GCS parameters are required")
    if not isinstance(states, (list, tuple)) or not states:
        raise ValueError("states must be a non-empty list or tuple")
    if any(not isinstance(state, PrimaryGCSState) for state in states):
        raise ValueError("every batch item must be PrimaryGCSState")
    if dtype not in {"float32", "float64"}:
        raise ValueError("dtype must be float32 or float64")
    if device not in {"cpu", "cuda"}:
        raise ValueError("device must be cpu or cuda")
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA/ROCm device requested but unavailable")

    tdtype = {"float32": torch.float32, "float64": torch.float64}[dtype]
    concentrations = torch.tensor(
        [[s.cesium_mol_l, s.potassium_mol_l, s.sodium_mol_l,
          s.ammonium_mol_l, s.illite_mass_fraction] for s in states],
        dtype=tdtype, device=device,
    )
    capacities = torch.tensor(
        [s.capacity_mol_charge_per_kg for s in params.sites],
        dtype=tdtype, device=device,
    )
    kc_cs_k = torch.tensor([s.kc_cs_k for s in params.sites], dtype=tdtype, device=device)
    kc_k_na = torch.tensor([s.kc_k_na for s in params.sites], dtype=tdtype, device=device)
    kc_nh4_k = torch.tensor(
        [0.0 if s.kc_nh4_k is None else s.kc_nh4_k for s in params.sites],
        dtype=tdtype, device=device,
    )

    cs = concentrations[:, 0:1]
    k = concentrations[:, 1:2]
    na = concentrations[:, 2:3]
    nh4 = concentrations[:, 3:4]
    illite = concentrations[:, 4]
    weights_cs = cs * kc_cs_k
    denominator = k + na / kc_k_na + weights_cs + nh4 * kc_nh4_k
    occupancies = capacities * weights_cs / denominator
    illite_kd = occupancies.sum(dim=1) / concentrations[:, 0]
    bulk_kd = illite_kd * illite

    if not bool(torch.isfinite(bulk_kd).all()) or bool((bulk_kd < 0).any()):
        raise ValueError("exact batched GCS calculation produced invalid output")
    return PrimaryBatchResult(
        tuple(float(x) for x in bulk_kd.detach().cpu().tolist()),
        tuple(float(x) for x in illite_kd.detach().cpu().tolist()),
        "torch-exact", str(device), dtype, False, bulk_kd, illite_kd,
    )


def calculate_primary_kd_tensor(params: PrimaryGCSParameters, concentrations: Any, *, device: str = "cpu", dtype: str = "float64") -> tuple[Any, Any]:
    """Exact primary GCS kernel with tensor input/output and no host transfer.

    Columns are Cs, K, Na, NH4 (mol/L), and illite mass fraction.
    """
    if torch is None:
        raise RuntimeError("PyTorch is required for the exact batched GCS backend")
    if dtype not in {"float32", "float64"}:
        raise ValueError("dtype must be float32 or float64")
    if not isinstance(params,PrimaryGCSParameters): raise ValueError("primary GCS parameters required")
    if not hasattr(concentrations,"to"): raise ValueError("concentrations must be a tensor")
    t = concentrations.to(device=device, dtype={"float32":torch.float32,"float64":torch.float64}[dtype])
    if t.ndim != 2 or t.shape[1] != 5:
        raise ValueError("concentrations must have shape (batch, 5)")
    if not bool(torch.isfinite(t).all()): raise ValueError("concentrations must be finite")
    if bool((t[:,:4] < 0).any()) or bool((t[:,0] <= 0).any()): raise ValueError("invalid aqueous concentrations")
    if bool(((t[:,1] <= 0) & (t[:,2] <= 0)).any()): raise ValueError("positive K or Na required")
    if bool(((t[:,4] < 0) | (t[:,4] > 1)).any()): raise ValueError("illite fraction must be in [0,1]")
    capacities = torch.as_tensor([s.capacity_mol_charge_per_kg for s in params.sites], dtype=t.dtype, device=t.device)
    cs, k, na, nh4, illite = (t[:, i] for i in range(5))
    w = cs[:, None] * torch.as_tensor([s.kc_cs_k for s in params.sites], dtype=t.dtype, device=t.device)
    den = k[:, None] + na[:, None] / torch.as_tensor([s.kc_k_na for s in params.sites], dtype=t.dtype, device=t.device) + w + nh4[:, None] * torch.as_tensor([s.kc_nh4_k or 0.0 for s in params.sites], dtype=t.dtype, device=t.device)
    illite_kd = (capacities * w / den).sum(1) / cs
    return illite_kd * illite, illite_kd
