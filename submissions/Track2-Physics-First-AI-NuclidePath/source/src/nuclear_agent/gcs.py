"""Deterministic, deliberately limited Cs/K three-site GCS foundation."""
from __future__ import annotations
from dataclasses import dataclass
import json, math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

def _freeze(value: Any) -> Any:
    if isinstance(value, dict): return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list): return tuple(_freeze(v) for v in value)
    return value

def _validate_provenance(value: Any) -> None:
    required = {"basis", "source", "tables", "primary_paper_verified"}
    if not isinstance(value, Mapping) or not required <= set(value):
        raise ValueError("incomplete parameter provenance")
    if value["basis"] != "secondary_transcription" or value["primary_paper_verified"] is not False:
        raise ValueError("parameter provenance must disclose secondary transcription")
    if not isinstance(value["source"], str) or not value["source"].strip():
        raise ValueError("parameter provenance source must be non-empty")
    if (not isinstance(value["tables"], (list, tuple)) or not value["tables"]
            or any(not isinstance(item, str) or not item.strip() for item in value["tables"])):
        raise ValueError("parameter provenance tables must be non-empty strings")

@dataclass(frozen=True)
class Site:
    name: str; kc: float; capacity_fraction: float; capacity_mol_charge_per_kg: float
    @property
    def capacity_unit(self) -> str: return "mol_charge/kg"
    def __post_init__(self):
        vals=(self.kc,self.capacity_fraction,self.capacity_mol_charge_per_kg)
        if not isinstance(self.name,str) or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or x<=0 for x in vals): raise ValueError("invalid site")

@dataclass(frozen=True)
class IlliteParameters:
    material: str; cec_mol_charge_per_kg: float; cec_unit: str; source_rounding_policy: str; sites: tuple[Site,...]; provenance: Mapping[str,Any]
    def __post_init__(self):
        if self.material != "Illite du Puy":
            raise ValueError("unsupported material")
        if (isinstance(self.cec_mol_charge_per_kg, bool)
                or not isinstance(self.cec_mol_charge_per_kg, (int, float))
                or not math.isfinite(self.cec_mol_charge_per_kg)
                or self.cec_mol_charge_per_kg <= 0):
            raise ValueError("CEC must be finite and positive")
        if self.cec_unit != "mol_charge/kg":
            raise ValueError("unsupported CEC unit")
        if self.source_rounding_policy != "derive_residual_planar":
            raise ValueError("unsupported source rounding policy")
        if (not isinstance(self.sites, tuple) or len(self.sites) != 3
                or any(not isinstance(site, Site) for site in self.sites)
                or tuple(site.name for site in self.sites) != ("FES", "type-II", "planar")):
            raise ValueError("invalid site collection")
        if not math.isclose(
            sum(site.capacity_fraction for site in self.sites), 1.0,
            rel_tol=0.0, abs_tol=1.0e-12,
        ):
            raise ValueError("site fractions must sum to one")
        if not math.isclose(
            sum(site.capacity_mol_charge_per_kg for site in self.sites),
            self.cec_mol_charge_per_kg, rel_tol=1.0e-12, abs_tol=1.0e-15,
        ):
            raise ValueError("site capacities must sum to CEC")
        for site in self.sites:
            if not math.isclose(
                site.capacity_mol_charge_per_kg,
                self.cec_mol_charge_per_kg * site.capacity_fraction,
                rel_tol=1.0e-12, abs_tol=1.0e-15,
            ):
                raise ValueError("site capacity is inconsistent with fraction and CEC")
        _validate_provenance(self.provenance)
        object.__setattr__(self, "provenance", _freeze(dict(self.provenance)))

@dataclass(frozen=True)
class CsKState:
    potassium_mol_l: float; cesium_mol_l: float; illite_mass_fraction: float; competitor: str|None=None; isotope: str="Cs"
    def __post_init__(self):
        vals=(self.potassium_mol_l,self.cesium_mol_l,self.illite_mass_fraction)
        if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in vals): raise ValueError("state values must be finite")
        if self.potassium_mol_l<=0 or self.cesium_mol_l<=0: raise ValueError("K and Cs concentrations must be > 0 mol/L")
        if not 0<=self.illite_mass_fraction<=1: raise ValueError("illite mass fraction must be in [0, 1]")
        if self.competitor is not None or self.isotope!="Cs": raise ValueError("only Cs/K chemistry is supported")

