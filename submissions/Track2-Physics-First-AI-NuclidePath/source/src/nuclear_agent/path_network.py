"""Immutable acyclic directed 1-D segment networks."""
from __future__ import annotations
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


def _map(value: Mapping[str, float] | None) -> Mapping[str, float]:
    return MappingProxyType(dict(value or {}))

@dataclass(frozen=True)
class Segment:
    segment_id: str
    length_m: float
    porosity: float
    bulk_density_kg_m3: float
    groundwater_velocity_m_s: float
    dispersion_m2_s: float
    chemistry: Mapping[str, float] = None
    mineralogy: Mapping[str, float] = None
    sorption: Mapping[str, float] = None
    def __post_init__(self):
        import math
        if not self.segment_id.strip(): raise ValueError("segment_id must not be empty")
        vals = (self.length_m,self.porosity,self.bulk_density_kg_m3,self.groundwater_velocity_m_s,self.dispersion_m2_s)
        if any(isinstance(x,bool) or not math.isfinite(float(x)) for x in vals): raise ValueError("segment physical parameters must be finite")
        if self.length_m <= 0 or self.bulk_density_kg_m3 <= 0 or self.groundwater_velocity_m_s <= 0 or self.dispersion_m2_s <= 0: raise ValueError("segment positive parameters must be > 0")
        if not 0 < self.porosity <= 1: raise ValueError("segment porosity must be in (0, 1]")
        object.__setattr__(self, "chemistry", _map(self.chemistry)); object.__setattr__(self, "mineralogy", _map(self.mineralogy)); object.__setattr__(self, "sorption", _map(self.sorption))

@dataclass(frozen=True)
class HandoffAssumptions:
    continuity: str = "dissolved concentration continuity"
    flux: str = "advective-dispersive dissolved flux continuity"
    sorbed_storage: str = "segment-local equilibrium sorption; no sorbed carryover"
    def __post_init__(self):
        if not all(isinstance(x,str) and x.strip() for x in (self.continuity,self.flux,self.sorbed_storage)): raise ValueError("handoff assumptions must be non-empty text")

@dataclass(frozen=True)
class PathNetwork:
    segments: tuple[Segment, ...]
    edges: tuple[tuple[str,str], ...] = ()
    receptors: Mapping[str, str] = None
    handoff: HandoffAssumptions = HandoffAssumptions()
    def __post_init__(self):
        object.__setattr__(self, "segments", tuple(self.segments))
        object.__setattr__(self, "edges", tuple(tuple(e) if isinstance(e, (list, tuple)) else e for e in self.edges))
        if not self.segments: raise ValueError("segment network must not be empty")
        ids = [s.segment_id for s in self.segments]
        if len(set(ids)) != len(ids): raise ValueError("segment IDs must be unique")
        known = set(ids)
        if len(set(self.edges)) != len(self.edges): raise ValueError("edges must be unique")
        if any(a not in known or b not in known or a == b for a,b in self.edges): raise ValueError("edges must reference distinct known segments")
        incoming_counts = {x:0 for x in ids}
        for _,b in self.edges: incoming_counts[b] += 1
        if any(count > 1 for count in incoming_counts.values()): raise ValueError("multiple incoming segments make receptor path ambiguous")
        adjacency = {x: [] for x in ids}
        for a,b in self.edges: adjacency[a].append(b)
        state = {}
        def visit(n):
            if state.get(n) == 1: raise ValueError("segment network must be acyclic")
            if state.get(n) == 2: return
            state[n]=1
            for child in adjacency[n]: visit(child)
            state[n]=2
        for n in ids: visit(n)
        rec = dict(self.receptors or {})
        if any(s not in known for s in rec.values()): raise ValueError("receptor must connect to a known segment")
        object.__setattr__(self, "receptors", MappingProxyType(rec))
    def path_to_receptor(self, receptor_id: str) -> tuple[Segment, ...]:
        if receptor_id not in self.receptors: raise KeyError(receptor_id)
        by_id = {s.segment_id:s for s in self.segments}; target=self.receptors[receptor_id]
        incoming = {b:a for a,b in self.edges}; path=[]; cur=target
        while cur in by_id: path.append(by_id[cur]); cur=incoming.get(cur)
        return tuple(reversed(path))
