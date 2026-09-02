"""Block-scale evacuation engine.

Design rationale
----------------
The existing ``simulator.multiscale`` meso layer moves population between
~1 km grid cells using a distance-weighted diffusion rule.  That rule has no
capacity anywhere in it: the same fraction of a cell leaves per step whether
the cell is a single tower block with two gates or an open park.  Evacuation
times produced that way are a function of the diffusion constant, not of the
city.

This module replaces that with a **capacity-constrained queueing network on
road-enclosed blocks**, which is the smallest unit where the physics are real:

* People inside a block must reach the block boundary.  Intra-block walk time
  scales with the block's area-equivalent radius.
* They then pass through the block's egress onto the street.  Throughput there
  is bounded by ``egress width x specific flow`` (Fruin / Weidmann pedestrian
  fundamental diagram, ~1.2-1.4 persons per metre per second at capacity).
* They walk block-to-block along a routing tree toward a shelter.  Each hop is
  bounded by the shared boundary's width, so congestion emerges from geometry
  rather than from a tuned constant.
* Shelters admit until capacity, then overflow reroutes to the next reachable
  shelter.

Scaling
-------
Population is carried as **continuous stocks in numpy arrays of length
n_blocks**, not as one Python object per person. A city-scale population
scenario is represented by a compact set of numeric arrays, and a two-hour
simulation at 30-second intervals requires 240 vectorised steps.
Individual agents are materialised only for the rendered sample and for the
LLM coordinator cohort, which is where per-agent detail is actually observed.

Nothing here is claimed as calibration against an observed mass evacuation.
Departure curves, participation rates, and specific flow are documented
assumptions with literature-sourced defaults; they are
reported in the output payload so a reader can see what was assumed.
"""

from __future__ import annotations

import heapq
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Sequence

import numpy as np


# ────────────────────────────────────────────────────────────────────────────
# Assumptions (all overridable, all reported in the output payload)
# ────────────────────────────────────────────────────────────────────────────

#: Effective usable width in metres contributed by one boundary edge of a
#: given road class.  Wider streets carry more pedestrians away from a block.
DEFAULT_EGRESS_WIDTH_M: dict[str, float] = {
    "motorway": 0.0,        # not walkable
    "motorway_link": 0.0,
    "trunk": 3.0,
    "trunk_link": 2.0,
    "primary": 6.0,
    "secondary": 5.0,
    "tertiary": 4.0,
    "unclassified": 3.0,
    "residential": 3.0,
    "living_street": 3.0,
    "service": 2.0,
    "pedestrian": 8.0,
    "footway": 2.0,
    "path": 1.5,
    "unknown": 2.0,
    "default": 2.5,
}

#: Assumed capacity (persons) by candidate-shelter type, used only when a
#: source file gives neither a capacity nor an area to compute one from (see
#: ``load_shelters_geojson``). These are illustrative defaults, not surveyed
#: figures -- they exist so a city with nothing but an OSM POI dump (school,
#: hospital, park, ...) doesn't get every candidate flattened to one identical
#: number regardless of what kind of place it actually is. A hospital gets a
#: deliberately small figure: it is a casualty-treatment facility, not a
#: general-evacuee shelter, even though open data commonly tags it alongside
#: real shelters.
DEFAULT_CAPACITY_BY_SHELTER_TYPE: dict[str, float] = {
    "park": 5_000.0,
    "shelter": 2_000.0,
    "assembly_point": 1_000.0,
    "school": 1_500.0,
    "hospital": 500.0,
    "other": 1_000.0,
    "unknown": 1_000.0,
}

#: Pedestrian specific flow at capacity, persons per metre of width per second.
#: Weidmann (1993) and Fruin LOS E sit in the 1.2-1.4 range for level walkways.
SPECIFIC_FLOW_PPS_PER_M = 1.3

#: Free-flow walking speed, m/s.  Weidmann's mean for mixed urban populations.
FREE_FLOW_SPEED_MPS = 1.34

#: Jam density, persons/m^2, above which movement effectively stops.
JAM_DENSITY_PPSM = 5.4


@dataclass
class BlockScaleConfig:
    """Configuration for a block-scale evacuation run."""

    city: str = "public_demo_city"
    seed: int = 42

    # --- time ---
    step_seconds: int = 30
    duration_minutes: int = 120

    # --- population ---
    #: Scale the block population layer to this total.  ``None`` keeps the
    #: population exactly as supplied by the disaggregation step.
    target_population: int | None = None

    # --- departure behaviour ---
    #: Median departure delay after the shaking stops, in seconds.  Lognormal.
    departure_median_s: float = 180.0
    departure_sigma: float = 0.8
    #: Fraction of residents who evacuate at all, at and above the MMI
    #: threshold.  Below the threshold, ``participation_low``.
    participation_high: float = 0.65
    participation_low: float = 0.10
    mmi_evacuation_threshold: float = 6.0

    # --- pedestrian physics ---
    specific_flow: float = SPECIFIC_FLOW_PPS_PER_M
    free_flow_speed_mps: float = FREE_FLOW_SPEED_MPS
    jam_density: float = JAM_DENSITY_PPSM
    #: Multiplier on the straight-line intra-block radius to account for the
    #: fact that people walk around buildings, not through them.
    intra_block_detour: float = 1.4

    # --- hazard ---
    epicenter_lon: float = 0.0
    epicenter_lat: float = 0.0
    magnitude: float = 7.0

    # --- shelters ---
    #: Persons per square metre of usable shelter area, when capacity has to
    #: be inferred. Emergency-shelter guidance commonly uses 1.5-2.0
    #: m^2 per person for short-term open-space refuge.
    shelter_persons_per_m2: float = 0.5
    #: Cap on how far a block may be routed to a shelter, in metres.  Blocks
    #: beyond this are reported as unserved rather than given an implausible
    #: route.
    max_shelter_distance_m: float = 6000.0
    #: Reopen hysteresis margin, as a fraction of a shelter's nominal
    #: capacity. See ``BlockEvacuationSimulator.reopen_hysteresis``.
    shelter_reopen_hysteresis: float = 0.05
    #: How far a shelter may sit from its nearest block and still be bound to
    #: it, in metres. A shelter file usually covers a whole city while a run
    #: may simulate one district; without this, nearest-centroid snapping
    #: attaches every distant shelter to a boundary block and its capacity is
    #: counted as locally available. 2 km is generous for a genuine
    #: edge-of-window shelter while excluding one in another district.
    shelter_snap_max_m: float = 2000.0
    #: Occupancy fraction at which a shelter is retired from the routing tree,
    #: triggering a rebuild. 1.0 reproduces the original behaviour exactly
    #: (retire only on an actual rejection). Below 1.0 the rebuild happens
    #: while the shelter still has a little room, which is what lets a block
    #: be re-pointed to a *nearer* shelter that still has space instead of
    #: being sent far away only after its destination is completely full.
    #: Must stay above ``shelter_reopen_hysteresis`` or a shelter would be
    #: retired and immediately reopened.
    shelter_retire_at: float = 1.0

    # --- sampling for visualisation / LLM ---
    rendered_sample: int = 3000
    llm_coordinator_count: int = 0
    #: How often (in steps) to snapshot per-block cumulative departed/sheltered
    #: stocks for individual-agent timing reconstruction. Every step by default
    #: (cheap: a few numpy arrays, kept in memory, never serialised whole) so
    #: that near-shelter blocks with sub-step transit times don't alias.
    snapshot_every_steps: int = 1


