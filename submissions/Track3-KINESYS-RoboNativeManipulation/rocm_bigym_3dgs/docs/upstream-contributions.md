# Upstream contributions

This project isolates non-AMD/BiGym delivery-related generic improvements into small upstream PRs. All active branches have removed `agent/` prefixes, and as of 2026-08-06 PR status is checked as open, ready, and mergeable.

## BiGym

| PR | Branch | commit | Change | Local scoped test |
| --- | --- | --- | --- | --- |
| [NeuracoreAI/bigym#61](https://github.com/NeuracoreAI/bigym/pull/61) | `upstream/atomic-demo-save` | `2696412ee5064e53ed02d01f0add15f035886abf` | Demo atomic save | 2 passed |
| [NeuracoreAI/bigym#62](https://github.com/NeuracoreAI/bigym/pull/62) | `upstream/demo-recorder-save-state` | `062aa26fd6c19f42d8bb086ffd8130ce92183a00` | Recorder save state | 2 passed |
| [NeuracoreAI/bigym#63](https://github.com/NeuracoreAI/bigym/pull/63) | `upstream/headless-egl-rendering` | `1eae7b41183789b8db9e25ab61f8849d7c68b75c` | Headless EGL rendering | 4 passed |
| [NeuracoreAI/bigym#64](https://github.com/NeuracoreAI/bigym/pull/64) | `upstream/lazy-demo-loading` | `f7309da8f9bbd18e4141776e0c8bceb316a9c033` | Demo lazy loading | 13 passed |
| [NeuracoreAI/bigym#65](https://github.com/NeuracoreAI/bigym/pull/65) | `upstream/configurable-camera-rendering` | `d665b9536e3155e753d277276c57da51cb2b5086` | Configurable camera FOV and framebuffer | 12 passed |

Legacy PR `#56-#60` auto-closed due cross-repo head branch rename constraints. `#61-#65` share the same commits and are the only active entry points.

## gsplat

| PR | Branch | commit | Change | Local scoped test |
| --- | --- | --- | --- | --- |
| [nerfstudio-project/gsplat#1045](https://github.com/nerfstudio-project/gsplat/pull/1045) | `upstream/rocm-toolkit-probe` | `2e20e3566dd286f59d6df21b0b9364e48e862bc3` | ROCm toolkit probing | 4 passed |
| [nerfstudio-project/gsplat#1046](https://github.com/nerfstudio-project/gsplat/pull/1046) | `upstream/rocm-jit-build-flags` | `337427aeccf0e15c5c798cafd0bc2fd84ccd3bb3` | ROCm JIT build flags | 5 passed |

Legacy PR `#1043-#1044` closed because of same branch-rename constraints. `#1045-#1046` keep original commits and remain current Ready PRs.

## Work branches not yet upstream PRs

- `eust-w/bigym_plus:work/trajectory-audit-recording@da7a86387498a9535a528bd435fc3c6f0a31e735`
- `eust-w/gsplat:work/rocm-gfx1100-runtime@223bc85af4f8a8c3de7eac4fa90645cfc02372b0`
- `eust-w/gsplat:work/rocm-jit-toolkit-detection@059a82ce84952447ff193ddf828fc772f663b083`

## OpenDM inference adapter

| PR | Branch | commit | Change | Validation |
| --- | --- | --- | --- | --- |
| [Kyrie-w8/amd-bigym-3dgs-opendm#1](https://github.com/Kyrie-w8/amd-bigym-3dgs-opendm/pull/1) | `upstream/external-inference-v2` | `394f77f6c321c61e6c3a857728abd651ac09fd13` | Extract shared DM0.5 policy loader and provide protocol v2 `/health` + `/process_frame` services | 10 tests passed in upstream CI locally, master repo probe returned HTTP 200 and `10x16` actions |

This PR was merged upstream on 2026-08-06 into `main` at `8f018b253d0fd2b41a4fa4a87610829eaca74c44`. The contribution head `394f77f6c321c61e6c3a857728abd651ac09fd13` is kept for audit of original changes.

See [phase, repository, branch, and commit ledger](08-repository-revisions.md) for full rename mapping and stage dependencies.
