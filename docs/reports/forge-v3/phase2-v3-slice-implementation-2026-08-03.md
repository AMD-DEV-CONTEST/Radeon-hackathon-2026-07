# Forge V3 Phase 2 — Vertical Slice Implementation (MissionSpec → Human Review)

Date: 2026-08-03
Branch: forge-v3-integration

## Implemented

- Added V3 demo route:
  - `POST /forge/v3/demo/aircraft-test-lab`
- Added V3 slice handler module:
  - `forge_src/v3_slice.rs`
- Wired real Test Lab crate API usage:
  - `forge_test_lab::worker::TestLabCoordinator::execute_mission`
- Added manifest and hashing dependencies in `forge_Cargo.toml`:
  - `forge-test-lab` (path dependency), `sha2`, `hex`

## Vertical Slice Behavior

Route performs:
1. Admin-safe gate (if `FORGE_ADMIN_PASSWORD` is set).
2. Creates one `mission_id` and one `run_id`.
3. Resolves fixture-backed aircraft mission and executes via Test Lab coordinator.
4. Collects evidence artifacts (`EvidenceReport`, `QualificationDecision`, optional `EvidenceLayerCandidate`).
5. Generates chain-of-custody manifest with stage records and hashes.
6. Writes admin trace record for mission/run correlation.
7. Returns explicit `DerivedFixtureMetrics` disclaimer and final Human Review state.

## Artifact Outputs

- Chain-of-custody manifest:
  - `var/missions/v3/<mission_id>/<run_id>/chain_of_custody_manifest.json`
- Admin trace JSONL:
  - `var/missions/forge_v3_admin_trace.jsonl`
- Evidence artifacts (from Test Lab):
  - `reports/test-lab/aircraft-search-grid-v1/*.json`

## Validation Performed

- `cargo check` for `core/forge-test-lab` passes.
- Syntax/format validation for new module and route wiring performed.

## Known Limitation

The top-level Forge build in this repository currently has large pre-existing compile failures unrelated to this change (missing/legacy dependencies in the broader crate graph). This prevented a full end-to-end server run validation of the new route in this pass.
