"""Strict, immutable observation ingestion for validated scientific inputs."""
from __future__ import annotations
import csv, json, math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

_UNITS = {"Bq/m3": 1.0, "kBq/m3": 1_000.0, "Bq/L": 1_000.0, "mBq/m3": 1e-3}
_FIELDS = {"radionuclide", "receptor_id", "timestamp", "value", "unit", "uncertainty", "detection_limit_flag", "detection_limit_value", "provenance"}

def _number(x, name):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
        raise ValueError(f"{name} must be a finite non-boolean number")
    return float(x)

def _timestamp(x):
    if not isinstance(x, str) or not x.strip(): raise ValueError("timestamp must be a non-empty string")
    try:
        value=datetime.fromisoformat(x.replace("Z", "+00:00"))
        if value.tzinfo is None: raise ValueError("timezone required")
        return value
    except ValueError as e: raise ValueError("timestamp must be ISO-8601") from e

@dataclass(frozen=True, slots=True)
class Observation:
    radionuclide: str; receptor_id: str; timestamp: datetime; value: float; unit: str
    uncertainty: float; detection_limit_flag: bool; detection_limit_value: float | None; provenance: str

    def __post_init__(self):
        if not all(isinstance(x,str) and x.strip() for x in (self.radionuclide,self.receptor_id,self.unit,self.provenance)): raise ValueError("observation text fields required")
        if not isinstance(self.timestamp,datetime) or self.timestamp.tzinfo is None: raise ValueError("timestamp must include timezone")
        for name,value in (("value",self.value),("uncertainty",self.uncertainty)):
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value < 0: raise ValueError(f"{name} must be finite and nonnegative")
        if self.uncertainty <= 0: raise ValueError("uncertainty must be positive")
        if not isinstance(self.detection_limit_flag,bool): raise ValueError("detection_limit_flag must be boolean")
        if self.detection_limit_flag != (self.detection_limit_value is not None): raise ValueError("inconsistent detection-limit metadata")
        if self.detection_limit_value is not None and (not math.isfinite(self.detection_limit_value) or self.detection_limit_value < 0): raise ValueError("detection limit must be nonnegative finite")
        if self.unit != "Bq/m3": raise ValueError("Observation must be normalized to Bq/m3")

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Observation":
        if not isinstance(raw, Mapping): raise ValueError("observation must be an object")
        unknown = set(raw) - _FIELDS
        missing = _FIELDS - set(raw)
        if unknown: raise ValueError(f"unknown field: {sorted(unknown)[0]}")
        if missing: raise ValueError(f"missing field: {sorted(missing)[0]}")
        unit = raw["unit"]
        if not isinstance(unit, str) or unit not in _UNITS: raise ValueError("unknown or ambiguous unit")
        factor = _UNITS[unit]; value = _number(raw["value"], "value") * factor
        unc = _number(raw["uncertainty"], "uncertainty") * factor
        if unc <= 0: raise ValueError("uncertainty must be positive")
        flag = raw["detection_limit_flag"]
        if not isinstance(flag, bool): raise ValueError("detection_limit_flag must be boolean")
        dl = raw["detection_limit_value"]
        if flag and dl is None: raise ValueError("detection_limit_value required for censored observation")
        if not flag and dl is not None: raise ValueError("detection_limit_value only allowed when censored")
        if dl is not None: dl = _number(dl, "detection_limit_value") * factor
        for key in ("radionuclide", "receptor_id", "provenance"):
            if not isinstance(raw[key], str) or not raw[key].strip(): raise ValueError(f"{key} must be a non-empty string")
        return cls(raw["radionuclide"], raw["receptor_id"], _timestamp(raw["timestamp"]), value, "Bq/m3", unc, flag, dl, raw["provenance"])

def _load(rows):
    obs = tuple(Observation.from_dict(r) for r in rows)
    if not obs: raise ValueError("observation collection must not be empty")
    return obs

def load_json_observations(path: str | Path) -> tuple[Observation, ...]:
    try: data=json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as e: raise ValueError(f"invalid observation JSON: {e}") from e
    if not isinstance(data, list): raise ValueError("JSON observations must be a list")
    return _load(data)

def load_csv_observations(path: str | Path) -> tuple[Observation, ...]:
    try:
        with Path(path).open(newline="") as f: reader=csv.DictReader(f); rows=list(reader)
    except OSError as e: raise ValueError(f"invalid observation CSV: {e}") from e
    if reader.fieldnames is None or set(reader.fieldnames) != _FIELDS: raise ValueError("CSV fields must exactly match observation schema")
    for r in rows:
        for k in ("value", "uncertainty", "detection_limit_value"): 
            if r[k] == "": r[k] = None
        if r["detection_limit_flag"] in ("true", "True", "1"): r["detection_limit_flag"] = True
        elif r["detection_limit_flag"] in ("false", "False", "0"): r["detection_limit_flag"] = False
        else: raise ValueError("detection_limit_flag must be boolean")
        for k in ("value", "uncertainty", "detection_limit_value"):
            if r[k] is not None:
                try: r[k]=float(r[k])
                except ValueError as e: raise ValueError(f"{k} must be numeric") from e
    return _load(rows)
