# Parameter Provenance

## Classification policy

Every parameter is labelled as one of:

1. **site-specific measurement** — tied to site, method, date and uncertainty;
2. **literature constant/default** — sourced but not site truth;
3. **derived value** — calculated from declared inputs;
4. **demonstration value/range** — selected to expose behaviour;
5. **calibrated value** — fitted to data and independently checked.

The bundled case contains **no site-specific measurements**. “Plausible demonstration scenario” is the correct interpretation.

## Bundled baseline

| Parameter | Value | Unit | Classification | Basis and caution |
|---|---:|---|---|---|
| constant source concentration `C0` | 1,000,000 | Bq/m³ | demonstration | readable relative breakthrough plots; not an inventory |
| monitoring distance | 100 | m | demonstration | hypothetical receptor point |
| Cs Kd | 0.2 | m³/kg | low-end literature-informed demo | 200 L/kg; within low-end IAEA/PNNL brackets, not universal |
| dry bulk density | 1700 | kg/m³ | literature-style default | internally coherent with `n=0.35` and mineral particle density ~2615 kg/m³ |
| porosity | 0.35 | fraction | literature-style default | plausible for granular media; total/effective/water-filled porosity must be distinguished on site |
| pore-water velocity | 1e-5 | m/s | demonstration within realistic range | 0.864 m/day; high end for granular aquifers |
| dispersion coefficient | 1e-5 | m²/s | demonstration | with `v=1e-5`, longitudinal dispersivity `alpha_L=D/v=1 m` |
| dissolved K+ | 20 | mg/L | elevated demonstration | above ordinary 0–10 mg/L freshwater sensitivity bracket but possible with context |
| competition coefficient | 0.01 | L/mg | demonstration only | uncalibrated empirical coefficient; gives 16.7% Kd reduction at 20 mg/L |
| Cs-137 half-life | 30.018 | years | physical literature constant | DDEP 2024 recommendation, uncertainty ±0.022 y |

## Kd

IAEA TECDOC-2095 reports that Cs Kd varies by several orders of magnitude and should be conditioned on texture, organic matter, elapsed time, radiocaesium interception potential (RIP) and potassium in solution. Indicative IAEA geometric means and 5th–95th percentiles include:

| Group | Geometric mean | 5th–95th percentile |
|---|---:|---:|
| all soils, no information | 2,500 L/kg | 50–63,000 L/kg |
| short-term | 1,600 L/kg | 40–22,000 L/kg |
| sand, short-term | 1,400 L/kg | 56–11,000 L/kg |
| clay + loam, short-term | 3,900 L/kg | 590–26,000 L/kg |
| organic, short-term | 89 L/kg | 13–1,900 L/kg |

The bundled `200 L/kg` value is a low-end mobility-oriented demonstration value. PNNL-16531 contains a 200–5,000 mL/g Hanford water-borne bracket; that site-specific context must not be generalized to all soils.

## Porosity and density

Groundwater Project ranges include approximately:

- fine sand: `0.26–0.50`;
- coarse sand: `0.30–0.45`;
- sand and gravel: `0.20–0.30`;
- silt: `0.35–0.50`;
- clay: `0.45–0.55`.

For mineral particles near `2650 kg/m³`, `rho_b=(1−n)rho_p`; the bundled pair `rho_b=1700 kg/m³`, `n=0.35` implies `rho_p≈2615 kg/m³`.

## Velocity and dispersion

`groundwater_velocity_m_s` is the pore-water velocity:

```text
v = q / n_e = K i / n_e
```

It is not Darcy flux `q`. At shallow depth, order-of-magnitude pore velocities cited by the Groundwater Project are roughly `0.01–1 m/day` for granular aquifers, with much higher values possible in fractured rock and karst.

Use:

```text
D_L = alpha_L v + D_e
```

Dispersivity is scale-dependent. The baseline `alpha_L≈1 m` is compatible with field examples near 100–250 m scale; it is still not a site calibration.

## Potassium competition

The empirical closure is:

```text
Kd_eff = Kd / (1 + beta [K+])
```

It is used only for directionally transparent sensitivity. IAEA TECDOC-2095 recommends conditioning reversible Cs Kd on `RIP/Kss`, reflecting mineralogy and solution potassium. A credible beta requires experiments at controlled K+, ionic strength and mineralogy plus held-out validation.

**Double-counting warning:** do not apply the K+ correction when the supplied site Kd was already measured at the same ambient K+ chemistry unless the calibration explicitly supports it.

## Machine validation ranges

The contract enforces:

- source concentration `>0`;
- distance and times `>=0`;
- Kd `>=0`;
- density, velocity, dispersion and half-life `>0`;
- porosity in `(0,1]`;
- K+ and competition coefficient `>=0`;
- finite non-boolean numerical values only.

## Sources

- IAEA TECDOC-2095: <https://www.iaea.org/publications/15878/distribution-coefficients-for-soil-freshwater-and-marine-systems-for-exposure-assessments>
- EPA Kd guidance: <https://www.epa.gov/radiation/understanding-variation-partition-coefficient-kd-values>
- PNNL-16531: <https://www.pnnl.gov/main/publications/external/technical_reports/PNNL-16531.pdf>
- Groundwater Project, porosity: <https://books.gw-project.org/hydrogeologic-properties-of-earth-materials-and-principles-of-groundwater-flow/chapter/total-porosity/>
- USGS WSP 2220, Darcy versus pore velocity: <https://pubs.usgs.gov/wsp/2220/report.pdf>
- Gelhar, Welty & Rehfeldt (1992), field-scale dispersivity: <https://doi.org/10.1029/92WR00607>
- WHO, potassium in drinking water: <https://iris.who.int/bitstreams/ab162681-e9bc-4392-9aef-2c934cea2b5c/download>
- Leblond et al. (2024), Cs-137 half-life: <https://pubmed.ncbi.nlm.nih.gov/38290201/>