# ────────────────────────────────────────────────────────────────────────────
# Inputs
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class ShelterSite:
    """A shelter with a location and a capacity."""

    shelter_id: str
    name: str
    lon: float
    lat: float
    capacity: float
    block_id: str | None = None
    occupants: float = 0.0
    provenance: str = ""

    @property
    def remaining(self) -> float:
        return max(0.0, self.capacity - self.occupants)


@dataclass
class BlockLayer:
    """Immutable geometric and demographic inputs, as parallel arrays."""

    block_ids: list[str]
    lon: np.ndarray
    lat: np.ndarray
    area_m2: np.ndarray
    perimeter_m: np.ndarray
    population: np.ndarray
    egress_width_m: np.ndarray
    district: list[str | None]
    #: Undirected block adjacency: shared boundary node -> block indices.
    neighbours: list[list[int]]
    #: Shared boundary width per (block, neighbour) pair, metres.
    shared_width_m: list[list[float]]
    #: Per-block walking-resistance multiplier (>= 1.0; np.inf = impassable),
    #: from terrain slope and land cover -- see geo/terrain_resistance.py.
    #: Defaults to all-ones (no friction surface), which reproduces
    #: pre-friction-surface routing and timing exactly: a block-scale
    #: analogue of the minimum-cumulative-resistance (MCR) model used for
    #: landscape ecological security patterns (Knaapen et al. 1992; Yu 1999),
    #: applied here to pedestrian evacuation instead of ecological
    #: connectivity -- same mechanism (source -> resistance surface ->
    #: least-cumulative-cost path -> sink), different sources/sinks/surface.
    resistance: np.ndarray = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.resistance is None:
            self.resistance = np.ones(len(self.block_ids), dtype=np.float64)

    def __len__(self) -> int:
        return len(self.block_ids)


def build_block_layer(
    blocks: Sequence[Any],
    *,
    populations: dict[str, float] | None = None,
    egress_width_by_class: dict[str, float] | None = None,
    resistance_by_block: dict[str, float] | None = None,
) -> BlockLayer:
    """Assemble a :class:`BlockLayer` from :class:`geo.urban_blocks.Block`.

    Adjacency is derived from shared planar-graph node ids: two blocks are
    neighbours when their rings share at least two consecutive nodes, i.e.
    they are separated by a common street segment rather than merely touching
    at a junction.
    """
    widths = dict(DEFAULT_EGRESS_WIDTH_M)
    if egress_width_by_class:
        widths.update(egress_width_by_class)

    n = len(blocks)
    ids = [b.block_id for b in blocks]
    lon = np.array([b.lon for b in blocks], dtype=np.float64)
    lat = np.array([b.lat for b in blocks], dtype=np.float64)
    area = np.array([b.area_m2 for b in blocks], dtype=np.float64)
    perim = np.array([b.perimeter_m for b in blocks], dtype=np.float64)
    egress = np.array([b.egress_width_m(widths) for b in blocks], dtype=np.float64)

    pops = populations or {}
    population = np.array([float(pops.get(b.block_id, b.population)) for b in blocks],
                          dtype=np.float64)

    # Edge -> blocks incident to it.
    edge_owner: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, b in enumerate(blocks):
        ring = b.node_ids
        for a, c in zip(ring, list(ring[1:]) + [ring[0]]):
            edge_owner[(a, c) if a < c else (c, a)].append(i)

    nbr_width: list[dict[int, float]] = [dict() for _ in range(n)]
    for (a, c), owners in edge_owner.items():
        if len(owners) != 2:
            continue
        i, j = owners
        if i == j:
            continue
        # Shared width proxy: the road class of the separating segment.
        cls_i = blocks[i].boundary_classes
        width = max(
            widths.get(k, widths["default"]) for k in (cls_i or {"unknown": 1})
        ) if cls_i else widths["default"]
        nbr_width[i][j] = nbr_width[i].get(j, 0.0) + width
        nbr_width[j][i] = nbr_width[j].get(i, 0.0) + width

    neighbours = [sorted(d.keys()) for d in nbr_width]
    shared = [[nbr_width[i][j] for j in neighbours[i]] for i in range(n)]

    resistance = None
    if resistance_by_block:
        resistance = np.array(
            [float(resistance_by_block.get(b.block_id, 1.0)) for b in blocks],
            dtype=np.float64,
        )

    return BlockLayer(
        block_ids=ids, lon=lon, lat=lat, area_m2=area, perimeter_m=perim,
        population=population, egress_width_m=egress,
        district=[b.district for b in blocks],
        neighbours=neighbours, shared_width_m=shared,
        resistance=resistance,
    )


# ────────────────────────────────────────────────────────────────────────────
# Hazard field
# ────────────────────────────────────────────────────────────────────────────

def mmi_field(layer: BlockLayer, config: BlockScaleConfig) -> np.ndarray:
    """Per-block MMI from a simple distance attenuation relation.

    This is a transparent demonstration attenuation, **not** a validated GMPE.
    Replace with a ShakeMap raster lookup before drawing any conclusion about
    a specific scenario.
    """
    kx = 111_320.0 * np.cos(np.radians(layer.lat))
    dx = (layer.lon - config.epicenter_lon) * kx
    dy = (layer.lat - config.epicenter_lat) * 110_540.0
    dist_km = np.hypot(dx, dy) / 1000.0
    mmi = 1.5 * config.magnitude - 2.6 * np.log10(dist_km + 10.0) - 0.5
    return np.clip(mmi, 0.0, 12.0)