@dataclass(frozen=True)
class KdResult:
    occupancies: tuple[float,...]; total_sorbed_cs_mol_per_kg: float; illite_kd_l_kg: float; bulk_kd_l_kg: float; provenance: Mapping[str,Any]
    def __post_init__(self):
        values = (*self.occupancies, self.total_sorbed_cs_mol_per_kg,
                  self.illite_kd_l_kg, self.bulk_kd_l_kg)
        if (not isinstance(self.occupancies, tuple) or not self.occupancies
                or any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or not math.isfinite(value) or value < 0 for value in values)):
            raise ValueError("result values must be finite and non-negative")
        if not math.isclose(
            sum(self.occupancies), self.total_sorbed_cs_mol_per_kg,
            rel_tol=1.0e-12, abs_tol=1.0e-15,
        ):
            raise ValueError("result mass balance is inconsistent")
        if self.bulk_kd_l_kg > self.illite_kd_l_kg:
            raise ValueError("bulk Kd cannot exceed illite Kd")
        _validate_provenance(self.provenance)
        object.__setattr__(self, "provenance", _freeze(dict(self.provenance)))

def load_illite_parameters(path: str|Path) -> IlliteParameters:
    try: raw=json.loads(Path(path).read_text())
    except (OSError,json.JSONDecodeError,TypeError) as exc: raise ValueError("malformed parameter record") from exc
    if not isinstance(raw,dict) or raw.get("schema_version")!="1.0.0": raise ValueError("unsupported parameter schema")
    try: provenance=raw["provenance"]; material=raw["material"]; cec_unit=raw["cec_unit"]; policy=raw["source_rounding_policy"]; raw_sites=raw["sites"]
    except (KeyError,TypeError): raise ValueError("incomplete parameter record") from None
    if material!="Illite du Puy" or cec_unit!="mol_charge/kg" or policy!="derive_residual_planar": raise ValueError("unsupported parameter contract")
    _validate_provenance(provenance)
    cec=raw.get("cec")
    if isinstance(cec,bool) or not isinstance(cec,(int,float)) or not math.isfinite(cec) or cec<=0: raise ValueError("CEC must be finite and positive")
    if not isinstance(raw_sites,list) or len(raw_sites)!=3 or [x.get("name") for x in raw_sites if isinstance(x,dict)]!=['FES','type-II','planar']: raise ValueError("invalid site names")
    caps=[]
    for item in raw_sites:
        log,cap=item.get("log10_kc_cs_k"),item.get("capacity_percent")
        if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in (log,cap)) or cap<=0: raise ValueError("invalid site parameters")
        try: kc=10.0**log
        except OverflowError: raise ValueError("site selectivity overflows") from None
        if not math.isfinite(kc): raise ValueError("site selectivity overflows")
        caps.append(cap)
    caps[2]=100.0-caps[0]-caps[1]
    if caps[2]<=0: raise ValueError("planar residual must be positive")
    sites=tuple(Site(i["name"],10.0**i["log10_kc_cs_k"],c/100.0,cec*c/100.0) for i,c in zip(raw_sites,caps))
    return IlliteParameters(material,cec,cec_unit,policy,sites,provenance)

def calculate_kd(params: IlliteParameters, state: CsKState) -> KdResult:
    if not isinstance(params,IlliteParameters) or not isinstance(state,CsKState): raise ValueError("params and state types are required")
    occ=[]
    for site in params.sites:
        ratio=site.kc*state.cesium_mol_l/state.potassium_mol_l
        frac=ratio/(1+ratio) if math.isfinite(ratio) else 1.0
        occ.append(site.capacity_mol_charge_per_kg*frac)
    occupancies=tuple(occ); total=sum(occupancies); kd=total/state.cesium_mol_l; bulk=state.illite_mass_fraction*kd
    if not all(math.isfinite(x) for x in (*occupancies,total,kd,bulk)): raise ValueError("calculation produced non-finite result")
    return KdResult(occupancies,total,kd,bulk,params.provenance)


