"""Carbon label: measured energy -> gCO2e per 1,000 generated tokens -> A..G.

gCO2e/1k tokens = (joules_per_token * 1000 / 3.6e6) kWh * grid intensity.

Grid intensity is a static, documented constant (no live API dependency):
the Radeon Cloud instance used for all runs sits in mainland China
(China Mobile network), so the default is China's 2023 grid average,
571 gCO2e/kWh (Ember Electricity Data Explorer, 2023). Override with
GRID_G_PER_KWH for other regions; the label always reports the factor used.

Bands follow an EU-energy-label-style doubling scale. They are relative
bands for comparing configurations of the same deployment, not an
absolute cross-hardware standard; the README states this.
"""

from __future__ import annotations

import os

GRID_G_PER_KWH = float(os.environ.get("GRID_G_PER_KWH", "571"))
GRID_SOURCE = os.environ.get(
    "GRID_SOURCE", "China grid average 2023, Ember Electricity Data Explorer")

# Upper bound of each band in gCO2e per 1k tokens (doubling scale).
BANDS = [("A", 0.15), ("B", 0.30), ("C", 0.60), ("D", 1.20),
         ("E", 2.50), ("F", 5.00)]  # above the last bound -> "G"


def gco2e_per_1k_tokens(joules_per_token: float) -> float:
    kwh_per_1k = joules_per_token * 1000.0 / 3.6e6
    return kwh_per_1k * GRID_G_PER_KWH


def label(joules_per_token: float) -> str:
    g = gco2e_per_1k_tokens(joules_per_token)
    for name, bound in BANDS:
        if g <= bound:
            return name
    return "G"


def annotate(joules_per_token: float) -> dict:
    """Full carbon annotation for a run; embeds method transparency."""
    return {
        "gco2e_per_1k_tokens": round(gco2e_per_1k_tokens(joules_per_token), 3),
        "label": label(joules_per_token),
        "grid_g_per_kwh": GRID_G_PER_KWH,
        "grid_source": GRID_SOURCE,
    }
