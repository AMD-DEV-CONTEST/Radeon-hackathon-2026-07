# UI-6 Release Readiness Technical Specification

- Level: S1
- Status: implemented

## Implementation

- Vite injects the package version as a compile-time `__APP_VERSION__` value.
  The frontend renders it in the authenticated shell without exposing build
  paths, secrets, or environment values.
- `scripts/verify_web_release.py` consumes an already-built `web/dist/`
  directory, checks for `index.html` and at least one emitted asset, and prints
  SHA-256 checksums. It never modifies the build output.
- `docs/WEB_RELEASE_RUNBOOK.zh-CN.md` defines the release sequence and makes
  real-model RAG, concurrency, and long-running browser checks explicit
  cloud-only gates.

## Verification

- `npm test`, `npm run build`, and `python scripts/verify_web_release.py`.
- `python scripts/validate_specs.py --strict`.
