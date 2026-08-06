# Reuse Manifest V1

Reuse Manifest V1 is the mandatory Reuse-or-Justify gate for Workstream 02. It
catalogs mature upstream implementations before any project-owned module can be
written, patched, or admitted to a Radeon execution path.

## Catalog scope

The frozen catalog contains 28 official GitHub repositories across model,
training, agent, image, video, super-resolution, segmentation, OCR, audio,
evaluation, and marketing-agent directories. The 21 explicitly required pins
cover FLUX.2, Wan2.2, LTX-Video, SeedVR2, Real-ESRGAN, SwinIR, Grounding DINO,
SAM2.1, SigLIP2, CLAP, ms-swift, PEFT, TRL, LangGraph, Agent-R1, MATPO, MARTI,
OPSD, TCOD, rCM, and Causal Forcing.

Each entry records:

- official repository and immutable 40-character commit;
- normalized observation time and latest observed push time;
- source-code SPDX identifier and exact license locator;
- categories, intended adapter/wrapper/workflow/reference integration;
- import roots, hardware assumptions, CUDA-only components, and ROCm candidates;
- separate source-license approval, ROCm evidence, and executable-admission state.

Source-code licensing never grants model-weight, dataset, font, audio, or output
rights. Those remain under the Supply Chain V3 gates. OPSD is blocked because a
source license was not resolved. AutoGen is cataloged but blocked pending a
software-license suitability review. Neither may enter executable adapters.

## Radeon truth boundary

All 28 entries currently have `rocm_evidence_level=untested`. A project may not
be marked executable merely because its Python code imports, its repository is
reachable, or its README mentions a generic GPU. Executable admission requires:

1. approved source-code license;
2. non-archived frozen repository revision;
3. an observed receipt from that exact revision on the target Radeon/ROCm
   environment.

Consequently, the current executable-admission count is zero. CUDA-only and
ROCm-candidate lists are planning observations, not compatibility claims.

## Integration and patch governance

All upstream calls must resolve through a revision-bound `AdapterRegistry`.
Unmediated imports can be scanned mechanically. Project-owned changes live only
under `upstream_patches/` and require the upstream issue/PR, patch hash,
rationale, named regression tests, parity cases, and rollback revision. The
current patch registry is intentionally empty; no patch is claimed.

Replacement requires same-case parity and deterministic rollback. Maintenance
health combines archive state, freshness, license resolution, revision
resolution, and runtime smoke. A low score activates a frozen fallback instead
of silently switching implementations.

Wheel-vs-source-build decisions require successful observations from the same
environment. The mechanical fixture demonstrates the decision contract with
synthetic rows but does not claim real build speed or memory. Duplicate-code
scanning fingerprints equal Python function bodies. Every original module must
record evaluated upstream candidates and a falsifiable benefit; a suitable
candidate automatically blocks a convenient rebuild.

## Reproduce

```bash
PYTHONPATH=src .venv/bin/python scripts/build_v10_reuse_manifest.py
PYTHONPATH=src .venv/bin/python -m unittest tests.test_v10_reuse_governance -v
PYTHONPATH=src .venv/bin/python scripts/run_v10_upstream_smoke.py --project-id flux2
```

The final command is secret-free and defaults to a contract preflight. Add
`--network-head-check` only to observe current repository reachability and HEAD;
HEAD drift is reported and never rewrites the frozen commit. Neither mode is a
runtime or Radeon smoke.

Machine-readable artifacts:

- `config/cortex_x_v10_reuse_manifest_v1.json`
- `evidence/v10/reuse-manifest-v1-mechanical-fixture.json`
- `upstream_patches/manifest.json`

