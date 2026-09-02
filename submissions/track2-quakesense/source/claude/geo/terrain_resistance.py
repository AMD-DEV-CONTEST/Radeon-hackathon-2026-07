"""Pedestrian walking-resistance surface: slope (Tobler's hiking function)
combined with land-cover friction (ESA WorldCover classes), in the same
minimum-cumulative-resistance (MCR) tradition landscape ecology uses for
ecological security patterns (Knaapen, Lankinen & Rijsberman 1992; Yu 1999)
-- a source (here: a departing block), a resistance surface, a sink (here:
a shelter), and a least-cumulative-cost path through the surface, applied to
pedestrian evacuation instead of species movement or ecological flow.

Two independent, individually testable pieces:

* ``speed_factor_from_slope`` / ``resistance_from_slope`` -- Tobler's (1993)
  hiking-function slope penalty, a well-established pedestrian-speed model
  with no land-cover dependence.
* ``LANDCOVER_RESISTANCE`` / ``resistance_from_landcover`` -- a hand-set
  friction table by ESA WorldCover v200 class, the same product already used
  elsewhere in this project for population disaggregation, so no new
  land-cover source is introduced.

``combined_resistance`` multiplies the two into the single per-block
``BlockLayer.resistance`` value the routing/timing code consumes; either
input alone can also be used (e.g. flat terrain with only a land-cover
penalty, or open terrain with only a slope penalty).

Fetching real slope+land-cover values for a city's block centroids
(``fetch_block_resistance``) requires a live Earth Engine connection --
see scripts/fetch_terrain_resistance.py, which must run from a machine with
unrestricted access to Google's IP ranges (this project's cloud GPU server
blocks outbound to googleapis.com; see claude/scripts/test_gee_auth.py).
"""

from __future__ import annotations

import math

#: ESA WorldCover v200 class code -> walking-speed multiplier, in (0, 1].
#: 1.0 = no land-cover penalty (matches free-flow speed exactly); values
#: below 1.0 slow a pedestrian moving off the road network through that
#: cover type; 0.0 is a hand-coded sentinel for "not physically crossable
#: on foot without a built crossing", converted to infinite resistance by
#: ``resistance_from_landcover``.
LANDCOVER_SPEED_FACTOR: dict[int, float] = {
    10: 0.50,   # Tree cover
    20: 0.65,   # Shrubland
    30: 0.85,   # Grassland
    40: 0.75,   # Cropland
    50: 1.00,   # Built-up
    60: 0.90,   # Bare / sparse vegetation
    70: 0.30,   # Snow and ice
    80: 0.00,   # Permanent water bodies -- impassable off-road
    90: 0.30,   # Herbaceous wetland
    95: 0.20,   # Mangroves
    100: 0.60,  # Moss and lichen
}

_UNKNOWN_LANDCOVER_FACTOR = 0.8  # a mild, not-zero penalty for an unmapped/mixed class


def speed_factor_from_slope(slope_percent: float) -> float:
    """Tobler's (1993) hiking-function speed penalty, normalised so flat
    ground (0% slope) returns exactly 1.0.

    ``W = 6 * exp(-3.5 * abs(tan(slope) + 0.05))`` km/h, peaking slightly
    downhill (matching the well-documented empirical asymmetry that a
    gentle downhill grade is walked fastest, not perfectly flat ground);
    both steeper uphill and steeper downhill slow a pedestrian down.
    Returns a value in (0, 1].
    """
    tan_slope = slope_percent / 100.0
    w = 6.0 * math.exp(-3.5 * abs(tan_slope + 0.05))
    w_flat = 6.0 * math.exp(-3.5 * 0.05)
    return w / w_flat


def resistance_from_slope(slope_percent: float) -> float:
    """>= 1.0; inverse of ``speed_factor_from_slope``, or inf at zero speed
    (not reachable for any finite real-world slope, included for symmetry
    with ``resistance_from_landcover``)."""
    factor = speed_factor_from_slope(slope_percent)
    return 1.0 / factor if factor > 0 else math.inf


def resistance_from_landcover(worldcover_class: int) -> float:
    """>= 1.0, or ``inf`` for a class marked impassable off-road (open
    water) in ``LANDCOVER_SPEED_FACTOR``."""
    factor = LANDCOVER_SPEED_FACTOR.get(int(worldcover_class), _UNKNOWN_LANDCOVER_FACTOR)
    return 1.0 / factor if factor > 0 else math.inf


def combined_resistance(slope_percent: float | None, worldcover_class: int | None) -> float:
    """Multiplicative combination of the slope and land-cover terms; a
    missing input contributes no penalty (factor 1.0) rather than being
    treated as a data error, so this degrades gracefully when only one of
    the two rasters is available for a city."""
    r_slope = resistance_from_slope(slope_percent) if slope_percent is not None else 1.0
    r_cover = resistance_from_landcover(worldcover_class) if worldcover_class is not None else 1.0
    if math.isinf(r_slope) or math.isinf(r_cover):
        return math.inf
    return r_slope * r_cover
