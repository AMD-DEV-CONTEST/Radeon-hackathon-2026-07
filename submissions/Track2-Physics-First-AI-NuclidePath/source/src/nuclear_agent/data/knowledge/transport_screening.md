# One-dimensional reactive advection–dispersion screening

The deterministic tool evaluates a reactive Ogata–Banks analytical solution on a homogeneous saturated semi-infinite domain. A constant dissolved Cs-137 concentration is imposed at `x=0`; the initial concentration is zero for `x>0`. Retardation is `R = 1 + rho_b Kd_eff / porosity`, pore-water travel time is marked by `xR/v`, and radioactive decay acts in dissolved and sorbed phases.

This explicit source condition replaces an undefined Gaussian pulse. It still omits finite source duration and depletion, heterogeneous stratigraphy, transient flow, nonlinear or kinetic sorption, colloids, preferential pathways, matrix diffusion and daughter products. Concentration predictions require site calibration and external validation before site-specific interpretation.

Input classifications:

- literature constants/defaults are cited but are not site data;
- demonstration values expose software behaviour;
- site-specific values require provenance, method, date and uncertainty.

Source: Ogata & Banks, USGS Professional Paper 411-A: https://pubs.usgs.gov/pp/0411a/report.pdf
