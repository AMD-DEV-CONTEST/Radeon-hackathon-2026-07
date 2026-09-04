"""Source-faithful Bradbury (2000) validation scenarios and GCS envelopes.

These are reconstructions from Tables 4–5, not digitized measured-isotherm
validation. All predictions call the canonical primary GCS oracle.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
import math
from pathlib import Path
import random
from types import MappingProxyType
from typing import Any, Mapping

from .gcs import (
    PrimaryGCSState, PrimaryGCSParameters, calculate_primary_kd,
    load_primary_gcs_parameters,
)

HERE = Path(__file__).parent
DEFAULT_PARAMS = HERE / "data/parameters/bradbury_baeyens_gcs_v2.json"
PDF_HASH = "8a9a90a8a8e414b8936c4ab9c3e923023424b7159c66ca1418d7bdf83dbb78ac"
DOI = "10.1016/S0169-7722(99)00094-7"


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _finite_range(name: str, value, *, fraction=False):
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"invalid {name}")
    result = tuple(value)
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
           for x in result) or result[0] > result[1]:
        raise ValueError(f"invalid {name}")
    if fraction and (result[0] < 0 or result[1] > 1):
        raise ValueError(f"invalid {name}")
    return result


@dataclass(frozen=True)
class BradburyMineralogy:
    illite_weight_fraction_range: tuple[float, float]
    quartz_weight_percent: float | None = None
    quartz_weight_percent_range: tuple[float, float] | None = None
    carbonates_weight_percent_range: tuple[float, float] | None = None
    siderite_weight_percent_range: tuple[float, float] | None = None
    smectite_weight_fraction_range: tuple[float, float] | None = None
    kaolinite_weight_fraction_range: tuple[float, float] | None = None
    chlorite_weight_fraction_range: tuple[float, float] | None = None
    illite_smectite_mixed_layer_fraction_range: tuple[float, float] | None = None
    chlorite_smectite_mixed_layer_fraction_range: tuple[float, float] | None = None
    pyrite_weight_percent_range: tuple[float, float] | None = None
    pyrite_weight_percent: float | None = None
    k_feldspar_weight_percent_range: tuple[float, float] | None = None
    k_feldspar_note: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "illite_weight_fraction_range",
                           _finite_range("illite range", self.illite_weight_fraction_range, fraction=True))
        for name in ("smectite_weight_fraction_range", "kaolinite_weight_fraction_range",
                     "chlorite_weight_fraction_range", "illite_smectite_mixed_layer_fraction_range",
                     "chlorite_smectite_mixed_layer_fraction_range"):
            object.__setattr__(self, name, _finite_range(name, getattr(self, name), fraction=True))
        for name in ("quartz_weight_percent_range", "carbonates_weight_percent_range",
                     "siderite_weight_percent_range", "pyrite_weight_percent_range",
                     "k_feldspar_weight_percent_range"):
            object.__setattr__(self, name, _finite_range(name, getattr(self, name)))
        for name in ("quartz_weight_percent", "pyrite_weight_percent"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not math.isfinite(value) or value < 0):
                raise ValueError(f"invalid {name}")


@dataclass(frozen=True)
class BradburyWaterChemistry:
    sodium_mol_l: float | None = None
    potassium_mol_l: float | None = None
    ammonium_mol_l: float | None = None
    calcium_mol_l: float | None = None
    magnesium_mol_l: float | None = None
    strontium_mol_l: float | None = None
    cesium_mol_l: float | None = None
    chloride_mol_l: float | None = None
    carbonate_mol_l: float | None = None
    sulfate_mol_l: float | None = None
    fluoride_mol_l: float | None = None
    ph: float | None = None

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"invalid {name}")
            if name == "ph":
                if not 0 <= value <= 14: raise ValueError("invalid pH")
            elif value < 0: raise ValueError(f"invalid {name}")


@dataclass(frozen=True)
class BradburyRock:
    name: str
    location: str
    mineralogy: BradburyMineralogy
    water_chemistry: BradburyWaterChemistry
    provenance: Mapping[str, Any]

    def __post_init__(self):
        if not all(isinstance(x, str) and x.strip() for x in (self.name, self.location)):
            raise ValueError("rock name/location required")
        required = {"basis", "source", "tables", "primary_paper_verified", "doi",
                    "supplied_pdf_sha256", "note"}
        if (not isinstance(self.provenance, Mapping) or set(self.provenance) != required
                or self.provenance["basis"] != "paper_tables_4_5"
                or self.provenance["primary_paper_verified"] is not True
                or self.provenance["doi"] != DOI
                or self.provenance["supplied_pdf_sha256"] != PDF_HASH):
            raise ValueError("invalid primary-paper provenance")
        object.__setattr__(self, "provenance", _freeze(dict(self.provenance)))


def load_bradbury_rocks_v1(path: str | Path) -> tuple[BradburyRock, ...]:
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("malformed benchmark record") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "citation", "rocks"} or raw["schema_version"] != "1.0.0":
        raise ValueError("unsupported benchmark schema")
    if not isinstance(raw["citation"], str) or not isinstance(raw["rocks"], list):
        raise ValueError("invalid benchmark record")
    rock_fields = {"name", "location", "mineralogy", "water_chemistry", "provenance"}
    mineral_fields = set(BradburyMineralogy.__dataclass_fields__)
    chemistry_fields = set(BradburyWaterChemistry.__dataclass_fields__)
    result = []
    for item in raw["rocks"]:
        if not isinstance(item, dict) or set(item) != rock_fields:
            raise ValueError("invalid rock schema")
        mineral = item["mineralogy"]
        chemistry = item["water_chemistry"]
        if not isinstance(mineral, dict) or set(mineral) - mineral_fields:
            raise ValueError("unknown mineralogy field")
        if not isinstance(chemistry, dict) or set(chemistry) != chemistry_fields:
            raise ValueError("invalid water chemistry schema")
        converted = dict(mineral)
        for key, value in tuple(converted.items()):
            if key.endswith("_range") and value is not None: converted[key] = tuple(value)
        result.append(BradburyRock(item["name"], item["location"],
                                   BradburyMineralogy(**converted),
                                   BradburyWaterChemistry(**chemistry), item["provenance"]))
    if tuple(rock.name for rock in result) != ("Boom Clay", "Oxford Clay", "Palfris Marl", "Opalinus Clay"):
        raise ValueError("unexpected benchmark rock collection")
    return tuple(result)


def _chemistry_state(rock: BradburyRock, cs: float, illite: float) -> PrimaryGCSState:
    chemistry = rock.water_chemistry
    if chemistry.potassium_mol_l is None or chemistry.sodium_mol_l is None:
        raise ValueError("paper reconstruction requires reported K and Na")
    return PrimaryGCSState(cs, chemistry.potassium_mol_l, chemistry.sodium_mol_l,
                           0.0 if chemistry.ammonium_mol_l is None else chemistry.ammonium_mol_l,
                           illite, chemistry.ph)


def _grid() -> tuple[float, ...]:
    return tuple(10 ** (-9 + 6 * index / 24) for index in range(25))


def predict_cs_isotherm_envelope(rock: BradburyRock, parameter_path: str | Path = DEFAULT_PARAMS) -> Mapping[str, Any]:
    if not isinstance(rock, BradburyRock): raise ValueError("BradburyRock required")
    params = load_primary_gcs_parameters(parameter_path)
    concentrations = _grid()
    low, high = rock.mineralogy.illite_weight_fraction_range
    def values(fraction):
        return tuple(calculate_primary_kd(params, _chemistry_state(rock, cs, fraction)).bulk_kd_l_kg
                     for cs in concentrations)
    return _freeze({
        "label": "paper-input reconstruction, not digitized measured validation",
        "model_version": "bradbury-baeyens-gcs-2.0",
        "missing_nh4_treatment": "unreported NH4 treated as absent (0 mol/L)",
        "lower_illite_envelope": {"illite_fraction": low, "cs_concentrations_mol_l": concentrations,
                                  "predicted_kd_l_kg": values(low)},
        "upper_illite_envelope": {"illite_fraction": high, "cs_concentrations_mol_l": concentrations,
                                  "predicted_kd_l_kg": values(high)},
    })


def _perturb_systematic(params: PrimaryGCSParameters, shift: float) -> PrimaryGCSParameters:
    factor = 10 ** shift
    # Apply the same systematic shift to Cs/K and Cs/Na. Their ratio, and thus
    # Eq. 8 K/Na selectivity, remains exactly unchanged. K/Na and NH4/K are fixed.
    sites = tuple(replace(site, kc_cs_k=site.kc_cs_k * factor,
                          kc_cs_na=site.kc_cs_na * factor) for site in params.sites)
    return replace(params, sites=sites)


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = int(math.floor(position)); upper = int(math.ceil(position))
    if lower == upper: return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def sample_selectivity_uncertainty(rock: BradburyRock, seed: int = 42, n_samples: int = 1000,
                                   parameter_path: str | Path = DEFAULT_PARAMS) -> Mapping[str, Any]:
    if not isinstance(rock, BradburyRock): raise ValueError("BradburyRock required")
    if isinstance(seed, bool) or not isinstance(seed, int): raise ValueError("seed must be int")
    if isinstance(n_samples, bool) or not isinstance(n_samples, int) or n_samples < 1:
        raise ValueError("n_samples must be positive int")
    params = load_primary_gcs_parameters(parameter_path)
    rng = random.Random(seed)
    shifts = tuple(rng.uniform(-params.selectivity_uncertainty_log10,
                               params.selectivity_uncertainty_log10) for _ in range(n_samples))
    concentrations = _grid()
    low, high = rock.mineralogy.illite_weight_fraction_range
    middle = (low + high) / 2
    sampled = [[] for _ in concentrations]
    for shift in shifts:
        perturbed = _perturb_systematic(params, shift)
        for index, cs in enumerate(concentrations):
            sampled[index].append(calculate_primary_kd(
                perturbed, _chemistry_state(rock, cs, middle)).bulk_kd_l_kg)
    result = {}
    for name, probability in (("p05", .05), ("p50", .5), ("p95", .95)):
        result[name] = {"cs_concentrations_mol_l": concentrations,
                        "predicted_kd_l_kg": tuple(_quantile(row, probability) for row in sampled)}
    result.update({
        "sampled_log10_shifts": shifts,
        "uncertainty_interpretation": {
            "classification": "demonstrative-systematic",
            "distribution": "uniform",
            "range_log10": (-params.selectivity_uncertainty_log10,
                             params.selectivity_uncertainty_log10),
            "correlation": "perfectly correlated shift of Cs/K and Cs/Na across sites",
            "limitation": "Bradbury reports ±0.2 log units but does not prescribe this probability distribution/correlation model",
            "eq8_preserved": True,
        },
    })
    return _freeze(result)
