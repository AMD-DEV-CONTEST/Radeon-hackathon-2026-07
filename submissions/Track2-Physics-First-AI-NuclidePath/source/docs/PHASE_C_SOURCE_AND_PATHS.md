# Phase C: source terms and heterogeneous paths

The opt-in `source_terms-1.0` contract models boundary forcing without silently
changing units:

- `MaintainedBoundary`: constant boundary value (the legacy maintained-boundary
  behavior remains in `transport.py` and is not changed).
- `FiniteDurationBoundary`: maintained value until `duration_s`, then zero.
- `InstantaneousPulse`: an integrated amount at `time_s`; its `value_at` is zero
  because a Dirac pulse is not a finite concentration.
- `ConstantRateRelease`: rate with optional finite duration.
- `PiecewiseLinearSeries`: strictly increasing time knots and non-negative,
  finite values; interpolation is continuous and integration uses trapezoids.

`convolve_source` provides a causal trapezoidal convolution for regular source
signals. The impulse response and units are owned by the transport model.
Mass is never converted to concentration by this contract: flow, geometry and
dilution must be explicit at the boundary.

`path_network.py` provides frozen `Segment` records and an immutable
`PathNetwork`. Each segment carries its own length, porosity, bulk density,
velocity, dispersion, chemistry, mineralogy and sorption mappings. Networks
are directed and acyclic. Receptors map to known terminal/intermediate
segments and can be expanded with `path_to_receptor`.

Handoff assumptions are explicit in `HandoffAssumptions`: dissolved
concentration continuity, advective-dispersive dissolved flux continuity, and
segment-local equilibrium sorption with no sorbed carryover. These are model
assumptions, not universal physical truths, and must be replaced when a solver
uses a different interface condition.