# Primary-paper-verified Bradbury--Baeyens (2000) implementation.  The legacy
# Cs/K API above is intentionally retained because the checked-in surrogate is
# tied to that oracle and parameter hash.
@dataclass(frozen=True)
class PrimarySite:
    name: str
    capacity_fraction: float
    capacity_mol_charge_per_kg: float
    kc_cs_k: float
    kc_cs_na: float
    kc_k_na: float
    kc_nh4_k: float | None = None

    def __post_init__(self):
        numeric = (self.capacity_fraction, self.capacity_mol_charge_per_kg,
                   self.kc_cs_k, self.kc_cs_na, self.kc_k_na)
        if (self.name not in {"FES", "type-II", "planar"}
                or any(isinstance(x, bool) or not isinstance(x, (int, float))
                       or not math.isfinite(x) or x <= 0 for x in numeric)):
            raise ValueError("invalid primary GCS site")
        if self.kc_nh4_k is not None and (
            isinstance(self.kc_nh4_k, bool) or not isinstance(self.kc_nh4_k, (int, float))
            or not math.isfinite(self.kc_nh4_k) or self.kc_nh4_k <= 0
        ):
            raise ValueError("invalid NH4/K selectivity")


@dataclass(frozen=True)
class PrimaryGCSParameters:
    cec_mol_charge_per_kg: float
    sites: tuple[PrimarySite, ...]
    selectivity_uncertainty_log10: float
    applicability: Mapping[str, Any]
    noncompetitive_cations: tuple[str, ...]
    provenance: Mapping[str, Any]

    def __post_init__(self):
        if (isinstance(self.cec_mol_charge_per_kg, bool)
                or not isinstance(self.cec_mol_charge_per_kg, (int, float))
                or not math.isfinite(self.cec_mol_charge_per_kg)
                or self.cec_mol_charge_per_kg <= 0):
            raise ValueError("invalid primary CEC")
        if tuple(s.name for s in self.sites) != ("FES", "type-II", "planar"):
            raise ValueError("invalid primary site collection")
        if not math.isclose(sum(s.capacity_fraction for s in self.sites), 1.0,
                            rel_tol=0, abs_tol=1e-12):
            raise ValueError("primary site fractions must sum to one")
        if not math.isclose(sum(s.capacity_mol_charge_per_kg for s in self.sites),
                            self.cec_mol_charge_per_kg, rel_tol=1e-12, abs_tol=1e-15):
            raise ValueError("primary site capacities must sum to CEC")
        if self.noncompetitive_cations != ("Ca", "Mg", "Sr"):
            raise ValueError("unexpected noncompetitive-cation declaration")
        if (isinstance(self.selectivity_uncertainty_log10, bool)
                or not isinstance(self.selectivity_uncertainty_log10, (int, float))
                or not math.isfinite(self.selectivity_uncertainty_log10)
                or self.selectivity_uncertainty_log10 <= 0):
            raise ValueError("invalid selectivity uncertainty")
        expected_applicability = {"ph_min", "ph_max", "maximum_equilibrium_cs_mol_l",
                                  "prediction_factor_range"}
        if not isinstance(self.applicability, Mapping) or set(self.applicability) != expected_applicability:
            raise ValueError("invalid applicability contract")
        ph_min, ph_max = self.applicability["ph_min"], self.applicability["ph_max"]
        max_cs = self.applicability["maximum_equilibrium_cs_mol_l"]
        factors = self.applicability["prediction_factor_range"]
        if (any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
                for x in (ph_min, ph_max, max_cs)) or ph_min >= ph_max or max_cs <= 0
                or not isinstance(factors, (list, tuple)) or len(factors) != 2
                or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x)
                       or x <= 0 for x in factors) or factors[0] > factors[1]):
            raise ValueError("invalid applicability values")
        required = {"basis", "source", "doi", "tables", "primary_paper_verified",
                    "supplied_pdf_sha256"}
        if (not isinstance(self.provenance, Mapping) or not required <= set(self.provenance)
                or self.provenance["basis"] != "primary_paper"
                or self.provenance["primary_paper_verified"] is not True
                or self.provenance["doi"] != "10.1016/S0169-7722(99)00094-7"
                or tuple(self.provenance["tables"]) != ("Table 1", "Table 2")):
            raise ValueError("invalid primary-paper provenance")
        pdf_hash = self.provenance["supplied_pdf_sha256"]
        if (not isinstance(pdf_hash, str) or len(pdf_hash) != 64
                or any(ch not in "0123456789abcdef" for ch in pdf_hash)):
            raise ValueError("invalid supplied-PDF hash")
        object.__setattr__(self, "applicability", _freeze(dict(self.applicability)))
        object.__setattr__(self, "provenance", _freeze(dict(self.provenance)))


