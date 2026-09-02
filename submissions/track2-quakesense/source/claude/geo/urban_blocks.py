"""Road-enclosed block extraction and population disaggregation.

This module turns an OpenStreetMap road extract into a *planar partition* of
road-enclosed blocks, the spatial unit used by the block-scale evacuation
experiments.

Why planar faces instead of a raster grid
-----------------------------------------
A 25 m or 1 km grid cell has no relationship to the built form: a cell can
straddle a river, a ring road and three residential compounds.  A road-enclosed
block is the unit that actually constrains pedestrian evacuation — residents
leave a block through a bounded number of edges onto the street network, and
those edges are where queuing happens.  Blocks therefore give us a physically
meaningful place to put departure curves, egress capacity and intra-block
walking time, which a grid cannot.

Method
------
1.  Node the road LineStrings on shared coordinates (OSM extracts are already
    noded at junctions, so exact coordinate matching at 1e-7 deg is sufficient;
    see ``PRECISION``).
2.  Build an undirected planar graph and iteratively prune degree-1 nodes
    (cul-de-sacs and dangling stubs bound no face).
3.  Extract faces by half-edge traversal: from directed edge (u, v), the next
    half-edge is (v, w) where w is the clockwise predecessor of u in the
    angular order around v.  This yields counter-clockwise interior faces and
    clockwise outer boundaries.
4.  Filter faces by area to drop slivers (dual carriageway gores, roundabout
    islands) and the outer/unbounded faces.

Known limitations (do not present these as solved)
--------------------------------------------------
* **Grade separation.** OSM motorways on bridges/tunnels do not share nodes
  with the surface street they cross, so an elevated expressway does not split
  the block beneath it.  Pass ``drop_highways`` to exclude grade-separated
  classes when that matters, or accept the merged block.
* **Extract clipping.** Roads clipped at the download bounding box create
  artificial open faces at the edge; these appear as very large faces and are
  removed by ``max_area_m2``.
* **Not a cadastral or planning boundary.** These are road-enclosed
  morphological blocks, not administrative units. Do not label the output as
  an official administrative division.

The module has no third-party dependency beyond an optional numpy import, so
it runs on the cloud server and in CI without geopandas/shapely.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

# Coordinate rounding used to node the network.  1e-7 deg ~= 1.1 cm, which is
# finer than OSM's storage precision, so identical OSM nodes collapse and
# genuinely distinct nodes never do.
PRECISION = 7

# Highway classes that are grade-separated often enough that including them
# produces blocks split by a viaduct that pedestrians cannot actually cross.
GRADE_SEPARATED = frozenset(
    {"motorway", "motorway_link", "trunk_link", "primary_link",
     "secondary_link", "tertiary_link"}
)

# Default plausible area window for an urban block, in square metres.
# 200 m^2 removes carriageway gores; 5 km^2 removes clipped/outer faces.
MIN_BLOCK_AREA_M2 = 200.0
MAX_BLOCK_AREA_M2 = 5_000_000.0

EARTH_M_PER_DEG_LAT = 110_540.0
EARTH_M_PER_DEG_LON = 111_320.0


# ────────────────────────────────────────────────────────────────────────────
# Geometry helpers (local equirectangular projection; adequate at city extent)
# ────────────────────────────────────────────────────────────────────────────

def local_scale(lat_deg: float) -> tuple[float, float]:
    """Metres per degree of longitude and latitude at ``lat_deg``."""
    return EARTH_M_PER_DEG_LON * math.cos(math.radians(lat_deg)), EARTH_M_PER_DEG_LAT


def ring_metrics(ring: Sequence[tuple[float, float]]) -> tuple[float, float, float, float]:
    """Return (signed_area_m2, centroid_lon, centroid_lat, perimeter_m).

    Positive signed area means counter-clockwise, i.e. an interior face under
    the traversal convention in :func:`extract_faces`.
    """
    n = len(ring)
    if n < 3:
        return 0.0, 0.0, 0.0, 0.0
    lat0 = sum(p[1] for p in ring) / n
    kx, ky = local_scale(lat0)

    area2 = 0.0
    cx = cy = 0.0
    perimeter = 0.0
    for i in range(n):
        x1, y1 = ring[i][0] * kx, ring[i][1] * ky
        x2, y2 = ring[(i + 1) % n][0] * kx, ring[(i + 1) % n][1] * ky
        cross = x1 * y2 - x2 * y1
        area2 += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
        perimeter += math.hypot(x2 - x1, y2 - y1)

    area = area2 / 2.0
    if abs(area2) < 1e-9:
        lon = sum(p[0] for p in ring) / n
        lat = sum(p[1] for p in ring) / n
        return 0.0, lon, lat, perimeter
    cx /= 3.0 * area2
    cy /= 3.0 * area2
    return area, cx / kx, cy / ky, perimeter


def point_in_ring(lon: float, lat: float, ring: Sequence[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon test on a lon/lat ring."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat):
            x_cross = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


# ────────────────────────────────────────────────────────────────────────────
# Planar graph construction
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class RoadGraph:
    """Noded planar graph built from road LineStrings."""

    coords: list[tuple[float, float]] = field(default_factory=list)
    adjacency: dict[int, set[int]] = field(default_factory=lambda: defaultdict(set))
    # Highest road class touching each undirected edge; used for egress capacity.
    edge_class: dict[tuple[int, int], str] = field(default_factory=dict)
    ways_used: int = 0
    ways_skipped: int = 0

    def node_count(self) -> int:
        return len(self.adjacency)

    def edge_count(self) -> int:
        return sum(len(v) for v in self.adjacency.values()) // 2


# Ordered from most to least significant; used when two ways share an edge.
_CLASS_RANK = {
    "motorway": 0, "trunk": 1, "primary": 2, "secondary": 3, "tertiary": 4,
    "unclassified": 5, "residential": 6, "living_street": 7, "service": 8,
    "pedestrian": 9, "footway": 10, "path": 11,
}


def _rank(cls: str | None) -> int:
    return _CLASS_RANK.get(cls or "", 99)


def _iter_lines(geometry: dict) -> Iterable[list[list[float]]]:
    gtype = geometry.get("type")
    if gtype == "LineString":
        yield geometry["coordinates"]
    elif gtype == "MultiLineString":
        yield from geometry["coordinates"]


def build_road_graph(
    features: Iterable[dict],
    *,
    drop_highways: Iterable[str] = (),
    keep_highways: Iterable[str] | None = None,
) -> RoadGraph:
    """Build a noded planar graph from GeoJSON road features."""
    drop = frozenset(drop_highways)
    keep = frozenset(keep_highways) if keep_highways else None

    graph = RoadGraph()
    index: dict[tuple[float, float], int] = {}

    for feature in features:
        highway = (feature.get("properties") or {}).get("highway")
        if highway in drop or (keep is not None and highway not in keep):
            graph.ways_skipped += 1
            continue
        geometry = feature.get("geometry") or {}
        consumed = False
        for line in _iter_lines(geometry):
            node_ids: list[int] = []
            for point in line:
                pkey = (round(point[0], PRECISION), round(point[1], PRECISION))
                nid = index.get(pkey)
                if nid is None:
                    nid = len(graph.coords)
                    index[pkey] = nid
                    graph.coords.append(pkey)
                node_ids.append(nid)
            for a, b in zip(node_ids, node_ids[1:]):
                if a == b:
                    continue
                graph.adjacency[a].add(b)
                graph.adjacency[b].add(a)
                ekey = (a, b) if a < b else (b, a)
                current = graph.edge_class.get(ekey)
                if current is None or _rank(highway) < _rank(current):
                    graph.edge_class[ekey] = highway or "unknown"
                consumed = True
        graph.ways_used += int(consumed)

    return graph


def prune_dangling(graph: RoadGraph) -> RoadGraph:
    """Iteratively remove degree-1 nodes; they bound no face."""
    stack = [n for n, nbrs in graph.adjacency.items() if len(nbrs) <= 1]
    while stack:
        node = stack.pop()
        nbrs = graph.adjacency.get(node)
        if nbrs is None or len(nbrs) > 1:
            continue
        for other in list(nbrs):
            graph.adjacency[other].discard(node)
            if len(graph.adjacency[other]) <= 1:
                stack.append(other)
        graph.adjacency.pop(node, None)
    return graph


def extract_faces(graph: RoadGraph, *, max_cycle_nodes: int = 50_000) -> list[list[int]]:
    """Extract planar faces as node-id cycles via half-edge traversal.

    Interior faces come out counter-clockwise (positive signed area); the outer
    boundary of each connected component comes out clockwise.
    """
    angular: dict[int, tuple[list[int], dict[int, int]]] = {}
    for node, nbrs in graph.adjacency.items():
        x0, y0 = graph.coords[node]
        ordered = sorted(
            nbrs,
            key=lambda m: math.atan2(graph.coords[m][1] - y0, graph.coords[m][0] - x0),
        )
        angular[node] = (ordered, {m: i for i, m in enumerate(ordered)})

    visited: set[tuple[int, int]] = set()
    faces: list[list[int]] = []

    for start_u, nbrs in graph.adjacency.items():
        for start_v in nbrs:
            if (start_u, start_v) in visited:
                continue
            cycle: list[int] = []
            u, v = start_u, start_v
            overflow = False
            while True:
                visited.add((u, v))
                cycle.append(u)
                ordered, position = angular[v]
                idx = position[u]
                nxt = ordered[(idx - 1) % len(ordered)]
                u, v = v, nxt
                if (u, v) == (start_u, start_v):
                    break
                if len(cycle) > max_cycle_nodes:
                    overflow = True
                    break
            if not overflow and len(cycle) >= 3:
                faces.append(cycle)
    return faces


# ────────────────────────────────────────────────────────────────────────────
# Block assembly
# ────────────────────────────────────────────────────────────────────────────

@dataclass
class Block:
    """A road-enclosed block."""

    block_id: str
    ring: list[tuple[float, float]]
    area_m2: float
    perimeter_m: float
    lon: float
    lat: float
    node_ids: list[int] = field(default_factory=list)
    # Road classes on the bounding ring -> number of bounding edges.
    boundary_classes: dict[str, int] = field(default_factory=dict)
    population: float = 0.0
    district: str | None = None
    mmi: float | None = None

    @property
    def equivalent_radius_m(self) -> float:
        """Radius of the area-equivalent circle: a proxy for intra-block walk."""
        return math.sqrt(max(self.area_m2, 1.0) / math.pi)

    def egress_width_m(self, width_by_class: dict[str, float]) -> float:
        """Total usable egress width on the block boundary, in metres."""
        return sum(
            width_by_class.get(cls, width_by_class.get("default", 3.0)) * count
            for cls, count in self.boundary_classes.items()
        )

    def to_feature(self) -> dict:
        return {
            "type": "Feature",
            "id": self.block_id,
            "properties": {
                "block_id": self.block_id,
                "area_m2": round(self.area_m2, 1),
                "perimeter_m": round(self.perimeter_m, 1),
                "lon": round(self.lon, 6),
                "lat": round(self.lat, 6),
                "population": round(self.population, 3),
                "district": self.district,
                "mmi": self.mmi,
                "boundary_classes": self.boundary_classes,
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[round(x, 7), round(y, 7)] for x, y in self.ring]
                                + [[round(self.ring[0][0], 7), round(self.ring[0][1], 7)]]],
            },
        }


def build_blocks(
    graph: RoadGraph,
    faces: Sequence[Sequence[int]],
    *,
    min_area_m2: float = MIN_BLOCK_AREA_M2,
    max_area_m2: float = MAX_BLOCK_AREA_M2,
) -> list[Block]:
    """Convert planar faces into filtered, attributed :class:`Block` records."""
    blocks: list[Block] = []
    for face in faces:
        ring = [graph.coords[n] for n in face]
        area, lon, lat, perimeter = ring_metrics(ring)
        if area <= 0.0:                       # clockwise = outer boundary
            continue
        if not (min_area_m2 <= area <= max_area_m2):
            continue

        classes: dict[str, int] = defaultdict(int)
        for a, b in zip(face, list(face[1:]) + [face[0]]):
            ekey = (a, b) if a < b else (b, a)
            classes[graph.edge_class.get(ekey, "unknown")] += 1

        blocks.append(
            Block(
                block_id=f"B{len(blocks):06d}",
                ring=ring,
                area_m2=area,
                perimeter_m=perimeter,
                lon=lon,
                lat=lat,
                node_ids=list(face),
                boundary_classes=dict(classes),
            )
        )
    return blocks


# ────────────────────────────────────────────────────────────────────────────
# Population disaggregation (areal interpolation, mass conserving)
# ────────────────────────────────────────────────────────────────────────────

def disaggregate_population(
    blocks: Sequence[Block],
    grid_population: dict[Any, float],
    grid_centres: dict[Any, tuple[float, float]],
    *,
    grid_size_deg: float | None = None,
    suitability: dict[str, float] | None = None,
    sample_spacing_m: float = 50.0,
    max_samples_per_block: int = 400,
    coverage_radius_cells: float = 1.0,
) -> dict[str, float]:
    """Distribute coarse grid population onto blocks, conserving total mass.

    Each grid cell's population is split across the blocks that overlap it, in
    proportion to (overlapping block area x optional suitability weight).
    Blocks that fit inside a single cell take a fast centroid path; blocks that
    straddle cells have their area apportioned by interior lattice sampling at
    ``sample_spacing_m``.  Population in a grid cell that overlaps no block —
    water, farmland, airport aprons — is reported as ``residual`` rather than
    silently redistributed onto neighbouring blocks.

    Parameters
    ----------
    grid_population:
        Population per coarse cell (e.g. the WorldMove ~1 km cells already used
        by ``simulator.population_alignment``).
    grid_centres:
        Cell centre lon/lat, same keys as ``grid_population``.
    grid_size_deg:
        Cell edge length in degrees.  Inferred from the two closest centres if
        omitted.
    suitability:
        Optional per-block relative habitability weight (e.g. residential land
        use fraction).  Defaults to 1.0 for every block.

    Returns
    -------
    dict with keys ``assigned`` (block_id -> population), ``residual``
    (grid population with no block sample) and ``conservation_error``.
    """
    if not blocks or not grid_population:
        return {"assigned": {}, "residual": float(sum(grid_population.values())),
                "conservation_error": 0.0}

    if grid_size_deg is None:
        grid_size_deg = _infer_grid_size(grid_centres)

    half = grid_size_deg / 2.0
    # Anything further than this from every grid centre is treated as outside
    # the grid's coverage rather than snapped to a distant cell.
    max_snap = coverage_radius_cells * grid_size_deg

    # Grid centres are not on a regular lon/lat lattice (WorldMove cells come
    # from a projected grid), so cells are resolved as a nearest-centre
    # Voronoi lookup accelerated by a uniform bucket index.
    buckets: dict[tuple[int, int], list[Any]] = defaultdict(list)
    for gid, (glon, glat) in grid_centres.items():
        buckets[(int(glon / grid_size_deg), int(glat / grid_size_deg))].append(gid)

    search_ring = max(1, int(math.ceil(coverage_radius_cells)))
    offsets = [(dx, dy)
               for dx in range(-search_ring, search_ring + 1)
               for dy in range(-search_ring, search_ring + 1)]

    def cell_of_fast(lon: float, lat: float) -> Any | None:
        bx, by = int(lon / grid_size_deg), int(lat / grid_size_deg)
        best, best_d = None, max_snap ** 2
        for dx, dy in offsets:
            for gid in buckets.get((bx + dx, by + dy), ()):
                glon, glat = grid_centres[gid]
                d = (glon - lon) ** 2 + (glat - lat) ** 2
                if d < best_d:
                    best_d, best = d, gid
        return best

    weights: dict[Any, dict[str, float]] = defaultdict(dict)
    for block in blocks:
        weight = (suitability or {}).get(block.block_id, 1.0)
        if weight <= 0:
            continue
        mass = block.area_m2 * weight

        # Fast path: the block's bounding box fits inside one grid cell, so the
        # whole block belongs to the cell containing its centroid.  Blocks are
        # typically ~100-200 m across against a ~1 km grid, so this covers the
        # large majority and avoids millions of point-in-polygon tests.
        lons = [p[0] for p in block.ring]
        lats = [p[1] for p in block.ring]
        if (max(lons) - min(lons)) < grid_size_deg and (max(lats) - min(lats)) < grid_size_deg:
            gid = cell_of_fast(block.lon, block.lat)
            if gid is not None:
                glon, glat = grid_centres[gid]
                # Confirm the whole bbox lies inside that cell's footprint.
                if (glon - half <= min(lons) and max(lons) <= glon + half
                        and glat - half <= min(lats) and max(lats) <= glat + half):
                    weights[gid][block.block_id] = \
                        weights[gid].get(block.block_id, 0.0) + mass
                    continue

        # Slow path: the block straddles cells, so split its area by the
        # fraction of interior lattice samples falling in each cell.
        samples = _lattice_samples(block, sample_spacing_m, max_samples_per_block)
        counts: dict[Any, int] = defaultdict(int)
        for lon, lat in samples:
            gid = cell_of_fast(lon, lat)
            if gid is not None:
                counts[gid] += 1
        total_hits = sum(counts.values())
        if not total_hits:
            continue
        for gid, hits in counts.items():
            weights[gid][block.block_id] = \
                weights[gid].get(block.block_id, 0.0) + mass * hits / total_hits

    assigned: dict[str, float] = defaultdict(float)
    residual = 0.0
    for gid, pop in grid_population.items():
        share = weights.get(gid)
        if not share:
            residual += float(pop)
            continue
        total = sum(share.values())
        for block_id, w in share.items():
            assigned[block_id] += float(pop) * w / total

    total_in = float(sum(grid_population.values()))
    total_out = float(sum(assigned.values())) + residual
    return {
        "assigned": dict(assigned),
        "residual": residual,
        "conservation_error": abs(total_in - total_out) / max(total_in, 1.0),
    }


def _lattice_samples(block: Block, spacing_m: float, cap: int) -> list[tuple[float, float]]:
    """Interior lattice points of a block, always at least the centroid."""
    kx, ky = local_scale(block.lat)
    lons = [p[0] for p in block.ring]
    lats = [p[1] for p in block.ring]
    dlon = spacing_m / max(kx, 1e-6)
    dlat = spacing_m / ky

    # Coarsen so a very large block never explodes the sample count.
    nx = max(1, int((max(lons) - min(lons)) / dlon))
    ny = max(1, int((max(lats) - min(lats)) / dlat))
    if nx * ny > cap:
        factor = math.sqrt(nx * ny / cap)
        dlon *= factor
        dlat *= factor

    samples: list[tuple[float, float]] = []
    lat = min(lats) + dlat / 2
    while lat < max(lats):
        lon = min(lons) + dlon / 2
        while lon < max(lons):
            if point_in_ring(lon, lat, block.ring):
                samples.append((lon, lat))
            lon += dlon
        lat += dlat
    if not samples:
        samples.append((block.lon, block.lat))
    return samples


def _infer_grid_size(grid_centres: dict[Any, tuple[float, float]]) -> float:
    """Median nearest-neighbour spacing between grid centres, in degrees.

    Uses nearest-neighbour distance rather than the minimum longitude gap:
    WorldMove-style cells come from a projected grid, so their lon/lat centres
    are not on a regular lattice and the minimum gap is meaninglessly small.
    """
    points = list(grid_centres.values())
    if len(points) < 2:
        return 0.01

    # Coarse bucketing on a provisional scale, refined once.
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    span = max(max(lons) - min(lons), max(lats) - min(lats)) or 0.01
    provisional = span / max(1.0, math.sqrt(len(points)))

    buckets: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
    for lon, lat in points:
        buckets[(int(lon / provisional), int(lat / provisional))].append((lon, lat))

    distances: list[float] = []
    for lon, lat in points[: min(len(points), 2000)]:
        bx, by = int(lon / provisional), int(lat / provisional)
        best = float("inf")
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for olon, olat in buckets.get((bx + dx, by + dy), ()):
                    d = (olon - lon) ** 2 + (olat - lat) ** 2
                    if 1e-18 < d < best:
                        best = d
        if best < float("inf"):
            distances.append(math.sqrt(best))

    if not distances:
        return provisional
    distances.sort()
    return distances[len(distances) // 2]


# ────────────────────────────────────────────────────────────────────────────
# District attribution
# ────────────────────────────────────────────────────────────────────────────

def assign_districts(blocks: Sequence[Block], district_geojson: dict) -> int:
    """Point-in-polygon block -> district assignment.

    Deliberately *not* nearest-centroid: municipal districts can be elongated
    and interlocking, so nearest-centroid assignment can misclassify blocks.
    Returns the number of blocks successfully assigned.
    """
    polygons: list[tuple[str, list[list[tuple[float, float]]], tuple[float, float, float, float]]] = []
    for feature in district_geojson.get("features", []):
        props = feature.get("properties") or {}
        name = str(props.get("name") or props.get("adcode") or "")
        geometry = feature.get("geometry") or {}
        rings: list[list[tuple[float, float]]] = []
        if geometry.get("type") == "Polygon":
            rings.append([(p[0], p[1]) for p in geometry["coordinates"][0]])
        elif geometry.get("type") == "MultiPolygon":
            for poly in geometry["coordinates"]:
                rings.append([(p[0], p[1]) for p in poly[0]])
        for ring in rings:
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            polygons.append((name, [ring], (min(xs), min(ys), max(xs), max(ys))))

    hits = 0
    for block in blocks:
        for name, rings, (minx, miny, maxx, maxy) in polygons:
            if not (minx <= block.lon <= maxx and miny <= block.lat <= maxy):
                continue
            if point_in_ring(block.lon, block.lat, rings[0]):
                block.district = name
                hits += 1
                break
    return hits


# ────────────────────────────────────────────────────────────────────────────
# End-to-end convenience entry point
# ────────────────────────────────────────────────────────────────────────────

def blocks_from_geojson(
    roads_path: Path,
    *,
    drop_highways: Iterable[str] = (),
    min_area_m2: float = MIN_BLOCK_AREA_M2,
    max_area_m2: float = MAX_BLOCK_AREA_M2,
) -> tuple[list[Block], RoadGraph, dict]:
    """Read a roads GeoJSON and return (blocks, graph, provenance)."""
    payload = json.loads(Path(roads_path).read_text(encoding="utf-8"))
    features = payload.get("features", [])

    graph = build_road_graph(features, drop_highways=drop_highways)
    nodes_before = graph.node_count()
    prune_dangling(graph)
    faces = extract_faces(graph)
    blocks = build_blocks(graph, faces, min_area_m2=min_area_m2, max_area_m2=max_area_m2)

    provenance = {
        "roads_path": str(roads_path),
        "road_features": len(features),
        "ways_used": graph.ways_used,
        "ways_skipped": graph.ways_skipped,
        "dropped_highway_classes": sorted(drop_highways),
        "nodes_before_prune": nodes_before,
        "nodes_after_prune": graph.node_count(),
        "edges": graph.edge_count(),
        "faces_traversed": len(faces),
        "blocks_kept": len(blocks),
        "min_area_m2": min_area_m2,
        "max_area_m2": max_area_m2,
        "coordinate_reference_system": "WGS84 / EPSG:4326",
        "attribution": "© OpenStreetMap contributors (ODbL 1.0)",
        "caveats": [
            "Grade-separated crossings do not split blocks unless their highway class is dropped.",
            "Blocks are morphological road-enclosed faces, not official administrative boundaries.",
            "Faces touching the extract bounding box are removed by the max-area filter.",
        ],
    }
    return blocks, graph, provenance