# ────────────────────────────────────────────────────────────────────────────
# Routing: multi-source Dijkstra from shelters over the block graph
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class RoutingTree:
    """Next-hop routing toward the nearest reachable shelter."""

    next_hop: np.ndarray          # int32, -1 = no route
    distance_m: np.ndarray        # float64, inf = unreachable
    shelter_index: np.ndarray     # int32, -1 = unserved
    hop_capacity_pps: np.ndarray  # float64, persons/s out of each block
    hop_time_s: np.ndarray        # float64, free-flow time to cross one hop


def build_routing_tree(
    layer: BlockLayer,
    shelter_blocks: Sequence[int],
    config: BlockScaleConfig,
    *,
    blocked_blocks: Sequence[int] = (),
) -> RoutingTree:
    """Multi-source Dijkstra outward from shelter blocks, weighted by
    cumulative walking resistance rather than raw distance.

    Each hop's cost is its physical centroid-to-centroid distance times the
    mean of the two blocks' ``resistance`` (terrain slope + land cover; see
    ``BlockLayer.resistance``). With the default all-ones resistance this is
    identical to plain shortest-path distance. This is the same
    minimum-cumulative-resistance (MCR) mechanism landscape ecology uses to
    route ecological flows through a friction surface (Knaapen et al. 1992),
    applied here to pedestrian routing instead. ``blocked_blocks`` (e.g.
    debris-blocked or liquefaction-affected) are excluded from the graph
    entirely, on top of whatever finite resistance they might also carry;
    a block with ``resistance == inf`` (e.g. open water, never crossed
    off-road) is excluded just as effectively without being listed here.
    """
    n = len(layer)
    blocked = set(int(b) for b in blocked_blocks)

    dist = np.full(n, np.inf, dtype=np.float64)
    nxt = np.full(n, -1, dtype=np.int32)
    src = np.full(n, -1, dtype=np.int32)

    kx = 111_320.0 * np.cos(np.radians(layer.lat))

    heap: list[tuple[float, int, int, int]] = []
    for s_idx, b_idx in enumerate(shelter_blocks):
        if b_idx < 0 or b_idx in blocked or not np.isfinite(layer.resistance[b_idx]):
            continue
        dist[b_idx] = 0.0
        src[b_idx] = s_idx
        heapq.heappush(heap, (0.0, b_idx, -1, s_idx))

    while heap:
        d, u, via, s_idx = heapq.heappop(heap)
        if d > dist[u]:
            continue
        nxt[u] = via
        src[u] = s_idx
        for v in layer.neighbours[u]:
            if v in blocked or not np.isfinite(layer.resistance[v]):
                continue
            step = math.hypot((layer.lon[v] - layer.lon[u]) * kx[u],
                              (layer.lat[v] - layer.lat[u]) * 110_540.0)
            resistance = 0.5 * (layer.resistance[u] + layer.resistance[v])
            nd = d + step * resistance
            if nd < dist[v] and nd <= config.max_shelter_distance_m:
                dist[v] = nd
                heapq.heappush(heap, (nd, v, u, s_idx))

    src[np.isinf(dist)] = -1

    # Hop capacity: the shared boundary width toward the next hop, times the
    # pedestrian specific flow, further capped by the block's own egress.
    hop_cap = np.zeros(n, dtype=np.float64)
    hop_time = np.full(n, np.inf, dtype=np.float64)
    for u in range(n):
        v = int(nxt[u])
        if v < 0:
            # Root of the tree: either a shelter block, where the constraint is
            # the shelter gate rather than a downstream street, or an
            # unreachable block, which is zeroed separately by ``unserved_mask``.
            if src[u] >= 0:
                hop_cap[u] = np.inf
                hop_time[u] = 0.0
            continue
        try:
            k = layer.neighbours[u].index(v)
            width = layer.shared_width_m[u][k]
        except ValueError:
            width = DEFAULT_EGRESS_WIDTH_M["default"]
        hop_cap[u] = width * config.specific_flow
        step = math.hypot((layer.lon[v] - layer.lon[u]) * kx[u],
                          (layer.lat[v] - layer.lat[u]) * 110_540.0)
        resistance = 0.5 * (layer.resistance[u] + layer.resistance[v])
        hop_time[u] = step * resistance / config.free_flow_speed_mps

    return RoutingTree(next_hop=nxt, distance_m=dist, shelter_index=src,
                       hop_capacity_pps=hop_cap, hop_time_s=hop_time)


# ────────────────────────────────────────────────────────────────────────────
# The simulator
# ────────────────────────────────────────────────────────────────────────────

