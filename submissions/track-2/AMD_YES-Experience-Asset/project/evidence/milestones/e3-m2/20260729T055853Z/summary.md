# E3 / M2 Critical Moment Map evidence

Result: `E3_LOCAL_VERTICAL_SLICE_READY_FOR_REVIEW`

Implementation commit `6018657fb0fe667c6c28a5817c808d3466f92c1a` delivers the
M2 vertical slice tracked by
[#19](https://github.com/kinnyuww/amd-devmaster-track2-agent/issues/19).

## Demonstrated behavior

- An accepted M1 version generates a source-linked Critical Moment Map.
- Source-supported temporal phrases are marked `KNOWN`; absent timing remains
  `MISSING`; only an explicit structured M1 conflict group becomes
  `CONFLICTING`. No date is invented.
- M2 create, edit, confirmation, history and canonical ExperienceAsset
  projection persist across restart through one dual-CAS SQLite transaction.
- Title-only autosave preserves in-flight edits, rebases only locally edited
  moments after a 409, and blocks automatic retries when M1 invalidates the map.
- Related M1 corrections and clarification resolutions atomically invalidate
  dependent M2 artifacts. Unrelated M1 edits leave M2 current.
- Every exposed M2 generation run ID resolves to a durable local run.

## Reproduction result

- backend: 121/121 tests and Ruff PASS;
- public QA: 32/32 and contract gate PASS;
- frontend: 106/106 tests, typecheck, ESLint, production build and 15/15
  contract provenance checks PASS;
- contract export: idempotent;
- live loopback FastAPI/React browser path: PASS.

The screenshot and JSON artifacts use only a synthetic public chair-selection
scenario. The correction trace shows both canonical `M2=INVALIDATED` state and
the immutable invalidated M2 successor.

## Decision boundary

This packet is local evidence for independent E3 review. It is not a
quality-owner acceptance, merge authorization, new W7900/ROCm/vLLM benchmark,
or performance claim. E3 retains the already accepted E1/E2 local-serving
boundary and does not change the core model path.