@dataclass(frozen=True)
class PrimaryGCSState:
    cesium_mol_l: float
    potassium_mol_l: float
    sodium_mol_l: float
    ammonium_mol_l: float
    illite_mass_fraction: float
    ph: float | None = None

    def __post_init__(self):
        values = (self.cesium_mol_l, self.potassium_mol_l, self.sodium_mol_l,
                  self.ammonium_mol_l, self.illite_mass_fraction)
        if any(isinstance(x, bool) or not isinstance(x, (int, float))
               or not math.isfinite(x) for x in values):
            raise ValueError("primary GCS state must be finite numeric")
        if self.cesium_mol_l <= 0 or min(self.potassium_mol_l, self.sodium_mol_l,
                                        self.ammonium_mol_l) < 0:
            raise ValueError("invalid primary GCS concentrations")
        if self.potassium_mol_l <= 0 and self.sodium_mol_l <= 0:
            raise ValueError("primary GCS requires positive K or Na background")
        if not 0 <= self.illite_mass_fraction <= 1:
            raise ValueError("illite mass fraction must be in [0, 1]")
        if self.ph is not None and (isinstance(self.ph, bool)
                or not isinstance(self.ph, (int, float)) or not math.isfinite(self.ph)):
            raise ValueError("pH must be finite numeric")


@dataclass(frozen=True)
class PrimaryKdResult:
    occupancies: tuple[float, ...]
    total_sorbed_cs_mol_per_kg: float
    illite_kd_l_kg: float
    bulk_kd_l_kg: float
    competitor_treatment: Mapping[str, str]
    applicability_warnings: tuple[str, ...]
    provenance: Mapping[str, Any]

    def __post_init__(self):
        values = (*self.occupancies, self.total_sorbed_cs_mol_per_kg,
                  self.illite_kd_l_kg, self.bulk_kd_l_kg)
        if any(isinstance(x, bool) or not isinstance(x, (int, float))
               or not math.isfinite(x) or x < 0 for x in values):
            raise ValueError("invalid primary GCS result")
        if not math.isclose(sum(self.occupancies), self.total_sorbed_cs_mol_per_kg,
                            rel_tol=1e-12, abs_tol=1e-15):
            raise ValueError("primary result mass balance is inconsistent")
        object.__setattr__(self, "competitor_treatment", _freeze(dict(self.competitor_treatment)))
        object.__setattr__(self, "provenance", _freeze(dict(self.provenance)))