class BlockEvacuationSimulator:
    """Capacity-constrained block-scale evacuation.

    State per block, all float64 arrays of length ``n_blocks``:

    ``indoors``   people who have not yet started moving
    ``internal``  people walking inside their block toward its boundary
    ``queued``    people waiting at the block boundary for street capacity
    ``sheltered`` people admitted to a shelter (absorbed)
    """

    def __init__(
        self,
        layer: BlockLayer,
        shelters: Sequence[ShelterSite],
        config: BlockScaleConfig | None = None,
        *,
        blocked_blocks: Sequence[int] = (),
    ):
        self.layer = layer
        self.config = config or BlockScaleConfig()
        self.rng = np.random.default_rng(self.config.seed)
        self.shelters = list(shelters)
        self.blocked_blocks = list(blocked_blocks)

        n = len(layer)
        self.n = n

        if self.config.target_population:
            total = float(layer.population.sum())
            if total > 0:
                layer.population = layer.population * (self.config.target_population / total)

        self.mmi = mmi_field(layer, self.config)

        participation = np.where(
            self.mmi >= self.config.mmi_evacuation_threshold,
            self.config.participation_high,
            self.config.participation_low,
        )
        self.will_evacuate = layer.population * participation
        self.stay_put = layer.population - self.will_evacuate

        # Shelter -> block index by nearest centroid.
        block_of_shelter = self._locate_shelters()
        self._shelter_block = block_of_shelter
        self._shelters_by_block: dict[int, list[int]] = defaultdict(list)
        for s_idx, b_idx in enumerate(block_of_shelter):
            if b_idx >= 0:
                self._shelters_by_block[b_idx].append(s_idx)
        self._full_shelters: set[int] = set()
        self._reroute_events: list[dict] = []
        self.routing = build_routing_tree(layer, block_of_shelter, self.config,
                                          blocked_blocks=blocked_blocks)

        # Stocks
        self.indoors = self.will_evacuate.copy()
        self.internal = np.zeros(n)
        self.queued = np.zeros(n)
        self.sheltered = np.zeros(n)
        self.shelter_occupancy = np.zeros(len(self.shelters))
        #: Fraction of nominal capacity actually usable per shelter, in
        #: [0, 1]. Defaults to 1.0 everywhere (identical to not having this
        #: knob at all). A controller (see rl/shelter_agents.py) can lower a
        #: shelter's cutoff *before* it would otherwise fill, so admission is
        #: throttled proactively instead of only reacting once capacity is
        #: hit exactly -- the mechanism this project's own reroute events
        #: already show is late and disruptive.
        self.shelter_cutoff = np.ones(len(self.shelters))
        #: Fraction of nominal capacity that must be free (effective
        #: capacity minus occupancy) before a shelter marked "full" is
        #: reopened, on top of merely crossing back over its effective
        #: capacity. Without this margin, a shelter whose cutoff hovers
        #: near its occupancy setpoint (e.g. an admission controller
        #: adjusting cutoff in small steps) flips full/not-full on every
        #: adjustment, and each flip forces an expensive network-wide
        #: reroute -- exactly the reroute-thrashing this project's own RL
        #: ablation found once the one-way latch bug was fixed (see
        #: rl/shelter_agents.py).
        self.reopen_hysteresis = config.shelter_reopen_hysteresis

        # Intra-block walk time to reach the boundary, also subject to that
        # block's own terrain resistance (a resistance-surface block is not
        # only slower to leave toward a neighbour, it is slower to cross
        # internally too).
        radius = np.sqrt(np.maximum(layer.area_m2, 1.0) / math.pi)
        self.internal_time_s = np.maximum(
            radius * self.config.intra_block_detour * layer.resistance / self.config.free_flow_speed_mps,
            float(self.config.step_seconds),
        )

        # Egress capacity in persons per step.
        self.egress_pps = layer.egress_width_m * self.config.specific_flow
        self.hop_pps = self.routing.hop_capacity_pps

        #: Instantaneous reachability, recomputed every time a shelter fills
        #: and the routing tree is rebuilt. Correct for the dynamics (a block
        #: whose only shelter is now full must stop pushing outflow this step),
        #: but NOT a measure of evacuation failure: late in a run most shelters
        #: are full, so this mask flags blocks that were reachable and sent
        #: most of their people out before their shelter filled.
        self.unserved_mask = self.routing.shelter_index < 0

        #: Structural reachability, frozen at the initial routing tree (every
        #: shelter still open). A block is structurally unserved only if it
        #: could reach NO shelter even when all of them had room -- a genuine
        #: distance/coverage failure. This is the mask the outcome metrics use,
        #: so "unserved" means "never had anywhere to go", not "arrived after
        #: the nearest shelter had already filled".
        self.structural_unserved_mask = self.routing.shelter_index < 0

        self.step_index = 0
        self.history: list[dict] = []
        self._flow_accum = np.zeros(n)

        # Per-block time series, used only to reconstruct individual
        # rendered-agent departure/transit timing after the run (see
        # `sample_rendered_agents`). Snapshot 0 is the initial state so
        # interpolation has a left edge at t=0.
        #
        # `departed` (= will_evacuate - indoors) is a genuinely per-origin-block
        # quantity, since `indoors` never receives inflow from other blocks, so
        # it can be inverted to get a real per-block departure time.
        #
        # `sheltered`, by contrast, is recorded at whichever block *hosts* a
        # shelter and mixes arrivals from every block that routes through it,
        # so it cannot be inverted per origin block. Individual arrival time is
        # instead reconstructed in `_traverse_route` by advecting each sampled
        # point through the real, already-solved `congestion` field hop by
        # hop (a standard Eulerian-field / Lagrangian-particle post-process).
        self.snapshot_time_s: list[float] = [0.0]
        self.snapshot_departed: list[np.ndarray] = [np.zeros(n)]
        self.snapshot_congestion: list[np.ndarray] = [np.ones(n)]

    # -- setup helpers ----------------------------------------------------

    def _locate_shelters(self) -> list[int]:
        layer = self.layer
        out: list[int] = []
        kx = 111_320.0 * math.cos(math.radians(float(np.mean(layer.lat))))
        for shelter in self.shelters:
            if shelter.block_id is not None:
                try:
                    out.append(layer.block_ids.index(shelter.block_id))
                    continue
                except ValueError:
                    pass
            dx = (layer.lon - shelter.lon) * kx
            dy = (layer.lat - shelter.lat) * 110_540.0
            d2 = dx * dx + dy * dy
            best = int(np.argmin(d2))
            # argmin always returns something, so a shelter tens of kilometres
            # outside the simulated window would otherwise be snapped onto a
            # boundary block and used as if it were local. That silently handed
            # a 1 M central-urban window the whole municipality's shelter
            # capacity. Only bind a shelter that is genuinely near a block.
            if math.sqrt(float(d2[best])) > self.config.shelter_snap_max_m:
                out.append(-1)
            else:
                out.append(best)
        return out

    def _rebuild_routing(self) -> None:
        """Recompute the routing tree over shelters that still have room.

        Called when a shelter fills.  Blocks with no remaining reachable
        shelter become unserved, and their queued population is reported
        rather than being silently absorbed.
        """
        sources = [b if s not in self._full_shelters else -1
                   for s, b in enumerate(self._shelter_block)]
        self.routing = build_routing_tree(
            self.layer, sources, self.config, blocked_blocks=self.blocked_blocks
        )
        self.hop_pps = self.routing.hop_capacity_pps
        self.unserved_mask = self.routing.shelter_index < 0
        self._reroute_events.append({
            "step": self.step_index,
            "time_min": round(self.step_index * self.config.step_seconds / 60.0, 2),
            "full_shelters": sorted(self._full_shelters),
            "remaining_shelters": len(self.shelters) - len(self._full_shelters),
            "unserved_blocks": int(self.unserved_mask.sum()),
        })

    # -- dynamics ---------------------------------------------------------

    def _departure_increment(self, t_now: float, dt: float) -> np.ndarray:
        """Fraction of the evacuating cohort that starts moving in [t, t+dt).

        Lognormal departure delay: median ``departure_median_s`` with shape
        ``departure_sigma``.  Empirical post-earthquake departure studies
        (e.g. Makinoshima et al. on Noto) report aggregate movement beginning
        2-3 minutes after shaking and largely complete within 10 minutes,
        which the default parameters reproduce.
        """
        def cdf(t: float) -> float:
            if t <= 0:
                return 0.0
            z = (math.log(t) - math.log(self.config.departure_median_s)) / self.config.departure_sigma
            return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

        return np.float64(cdf(t_now + dt) - cdf(t_now))

    def step(self) -> dict:
        """Advance one time step."""
        cfg = self.config
        dt = float(cfg.step_seconds)
        t_now = self.step_index * dt
        self.step_index += 1

        # 1. Departure: indoors -> internal
        frac = self._departure_increment(t_now, dt)
        starting = np.minimum(self.indoors, self.will_evacuate * frac)
        self.indoors -= starting
        self.internal += starting

        # 2. Internal walk to the block boundary -> queued
        reach_frac = np.clip(dt / self.internal_time_s, 0.0, 1.0)
        to_boundary = self.internal * reach_frac
        self.internal -= to_boundary
        self.queued += to_boundary

        # 3. Egress + hop capacity, with density-dependent speed reduction.
        #    Crowding at the boundary reduces achievable specific flow.
        density = np.where(self.layer.perimeter_m > 0,
                           self.queued / np.maximum(self.layer.perimeter_m * 3.0, 1.0),
                           0.0)
        congestion = np.clip(1.0 - density / cfg.jam_density, 0.05, 1.0)
        capacity = np.minimum(self.egress_pps, self.hop_pps) * congestion * dt
        capacity[self.unserved_mask] = 0.0

        # Transit constraint: a person can only reach the next block once they
        # have physically walked the hop.  Without this the queue would advance
        # one full hop per time step regardless of hop length, which makes
        # clearance times a function of ``step_seconds`` rather than distance.
        transit = np.clip(dt / np.maximum(self.routing.hop_time_s, 1e-9), 0.0, 1.0)
        outflow = np.minimum(self.queued * transit, capacity)
        self.queued -= outflow

        # 4. Deliver outflow to the next hop, or into a shelter.
        nxt = self.routing.next_hop
        inflow = np.zeros(self.n)
        arriving_at_shelter = np.zeros(len(self.shelters))

        at_shelter = nxt < 0
        moving = ~at_shelter & (outflow > 0)

        np.add.at(inflow, nxt[moving], outflow[moving])

        # Blocks that *are* shelter blocks absorb into their shelter(s).
        # Several shelters can share a block, so the block's outflow is split
        # between them by remaining capacity rather than counted once each.
        for b_idx, s_indices in self._shelters_by_block.items():
            if nxt[b_idx] >= 0 or outflow[b_idx] <= 0:
                continue
            rooms = [max(0.0, self.shelters[s].capacity * self.shelter_cutoff[s] - self.shelter_occupancy[s])
                     for s in s_indices]
            total_room = sum(rooms)
            if total_room <= 0:
                arriving_at_shelter[s_indices[0]] += outflow[b_idx]
                continue
            for s, room in zip(s_indices, rooms):
                arriving_at_shelter[s] += outflow[b_idx] * room / total_room

        self.queued += inflow
        self._flow_accum += outflow

        # 5. Shelter admission with capacity; overflow triggers a reroute.
        overflow_total = 0.0
        newly_full = False
        for s_idx, shelter in enumerate(self.shelters):
            arriving = arriving_at_shelter[s_idx]
            if arriving <= 0:
                continue
            room = max(0.0, shelter.capacity * self.shelter_cutoff[s_idx] - self.shelter_occupancy[s_idx])
            admitted = min(arriving, room)
            self.shelter_occupancy[s_idx] += admitted
            shelter.occupants = float(self.shelter_occupancy[s_idx])
            b_idx = self._shelter_block[s_idx]
            if b_idx < 0:
                # Not bound to any block (too far outside the window), so no
                # block ever routes to it and it cannot receive arrivals.
                # Guarded explicitly so a -1 can never index from the end.
                continue
            self.sheltered[b_idx] += admitted
            rejected = arriving - admitted
            if rejected > 0:
                self.queued[b_idx] += rejected
                overflow_total += rejected
                if s_idx not in self._full_shelters:
                    self._full_shelters.add(s_idx)
                    newly_full = True
            # Retire a shelter once it is nearly full, not only once it has
            # actually turned someone away. Waiting for outright rejection
            # means a whole block keeps funnelling down one next-hop chain
            # until the destination is exactly full, and only then gets
            # re-pointed -- often somewhere far, while nearer shelters still
            # hold room. Retiring early lets the rebuild hand those blocks to
            # a closer shelter that still has space.
            elif (self.config.shelter_retire_at < 1.0
                  and s_idx not in self._full_shelters):
                effective = shelter.capacity * self.shelter_cutoff[s_idx]
                if (effective > 0
                        and self.shelter_occupancy[s_idx]
                        >= effective * self.config.shelter_retire_at):
                    self._full_shelters.add(s_idx)
                    newly_full = True

        # 6. Capacity-aware reroute: once a shelter is full it stops being a
        #    sink, and the routing tree is rebuilt over the shelters that still
        #    have room.  Without this, overflow oscillates against a full
        #    shelter forever instead of walking on to the next one.
        #
        #    "Full" is re-evaluated every step against *current* effective
        #    capacity (capacity x shelter_cutoff), not latched permanently at
        #    first rejection: occupancy never decreases, but shelter_cutoff
        #    can be raised again later (e.g. by a controller easing off a
        #    proactive throttle -- see rl/shelter_agents.py), and a shelter
        #    with newly-freed room has to become reachable again for that
        #    control lever to mean anything.
        #
        #    Reopening requires more than a bare crossing, though: it must
        #    clear effective capacity by ``reopen_hysteresis`` x nominal
        #    capacity. Occupancy itself never decreases, so this margin only
        #    ever changes the reopen threshold as effective_capacity moves
        #    (i.e. as a controller adjusts shelter_cutoff) -- it exists to
        #    stop a cutoff hovering near its own occupancy from re-triggering
        #    a reroute on every adjustment.
        freed = False
        for s_idx in list(self._full_shelters):
            shelter = self.shelters[s_idx]
            effective_capacity = shelter.capacity * self.shelter_cutoff[s_idx]
            # Reopen below the level a shelter is retired at, not below its
            # full capacity: with shelter_retire_at < 1.0 a shelter retired at
            # (say) 85% would otherwise satisfy the plain "< capacity" test on
            # the very next step and reopen immediately, thrashing the routing
            # tree once per step.
            retire_level = effective_capacity * self.config.shelter_retire_at
            margin = self.reopen_hysteresis * shelter.capacity
            if self.shelter_occupancy[s_idx] < retire_level - margin - 1e-6:
                self._full_shelters.discard(s_idx)
                freed = True
        if newly_full or freed:
            self._rebuild_routing()

        record = {
            "step": self.step_index,
            "time_s": int(t_now + dt),
            "time_min": round((t_now + dt) / 60.0, 2),
            "indoors": float(self.indoors.sum()),
            "internal": float(self.internal.sum()),
            "queued": float(self.queued.sum()),
            "sheltered": float(self.sheltered.sum()),
            "stay_put": float(self.stay_put.sum()),
            "outflow": float(outflow.sum()),
            "shelter_overflow": float(overflow_total),
            "congested_blocks": int((congestion < 0.5).sum()),
            "mean_congestion": float(congestion.mean()),
            "full_shelters": len(self._full_shelters),
            "unserved_blocks": int(self.unserved_mask.sum()),
        }
        self.history.append(record)

        if self.step_index % cfg.snapshot_every_steps == 0:
            self.snapshot_time_s.append(t_now + dt)
            self.snapshot_departed.append((self.will_evacuate - self.indoors).copy())
            self.snapshot_congestion.append(congestion.copy())

        return record

    def run(self) -> list[dict]:
        steps = int(self.config.duration_minutes * 60 // self.config.step_seconds)
        for _ in range(steps):
            self.step()
        # Guarantee the horizon's right edge is captured even when the step
        # count isn't a multiple of snapshot_every_steps, so agent timing
        # interpolation never has to extrapolate past the last known stock.
        if self.snapshot_time_s[-1] < steps * self.config.step_seconds:
            self.snapshot_time_s.append(steps * self.config.step_seconds)
            self.snapshot_departed.append((self.will_evacuate - self.indoors).copy())
            self.snapshot_congestion.append(self.snapshot_congestion[-1].copy())
        return self.history

    # -- reporting --------------------------------------------------------

    def clearance_time_min(self, quantile: float = 0.9) -> float | None:
        """Time at which ``quantile`` of the evacuating cohort is sheltered."""
        target = float(self.will_evacuate.sum()) * quantile
        for record in self.history:
            if record["sheltered"] >= target:
                return record["time_min"]
        return None

    def block_summary(self) -> list[dict]:
        layer = self.layer
        return [
            {
                "block_id": layer.block_ids[i],
                "lon": round(float(layer.lon[i]), 6),
                "lat": round(float(layer.lat[i]), 6),
                "area_m2": round(float(layer.area_m2[i]), 1),
                "district": layer.district[i],
                "population": round(float(layer.population[i]), 2),
                "will_evacuate": round(float(self.will_evacuate[i]), 2),
                "sheltered": round(float(self.sheltered[i]), 2),
                "queued": round(float(self.queued[i]), 2),
                "mmi": round(float(self.mmi[i]), 2),
                "egress_width_m": round(float(layer.egress_width_m[i]), 1),
                "shelter_distance_m": (None if math.isinf(self.routing.distance_m[i])
                                       else round(float(self.routing.distance_m[i]), 1)),
                "throughput": round(float(self._flow_accum[i]), 2),
                # Terrain walking resistance actually used for routing (1.0 =
                # flat-plane default, inf = not crossable on foot). Exported so
                # a block-level analysis can regress outcomes on terrain
                # without re-deriving the surface.
                "resistance": (None if math.isinf(float(self.layer.resistance[i]))
                                else round(float(self.layer.resistance[i]), 4)),
                # Structural: could this block reach no shelter even at t=0.
                "unserved": bool(self.structural_unserved_mask[i]),
                "no_open_shelter_at_end": bool(self.unserved_mask[i]),
            }
            for i in range(self.n)
        ]

    # -- individual-agent rendering sample ---------------------------------

    def _route_chain(self, block_index: int, max_hops: int = 2000) -> list[int]:
        """Block indices from ``block_index`` to its shelter block, inclusive.

        Uses the *final* routing tree (after all reroutes), so the path shown
        is the one that was actually valid by the end of the run. An unserved
        block (no route) returns just itself.
        """
        chain = [block_index]
        seen = {block_index}
        cur = block_index
        for _ in range(max_hops):
            nxt = int(self.routing.next_hop[cur])
            if nxt < 0 or nxt in seen:
                break
            chain.append(nxt)
            seen.add(nxt)
            cur = nxt
        return chain

    @staticmethod
    def _interp_crossing(times: Sequence[float], cum: Sequence[float], target: float) -> float | None:
        """First time at which a non-decreasing cumulative curve reaches ``target``.

        Linear interpolation between the two bracketing snapshots. Returns
        ``None`` if the curve never reaches ``target`` within the horizon.
        """
        if target <= cum[0]:
            return times[0]
        for i in range(1, len(times)):
            if cum[i] >= target:
                lo, hi = cum[i - 1], cum[i]
                if hi <= lo:
                    return times[i]
                frac = (target - lo) / (hi - lo)
                return times[i - 1] + frac * (times[i] - times[i - 1])
        return None

    def _congestion_at(self, block_index: int, t: float) -> float:
        """Interpolated congestion factor (1 = free flow, ~0.05 = jammed)."""
        times = self.snapshot_time_s
        if t <= times[0]:
            return float(self.snapshot_congestion[0][block_index])
        if t >= times[-1]:
            return float(self.snapshot_congestion[-1][block_index])
        i = int(np.searchsorted(times, t))
        lo, hi = times[i - 1], times[i]
        frac = 0.0 if hi <= lo else (t - lo) / (hi - lo)
        c_lo = self.snapshot_congestion[i - 1][block_index]
        c_hi = self.snapshot_congestion[i][block_index]
        return float(c_lo + frac * (c_hi - c_lo))

    def _traverse_route(self, chain: list[int], depart_s: float,
                        horizon_s: float) -> tuple[float | None, float]:
        """Advect one point through the already-solved congestion field.

        The block-scale model is Eulerian (stocks, not individually tagged
        people), so an individual's arrival time can't be read directly off
        any per-block stock. Instead this walks the point hop by hop along
        its real route, at each hop taking the *free-flow* hop time
        (``routing.hop_time_s``, itself bounded by the shared boundary width
        and pedestrian specific flow) and inflating it by the real, already-
        simulated congestion factor at that block around the time the point
        would be passing through it. This is a standard Eulerian-field /
        Lagrangian-particle reconstruction, not a separate invented curve.

        Returns ``(arrive_s, progress_at_horizon)``. ``arrive_s`` is ``None``
        when the point hasn't reached its shelter by ``horizon_s``, in which
        case ``progress_at_horizon`` (0-1, by cumulative walked distance
        along the route) says how far it got, so a renderer can show it
        stalled at the right place instead of frozen at the start or
        teleported to the end.
        """
        hop_dist = [self.routing.distance_m[chain[i]] - self.routing.distance_m[chain[i + 1]]
                   for i in range(len(chain) - 1)]
        total_dist = sum(hop_dist) or 1.0

        t = depart_s + float(self.internal_time_s[chain[0]])
        covered = 0.0
        for i, b in enumerate(chain[:-1]):
            if t > horizon_s:
                return None, covered / total_dist
            cong = self._congestion_at(b, t)
            hop_t = self.routing.hop_time_s[b]
            if not math.isfinite(hop_t):
                return None, covered / total_dist
            hop_t_congested = hop_t / max(cong, 0.05)
            if t + hop_t_congested > horizon_s and hop_t_congested > 0:
                frac_of_hop = (horizon_s - t) / hop_t_congested
                return None, (covered + frac_of_hop * hop_dist[i]) / total_dist
            t += hop_t_congested
            covered += hop_dist[i]
        return t, 1.0

    def sample_rendered_agents(self, n: int, *, seed: int | None = None) -> list[dict]:
        """Sample ``n`` individual pedestrian points for point-based rendering.

        Each point is a real sample from the simulated population: it is
        assigned a home block by population weight, a departure time read
        off that block's own real cumulative-departed curve, a route that is
        the actual block-to-block path its cohort walks toward its shelter,
        and (if reached within the horizon) an arrival time reconstructed by
        advecting it hop by hop through the real, already-solved per-block
        congestion field (see `_traverse_route`). Individual departure timing
        within a shared block cohort is a stratified approximation (evenly
        spread across the block's real aggregate departure curve), since the
        underlying model carries stocks rather than individually identified
        people; there is no per-block "who arrived" stock to invert directly,
        because arrivals are recorded at the shelter's block and mix cohorts
        from every block routed through it.
        """
        rng = np.random.default_rng(seed if seed is not None else self.config.seed + 1)
        layer = self.layer
        we = self.will_evacuate
        eligible = np.where(we > 1e-9)[0]
        if eligible.size == 0 or n <= 0:
            return []

        weights = we[eligible]
        weights = weights / weights.sum()
        # Deterministic weighted sample with replacement, then sort by block
        # so each block's cohort gets a contiguous, evenly-spread rank.
        picks = rng.choice(eligible, size=n, p=weights)
        picks.sort()

        times = self.snapshot_time_s
        horizon_s = times[-1]
        agents: list[dict] = []
        route_cache: dict[int, list[int]] = {}

        counts = np.bincount(picks, minlength=self.n)
        rank_in_block = np.zeros(self.n, dtype=np.int64)

        for agent_id, block_idx in enumerate(picks):
            block_idx = int(block_idx)
            m = int(counts[block_idx])
            k = int(rank_in_block[block_idx])
            rank_in_block[block_idx] += 1
            rank_frac = (k + 0.5) / m

            target = rank_frac * float(we[block_idx])
            dep_cum = [float(s[block_idx]) for s in self.snapshot_departed]
            depart_s = self._interp_crossing(times, dep_cum, target)

            if block_idx not in route_cache:
                route_cache[block_idx] = self._route_chain(block_idx)
            chain = route_cache[block_idx]
            route = [[round(float(layer.lon[b]), 6), round(float(layer.lat[b]), 6)]
                     for b in chain]

            shelter_idx = int(self.routing.shelter_index[block_idx])
            progress_at_horizon = 0.0
            if shelter_idx < 0 or depart_s is None:
                arrive_s = None
            else:
                arrive_s, progress_at_horizon = self._traverse_route(chain, depart_s, horizon_s)

            agents.append({
                "agent_id": agent_id,
                "home_block": layer.block_ids[block_idx],
                "represented_population": round(float(we[block_idx]) / m, 3),
                "shelter_id": (self.shelters[shelter_idx].shelter_id
                              if shelter_idx >= 0 else None),
                "depart_s": (round(depart_s, 1) if depart_s is not None else None),
                "arrive_s": (round(arrive_s, 1) if arrive_s is not None else None),
                # Fraction (by walked distance) of the route covered by the
                # horizon when arrive_s is None -- lets a renderer stall the
                # point at its real position instead of freezing at the
                # start or teleporting to the shelter.
                "progress_at_horizon": round(progress_at_horizon, 4),
                "route": route,
            })
        return agents

    def to_dict(self, *, include_blocks: bool = True) -> dict:
        # Outcome metrics use the STRUCTURAL mask (reachability at t=0, every
        # shelter open), not the end-of-run instantaneous mask. Using the
        # end-of-run mask double-counts: late in a run most shelters are full,
        # so it flags blocks that were reachable and sheltered most of their
        # people before their nearest shelter filled -- which is why an earlier
        # version reported sheltered > "reachable evacuees", an impossibility.
        struct = self.structural_unserved_mask
        unserved_pop = float(self.layer.population[struct].sum())
        total_pop = float(self.layer.population.sum())
        # The operationally meaningful figure is the evacuees who set out and
        # had nowhere reachable to go from the start -- a distance/coverage
        # failure. will_evacuate is per-block, so this split is exact.
        unserved_evacuees = float(self.will_evacuate[struct].sum())
        will_evac_total = float(self.will_evacuate.sum())
        sheltered_total = float(self.sheltered.sum())
        reachable_evacuees = will_evac_total - unserved_evacuees
        return {
            "scale": "block",
            "city": self.config.city,
            "schema_version": "1.0",
            "evidence_class": (
                "Synthetic capacity-constrained scenario on OpenStreetMap "
                "road-enclosed blocks. Not an observed evacuation, not an "
                "official emergency plan."
            ),
            "config": asdict(self.config),
            "assumptions": {
                "specific_flow_persons_per_m_per_s": self.config.specific_flow,
                "specific_flow_source": "Weidmann (1993) / Fruin LOS E range 1.2-1.4",
                "free_flow_speed_mps": self.config.free_flow_speed_mps,
                "departure_distribution": "lognormal",
                "departure_median_s": self.config.departure_median_s,
                "departure_sigma": self.config.departure_sigma,
                "egress_width_by_class_m": DEFAULT_EGRESS_WIDTH_M,
                "mmi_attenuation": "demonstration distance relation, not a validated GMPE",
                "resistance_surface_applied": bool(np.any(self.layer.resistance != 1.0)),
                "known_gaps": [
                    "Vehicle traffic and its interaction with pedestrians is not modelled.",
                    "Building collapse and debris are not yet coupled into blocked_blocks.",
                    "Shelter capacity is largely inferred; see each shelter's provenance.",
                    "Shelter locations themselves may be unverified candidates rather than "
                    "a government-confirmed current roster; see each shelter's provenance "
                    "and, upstream, its operational_status/verification_level flags.",
                    "Routing is recomputed only when a shelter fills, not continuously "
                    "in response to congestion.",
                ],
            },
            "totals": {
                "blocks": self.n,
                "population": round(total_pop, 1),
                "will_evacuate": round(float(self.will_evacuate.sum()), 1),
                "stay_put": round(float(self.stay_put.sum()), 1),
                "sheltered": round(float(self.sheltered.sum()), 1),
                "still_queued": round(float(self.queued.sum()), 1),
                "still_indoors": round(float(self.indoors.sum()), 1),
                # All residents of unreachable blocks, evacuees or not. Kept
                # for backward compatibility; prefer the evacuee fields below.
                "unserved_population": round(unserved_pop, 1),
                # Evacuees with no shelter reachable within the routing cap --
                # a distance/coverage failure, distinct from capacity.
                "unserved_evacuees_no_reachable_shelter": round(unserved_evacuees, 1),
                # Evacuees who could reach a shelter at all.
                "reachable_evacuees": round(reachable_evacuees, 1),
                # Of those reachable, the share who actually got in before
                # capacity ran out -- the pure capacity-vs-demand story.
                "sheltered_share_of_reachable": (
                    round(sheltered_total / reachable_evacuees, 4)
                    if reachable_evacuees > 0 else None),
                "sheltered_share_of_all_evacuees": (
                    round(sheltered_total / will_evac_total, 4)
                    if will_evac_total > 0 else None),
                # Structurally unreachable blocks (frozen at t=0), matching the
                # evacuee figures above.
                "unserved_blocks": int(struct.sum()),
                # End-of-run instantaneous count, for comparison: how many
                # blocks had no open shelter left when the run ended.
                "blocks_no_open_shelter_at_end": int(self.unserved_mask.sum()),
                # Capacity of every shelter in the loaded file, including any
                # that sit outside the simulated window. Kept for provenance.
                "shelter_capacity": round(sum(s.capacity for s in self.shelters), 1),
                # Capacity actually usable: a shelter only absorbs anyone if
                # some block routes to it, so a shelter outside the window (or
                # behind impassable terrain) contributes nothing however large
                # it is. Reporting only the file total made a 1 M central-urban
                # window look like it had the whole municipality's capacity
                # available even when many shelters were outside the scenario.
                "shelter_capacity_reachable": round(
                    sum(s.capacity for i, s in enumerate(self.shelters)
                        if self._shelter_block[i] >= 0
                        and not self.structural_unserved_mask[self._shelter_block[i]]), 1),
                "shelters_reachable_count": int(sum(
                    1 for i in range(len(self.shelters))
                    if self._shelter_block[i] >= 0
                    and not self.structural_unserved_mask[self._shelter_block[i]])),
                "clearance_time_p50_min": self.clearance_time_min(0.5),
                "clearance_time_p90_min": self.clearance_time_min(0.9),
            },
            "conservation": self._conservation(),
            "reroute_events": self._reroute_events,
            "shelters": [
                {"shelter_id": s.shelter_id, "name": s.name, "lon": s.lon, "lat": s.lat,
                 "capacity": s.capacity, "occupants": round(s.occupants, 1),
                 "provenance": s.provenance}
                for s in self.shelters
            ],
            "history": self.history,
            "blocks": self.block_summary() if include_blocks else [],
        }

    def _conservation(self) -> dict:
        accounted = float(
            self.indoors.sum() + self.internal.sum() + self.queued.sum()
            + self.sheltered.sum() + self.stay_put.sum()
        )
        expected = float(self.layer.population.sum())
        return {
            "expected_population": round(expected, 3),
            "accounted_population": round(accounted, 3),
            "absolute_error": round(abs(expected - accounted), 6),
            "relative_error": (abs(expected - accounted) / expected) if expected else 0.0,
        }


# ────────────────────────────────────────────────────────────────────────────
# Shelter loading
# ────────────────────────────────────────────────────────────────────────────

def load_shelters_geojson(path: Path, config: BlockScaleConfig) -> list[ShelterSite]:
    """Load shelter points, inferring capacity where it is not recorded.

    Capacity that has to be inferred is marked in ``provenance`` so downstream
    reporting can distinguish an official figure from an assumption. When the
    source file already carries its own ``capacity_source`` label (for example,
    ``scenario_assumption_not_observed``), that label is used verbatim rather
    than being overwritten with a generic "recorded capacity" -- a numeric
    capacity field being *present* doesn't mean it's an *official* figure.

    Capacity resolution order per candidate, first match wins:
    1. ``capacity`` / ``capacity_persons`` field, if present and non-empty.
    2. ``area_m2`` x ``shelter_persons_per_m2``, if an area is given.
    3. A type-based default from ``DEFAULT_CAPACITY_BY_SHELTER_TYPE``, read
       from ``shelter_type`` (or ``amenity`` / ``leisure`` as a fallback key,
       matching common OSM tagging) -- e.g. a park and a hospital candidate
       from the same raw POI dump get different assumed capacities instead of
       both being flattened to one identical number.
    4. A flat default, only when no type information exists at all.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    sites: list[ShelterSite] = []
    for i, feature in enumerate(payload.get("features", [])):
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        lon, lat = geom["coordinates"][:2]
        capacity = props.get("capacity") or props.get("capacity_persons")
        capacity_source = props.get("capacity_source")
        if capacity and capacity_source:
            provenance = str(capacity_source)
        elif capacity:
            provenance = "recorded capacity"
        else:
            area = float(props.get("area_m2") or 0.0)
            shelter_type = str(props.get("shelter_type") or props.get("amenity")
                               or props.get("leisure") or "").strip().lower()
            if area:
                capacity = area * config.shelter_persons_per_m2
                provenance = "inferred from area"
            elif shelter_type in DEFAULT_CAPACITY_BY_SHELTER_TYPE:
                capacity = DEFAULT_CAPACITY_BY_SHELTER_TYPE[shelter_type]
                provenance = f"assumed default for type '{shelter_type}'; no official capacity available"
            else:
                capacity = 20_000.0
                provenance = "assumed default; no official capacity or type available"
        sites.append(ShelterSite(
            shelter_id=str(props.get("shelter_id") or props.get("id") or f"S{i:04d}"),
            name=str(props.get("official_2010_name") or props.get("name") or f"shelter-{i}"),
            lon=float(lon), lat=float(lat),
            capacity=float(capacity),
            provenance=provenance,
        ))
    return sites
