# CESARops Test Lab Fixtures: aircraft-search-grid-v1

## Purpose
This fixture set provides a deterministic, offline testing environment for the Forge Test Lab. It allows the architecture to validate hypothesis proposals and evaluate evidence layers without requiring live web access, real-time satellite imagery downloads, or autonomous cloud execution.

## Why Known Sites Are Used
Evaluating remote-sensing layers requires ground truth. Rather than hunting for missing aircraft, this fixture set uses publicly documented, verified known wreck sites as control fixtures. This ensures deterministic evaluation of algorithms against varied terrain without raising ethical concerns over unlocated crashes or creating standalone detection claims.

## Selected Sites
1. **Sólheimasandur Plane Wreck (Iceland)**: Tests baseline optical recognition on open high-contrast black sand.
2. **Atka Island Liberator (Alaska)**: Tests structural footprint recognition on tundra/grassland.
3. **Gauli Glacier Skytrooper (Switzerland)**: Tests temporal emergence and change detection on snow/ice.
4. **Loon Lake Dragon (Idaho)**: Tests sub-canopy linear disturbance algorithms in dense forest terrain.

## Source-Verification Policy
Every site must achieve `MultiSourceVerified` status from at least two credible public authorities (e.g., National Park Service, National Aviation Authorities). Unverified or contested locations are excluded.

## Ethics Policy
Sites are excluded or flagged for human review if they involve:
* Active crash investigations or recent fatal accidents
* Unrecovered human remains
* Culturally sensitive or military-restricted locations
* Locations where publication could encourage vandalism or unethical visitation

## Control Strategy
Each site is evaluated alongside a matched negative control (e.g., an identical adjacent empty forest or black sand plain) and a confounder control to validate the algorithm's false positive rate.

## Execution Mode
The current executor runs in `DerivedFixtureMetrics` mode, consuming offline, pre-calculated metric data rather than raw satellite bytes, validating the pipeline flow deterministically.

## Metrics
Key metrics evaluated:
* `TargetRankAfter`: Does the algorithm improve the grid weighting of the target?
* `SearchAreaReductionAtFixedRecall`: Does the evidence layer mathematically shrink the search area?
* `EvidenceIndependence`: Is the layer mathematically orthogonal to existing layers?

## Strongest Permitted Claim
The Test Lab strictly enforces bounded claims. The strongest permitted claim is:
*"This method appears to contribute useful evidence toward search-grid prioritization under <conditions>."*
Standalone detection claims ("Aircraft Found") are strictly invalid and rejected by the execution Sandbox.

## Limitations
* Synthetic or derived metrics cannot guarantee live-world execution performance.
* Ethical bounding restricts testing of highly obscure sites.

## Usage Example
To run the full end-to-end fixture execution offline:
```bash
cargo run -p forge-test-lab --example run_aircraft_fixture_v1
```

### Example Output
```
Mission:
  Evaluate whether remote-sensing techniques contribute evidence to aircraft search-grid prioritization.

Sites:
  4 selected, 4 multi-source verified.

Execution mode:
  DerivedFixtureMetrics.

Result:
  Candidate rank improved at 3 of 4 positive sites.
  Negative-control rejection remained 95.0%.
  Independence from existing layers: Partial.

Strongest supported claim:
  This method appears to contribute useful evidence toward search-grid prioritization under verified conditions.

Decision:
  AcceptForHumanReview
```

## Remaining Boundary
Next sprint replaces fixture metrics with one small real imagery-processing test and optionally executes the same bounded contract on AMD ROCm infrastructure.
