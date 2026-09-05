# Contributing

## Workflow

1. Follow the [working protocol](docs/00-meta/working-protocol.md) for non-trivial work and read the durable owner documents for the files being changed.
2. Identify the canonical owner through the [documentation index](docs/README.md) before changing product, architecture, unit, or runtime truth.
3. Load [implementation taste](docs/00-meta/implementation-taste.md) only for non-trivial code changes that shape boundaries, data, authority, naming, abstraction, or complexity.
4. Keep changes explicit and local to the owning surface. Update durable docs when a verified contract, guarantee, operation, or recovery path changes.

## Development Commands

- Python `3.14.2` is the project and packaged runtime.
- `pdm install` installs project dependencies.
- `pdm run dev` runs the desktop application.
- `pdm run test` runs the curated acceptance portfolio in one process.
- `pdm run pytest --direct <pytest selectors/options>` runs a focused selection
  with the same isolated temporary-path setup.
- `pdm run lint` runs Ruff over source, tests, scripts, and benchmarks.
- `pdm run typecheck` runs the strict Mypy slice over typed boundary modules.
- `pdm run check` regenerates/checks Agent Skills, runs Ruff and Mypy, validates
  the native OCR lock, then compiles the Python tree.
- `pdm run i18n-extract` and `pdm run i18n-compile` update Qt translations.
- `pdm run package` builds the Windows bundle.
- `pdm run smoke-package` verifies the packaged executable.
- `pdm run velopack` creates a local Windows installer after package smoke.
- `pdm run dist` creates a ZIP from the packaged bundle.

Use the smallest verification set that proves the affected contract. Run `pdm run test` and `pdm run check` when the change has repository-wide or uncertain impact.

## Change-Specific Review

- UI changes follow the nearest local UI guidance. Cross-unit interaction or authority changes are reviewed against
  [Product TDD](docs/20-product-tdd/README.md).
- Storage changes are reviewed against [Storage Ownership](docs/20-product-tdd/storage-ownership.md); migrations also follow [Local State Evolution](docs/40-deployment/local-state-evolution.md).
- Runtime changes use the [Deployment index](docs/40-deployment/README.md); packaging changes follow [Packaging](docs/40-deployment/packaging.md) and the packaged smoke gate.
- New cross-unit ML states or result semantics update the
  [ML Task Lifecycle](docs/20-product-tdd/ml-task-lifecycle.md); runtime locations
  remain Deployment or source truth.

## Testing Intent

- Avoid adding a narrow regression test for every fixed bug. A past failure is evidence to inspect the durable contract, not by itself a reason to preserve a tiny test forever.
- Prefer a small acceptance portfolio around irreplaceable business outcomes,
  irreversible data risks, migration compatibility, and a few critical
  cross-boundary workflows.
- Use typed boundary models, mature library guarantees, static analysis, packaged
  smoke, and clear ownership before adding lower-level behavioral cases.
- Do not add tests that restate source definitions, type/schema constraints,
  enum membership, library behavior, defensive branches, widget structure, or
  incidental implementation details.
