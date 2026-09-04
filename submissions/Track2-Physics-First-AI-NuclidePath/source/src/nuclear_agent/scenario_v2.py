"""Strict, immutable multispecies scenario contract v2."""
from __future__ import annotations
import json, math
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
from .transport import TransportParameters, simulate_transport
from .gcs import PrimaryGCSState, calculate_primary_kd, load_primary_gcs_parameters

SCHEMA = "nuclidepath-multispecies-2.0"
SUPPORTED = {"Cs-137", "Sr-90"}
IONS = ("K", "Na", "Ca", "Mg", "NH4")
CLASSIFICATIONS = {"measured", "evaluated", "secondary", "official", "derived"}
HERE = Path(__file__).parent

class ScenarioInputV2Error(ValueError):
    pass

def _freeze(v):
    if isinstance(v, Mapping): return MappingProxyType({k: _freeze(x) for k, x in v.items()})
    if isinstance(v, list): return tuple(_freeze(x) for x in v)
    return v

def _number(name, value, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ScenarioInputV2Error(f"{name} must be finite numeric")
    if positive and value <= 0: raise ScenarioInputV2Error(f"{name} must be > 0")
    if nonnegative and value < 0: raise ScenarioInputV2Error(f"{name} must be >= 0")
    return float(value)

def _source(name, value):
    if not isinstance(value, str) or not value.strip(): raise ScenarioInputV2Error(f"{name} source required")

def _classification(name, value):
    if value not in CLASSIFICATIONS: raise ScenarioInputV2Error(f"{name} classification unsupported")

def _parse_radionuclides(raw):
    if not isinstance(raw, (list, tuple)) or not raw:
        raise ScenarioInputV2Error("radionuclides must be a non-empty list")
    seen, parsed = set(), []
    allowed = {"name", "initial_concentration_bq_m3", "half_life_years", "half_life_source", "half_life_classification", "sorption"}
    for r in raw:
        if not isinstance(r, Mapping): raise ScenarioInputV2Error("radionuclide must be an object")
        if set(r) - allowed: raise ScenarioInputV2Error("unknown radionuclide field")
        name = r.get("name")
        if name not in SUPPORTED: raise ScenarioInputV2Error("unknown radionuclide")
        if name in seen: raise ScenarioInputV2Error("duplicate radionuclide")
        seen.add(name)
        required = {"name", "initial_concentration_bq_m3", "half_life_years", "half_life_source", "half_life_classification", "sorption"}
        for key in required - set(r): raise ScenarioInputV2Error(f"missing radionuclide field: {key}")
        _number("initial_concentration_bq_m3", r["initial_concentration_bq_m3"], positive=True)
        _number("half_life_years", r["half_life_years"], positive=True)
        _source("half_life", r["half_life_source"]); _classification("half_life", r["half_life_classification"])
        s = r["sorption"]
        if not isinstance(s, Mapping): raise ScenarioInputV2Error("sorption must be object")
        if set(s) - {"model", "source", "classification", "kd_m3_kg", "stable_cs_mol_l", "illite_mass_fraction"}:
            raise ScenarioInputV2Error("unknown sorption field")
        if s.get("model") not in {"linear_kd", "gcs_cs_k"}: raise ScenarioInputV2Error("invalid sorption model")
        _source("sorption", s.get("source")); _classification("sorption", s.get("classification"))
        if s["model"] == "linear_kd":
            if set(s) != {"model", "source", "classification", "kd_m3_kg"}: raise ScenarioInputV2Error("linear Kd fields required")
            _number("kd_m3_kg", s["kd_m3_kg"], nonnegative=True)
        else:
            if name != "Cs-137": raise ScenarioInputV2Error("GCS is supported only for Cs-137")
            if set(s) != {"model", "source", "classification", "stable_cs_mol_l", "illite_mass_fraction"}: raise ScenarioInputV2Error("GCS fields required")
            _number("stable_cs_mol_l", s["stable_cs_mol_l"], positive=True)
            if _number("illite_mass_fraction", s["illite_mass_fraction"], nonnegative=True) > 1: raise ScenarioInputV2Error("illite_mass_fraction must be <= 1")
        normalized = dict(r)
        normalized["initial_concentration_bq_m3"] = float(r["initial_concentration_bq_m3"])
        normalized["half_life_years"] = float(r["half_life_years"])
        normalized["sorption"] = dict(s)
        parsed.append(_freeze(normalized))
    return tuple(parsed)

def _parse_chemistry(raw):
    if not isinstance(raw, Mapping) or set(raw) != set(IONS):
        raise ScenarioInputV2Error("chemistry must contain exactly K, Na, Ca, Mg, NH4")
    parsed = {}
    for ion in IONS:
        item = raw[ion]
        if not isinstance(item, Mapping) or set(item) not in ({"value_mg_l", "source", "classification"}, {"value_mg_l", "source", "classification", "use"}):
            raise ScenarioInputV2Error("invalid chemistry fields")
        _number(ion, item["value_mg_l"], nonnegative=True); _source(ion, item["source"]); _classification(ion, item["classification"])
        expected_use = {
            "K": "used by primary GCS",
            "Na": "used by primary GCS",
            "NH4": "used by primary GCS on FES only",
            "Ca": "effectively noncompetitive in primary-paper Cs GCS",
            "Mg": "effectively noncompetitive in primary-paper Cs GCS",
        }[ion]
        if "use" in item and item["use"] != expected_use: raise ScenarioInputV2Error("invalid chemistry use")
        parsed[ion] = {**item, "value_mg_l": float(item["value_mg_l"]), "use": expected_use}
    return _freeze(parsed)

@dataclass(frozen=True)
class ScenarioInputV2:
    scenario_id: str
    radionuclides: tuple[Mapping[str, Any], ...]
    chemistry: Mapping[str, Mapping[str, Any]]
    distance_m: float
    evaluation_times_s: tuple[float, ...]
    bulk_density_kg_m3: float = 1700.0
    porosity: float = .35
    groundwater_velocity_m_s: float = 1e-5
    dispersion_m2_s: float = 1e-5

    def __post_init__(self):
        # Direct construction follows the same domain rules as from_dict and
        # owns its data (callers cannot mutate the scenario behind our back).
        if not isinstance(self.scenario_id, str) or not self.scenario_id.strip():
            raise ScenarioInputV2Error("scenario_id required")
        radionuclides = _parse_radionuclides(self.radionuclides)
        chemistry = _parse_chemistry(self.chemistry)
        _number("distance_m", self.distance_m, nonnegative=True)
        if not isinstance(self.evaluation_times_s, (list, tuple)) or not self.evaluation_times_s:
            raise ScenarioInputV2Error("evaluation_times_s must be list")
        times = tuple(_number("time", t, nonnegative=True) for t in self.evaluation_times_s)
        if list(times) != sorted(times) or len(set(times)) != len(times):
            raise ScenarioInputV2Error("evaluation_times_s must be ordered and unique")
        _number("bulk_density_kg_m3", self.bulk_density_kg_m3, positive=True)
        porosity = _number("porosity", self.porosity, positive=True)
        if porosity > 1: raise ScenarioInputV2Error("porosity must be <= 1")
        _number("groundwater_velocity_m_s", self.groundwater_velocity_m_s, positive=True)
        _number("dispersion_m2_s", self.dispersion_m2_s, positive=True)
        object.__setattr__(self, "radionuclides", radionuclides)
        object.__setattr__(self, "chemistry", chemistry)
        object.__setattr__(self, "evaluation_times_s", times)

    @classmethod
    def from_dict(cls, p):
        if not isinstance(p, Mapping): raise ScenarioInputV2Error("payload must be an object")
        allowed={"schema_version","scenario_id","radionuclides","chemistry","distance_m","evaluation_times_s","bulk_density_kg_m3","porosity","groundwater_velocity_m_s","dispersion_m2_s"}
        if set(p)-allowed: raise ScenarioInputV2Error(f"unknown field: {sorted(set(p)-allowed)[0]!r}")
        if p.get("schema_version") != SCHEMA: raise ScenarioInputV2Error("invalid schema_version")
        for key in ("scenario_id","radionuclides","chemistry","distance_m","evaluation_times_s"):
            if key not in p: raise ScenarioInputV2Error(f"missing field: {key}")
        if not isinstance(p["scenario_id"], str) or not p["scenario_id"].strip(): raise ScenarioInputV2Error("scenario_id required")
        parsed = _parse_radionuclides(p["radionuclides"])
        pc = _parse_chemistry(p["chemistry"])
        times=p["evaluation_times_s"]
        if not isinstance(times,(list,tuple)) or not times: raise ScenarioInputV2Error("evaluation_times_s must be a non-empty list")
        vals={}
        vals["bulk_density_kg_m3"]=_number("bulk_density_kg_m3",p.get("bulk_density_kg_m3",1700.),positive=True)
        vals["porosity"]=_number("porosity",p.get("porosity",.35),positive=True)
        if vals["porosity"] > 1: raise ScenarioInputV2Error("porosity must be <= 1")
        vals["groundwater_velocity_m_s"]=_number("groundwater_velocity_m_s",p.get("groundwater_velocity_m_s",1e-5),positive=True)
        vals["dispersion_m2_s"]=_number("dispersion_m2_s",p.get("dispersion_m2_s",1e-5),positive=True)
        parsed_times=tuple(_number("time",t,nonnegative=True) for t in times)
        if list(parsed_times) != sorted(parsed_times) or len(set(parsed_times)) != len(parsed_times): raise ScenarioInputV2Error("evaluation_times_s must be ordered and unique")
        vals.update(scenario_id=p["scenario_id"],radionuclides=tuple(parsed),chemistry=_freeze(pc),distance_m=_number("distance_m",p["distance_m"],nonnegative=True),evaluation_times_s=parsed_times)
        return cls(**vals)

def load_molar_masses(path=None):
    path=path or HERE/"data/parameters/molar_masses_v1.json"
    try: raw=json.loads(Path(path).read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as e:
        raise ValueError("malformed molar mass record") from e
    if not isinstance(raw, Mapping) or set(raw)!={"schema_version","unit","source","masses","nh4_calculation","source_url","source_version","nh4_components"} or raw["schema_version"]!="1.0.0" or raw["unit"]!="g/mol" or not isinstance(raw["masses"], Mapping) or set(raw["masses"])!=set(IONS): raise ValueError("invalid molar mass schema")
    if not isinstance(raw["source"],str) or not raw["source"].strip() or not isinstance(raw["nh4_calculation"],str) or "N" not in raw["nh4_calculation"]: raise ValueError("invalid molar mass provenance")
    masses={k:_number(k,v,positive=True) for k,v in raw["masses"].items()}
    if not isinstance(raw["source_url"], str) or not raw["source_url"].startswith("https://") or not isinstance(raw["source_version"], str) or not raw["source_version"].strip() or not isinstance(raw["nh4_components"], Mapping): raise ValueError("invalid molar mass provenance")
    components = raw["nh4_components"]
    if set(components) != {"N", "H", "count_H"} or any(isinstance(components[k], bool) or not isinstance(components[k], (int,float)) for k in ("N","H","count_H")) or not math.isclose(components["N"] + components["count_H"] * components["H"], masses["NH4"], rel_tol=0.0, abs_tol=1e-12): raise ValueError("NH4 components do not reproduce mass")
    return _freeze(masses), _freeze({"schema_version":raw["schema_version"],"source":raw["source"],"source_url":raw["source_url"],"source_version":raw["source_version"],"unit":raw["unit"],"nh4_calculation":raw["nh4_calculation"],"nh4_components":raw["nh4_components"]})

def run_transport_contract_v2(payload):
    x=ScenarioInputV2.from_dict(payload); masses,mp=load_molar_masses(); results=[]
    mg={ion:x.chemistry[ion]["value_mg_l"] for ion in IONS}; mol={ion:mg[ion]/1000/masses[ion] for ion in IONS}
    for r in x.radionuclides:
        s=r["sorption"]
        if s["model"]=="linear_kd": kd=s["kd_m3_kg"]; sp={"model":s["model"],"source":s["source"],"classification":s["classification"]}
        else:
            if mol["K"]<=0 and mol["Na"]<=0:
                raise ScenarioInputV2Error("primary GCS requires positive K or Na")
            calc=calculate_primary_kd(
                load_primary_gcs_parameters(HERE/"data/parameters/bradbury_baeyens_gcs_v2.json"),
                PrimaryGCSState(s["stable_cs_mol_l"], mol["K"], mol["Na"], mol["NH4"],
                                s["illite_mass_fraction"]),
            )
            kd=calc.bulk_kd_l_kg/1000
            sp={"model":s["model"],"source":s["source"],"classification":s["classification"],
                "gcs_provenance":calc.provenance,
                "competitor_treatment":calc.competitor_treatment,
                "applicability_warnings":calc.applicability_warnings,
                "bulk_kd_l_kg":calc.bulk_kd_l_kg}
        tp=TransportParameters(r["initial_concentration_bq_m3"],kd,x.bulk_density_kg_m3,x.porosity,x.groundwater_velocity_m_s,x.dispersion_m2_s,0,0,r["half_life_years"])
        results.append({"radionuclide":r["name"],"half_life_years":r["half_life_years"],"half_life_provenance":{"source":r["half_life_source"],"classification":r["half_life_classification"]},"sorption":sp,"transport_parameters":{"potassium_mg_l":0,"competition_coefficient_l_mg":0},"points":tuple({"time_s":t,**simulate_transport(tp,x.distance_m,t)} for t in x.evaluation_times_s)})
    return _freeze({"schema_version":SCHEMA,"scenario_id":x.scenario_id,"chemistry":{"mg_l":mg,"mol_l":mol,"ion_provenance":{ion:{"source":x.chemistry[ion]["source"],"classification":x.chemistry[ion]["classification"],"use":x.chemistry[ion]["use"]} for ion in IONS},"molar_mass_provenance":mp},"species_results":results})