def load_primary_gcs_parameters(path: str | Path) -> PrimaryGCSParameters:
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("malformed primary GCS parameter record") from exc
    required = {"schema_version", "material", "cec", "cec_unit",
                "source_rounding_policy", "applicability",
                "selectivity_uncertainty_log10", "sites",
                "noncompetitive_cations", "provenance"}
    if (not isinstance(raw, dict) or set(raw) != required
            or raw["schema_version"] != "bradbury-baeyens-gcs-2.0"
            or raw["material"] != "reference illite"
            or raw["cec_unit"] != "mol_charge/kg"
            or raw["source_rounding_policy"] != "derive_residual_planar"):
        raise ValueError("unsupported primary GCS parameter contract")
    cec = raw["cec"]
    if isinstance(cec, bool) or not isinstance(cec, (int, float)) or not math.isfinite(cec) or cec <= 0:
        raise ValueError("invalid primary CEC")
    records = raw["sites"]
    if not isinstance(records, list) or len(records) != 3:
        raise ValueError("invalid primary site records")
    fractions = []
    for index, item in enumerate(records):
        if not isinstance(item, dict):
            raise ValueError("invalid primary site record")
        expected = {"name", "capacity_percent", "log10_kc_cs_k", "log10_kc_cs_na",
                    "log10_kc_k_na", "log10_kc_nh4_k"}
        if set(item) != expected:
            raise ValueError("invalid primary site schema")
        numbers = (item["capacity_percent"], item["log10_kc_cs_k"],
                   item["log10_kc_cs_na"], item["log10_kc_k_na"])
        if any(isinstance(x, bool) or not isinstance(x, (int, float))
               or not math.isfinite(x) for x in numbers):
            raise ValueError("invalid primary site number")
        fractions.append(float(item["capacity_percent"]) / 100)
    fractions[2] = 1.0 - fractions[0] - fractions[1]
    sites = []
    for item, fraction in zip(records, fractions):
        nh4_log = item["log10_kc_nh4_k"]
        if nh4_log is not None and (isinstance(nh4_log, bool)
                or not isinstance(nh4_log, (int, float)) or not math.isfinite(nh4_log)):
            raise ValueError("invalid primary NH4 coefficient")
        try:
            values = (10.0 ** item["log10_kc_cs_k"],
                      10.0 ** item["log10_kc_cs_na"],
                      10.0 ** item["log10_kc_k_na"],
                      None if nh4_log is None else 10.0 ** nh4_log)
        except OverflowError:
            raise ValueError("primary selectivity overflows") from None
        if any(x is not None and not math.isfinite(x) for x in values):
            raise ValueError("primary selectivity overflows")
        sites.append(PrimarySite(item["name"], fraction, cec * fraction, *values))
    return PrimaryGCSParameters(
        cec, tuple(sites), raw["selectivity_uncertainty_log10"],
        raw["applicability"], tuple(raw["noncompetitive_cations"]), raw["provenance"])


def calculate_primary_kd(params: PrimaryGCSParameters,
                         state: PrimaryGCSState) -> PrimaryKdResult:
    if not isinstance(params, PrimaryGCSParameters) or not isinstance(state, PrimaryGCSState):
        raise ValueError("primary params and state types are required")
    occupancies = []
    for site in params.sites:
        # Equivalent-fraction weights relative to K follow the Gaines--Thomas
        # mass-action definitions in equations 1--8 of the primary paper.
        weights_k = state.potassium_mol_l
        weights_na = state.sodium_mol_l / site.kc_k_na
        weights_cs = site.kc_cs_k * state.cesium_mol_l
        weights_nh4 = (site.kc_nh4_k * state.ammonium_mol_l
                       if site.kc_nh4_k is not None else 0.0)
        denominator = weights_k + weights_na + weights_cs + weights_nh4
        if denominator <= 0 or not math.isfinite(denominator):
            raise ValueError("invalid primary exchange denominator")
        occupancies.append(site.capacity_mol_charge_per_kg * weights_cs / denominator)
    occupancy_tuple = tuple(occupancies)
    total = sum(occupancy_tuple)
    illite_kd = total / state.cesium_mol_l
    bulk_kd = state.illite_mass_fraction * illite_kd
    warnings = []
    if state.cesium_mol_l > params.applicability["maximum_equilibrium_cs_mol_l"]:
        warnings.append("cesium_above_primary_paper_domain")
    if state.ph is not None and not (params.applicability["ph_min"] <= state.ph <= params.applicability["ph_max"]):
        warnings.append("ph_outside_primary_paper_range")
    treatment = {
        "K": "competitive on FES, type-II and planar sites",
        "Na": "competitive on FES, type-II and planar sites",
        "NH4": "FES only; no unsupported type-II/planar coefficient inferred",
        "Ca": "effectively noncompetitive in primary-paper Cs model",
        "Mg": "effectively noncompetitive in primary-paper Cs model",
        "Sr": "effectively noncompetitive in primary-paper Cs model",
    }
    return PrimaryKdResult(occupancy_tuple, total, illite_kd, bulk_kd,
                           treatment, tuple(warnings), params.provenance)
