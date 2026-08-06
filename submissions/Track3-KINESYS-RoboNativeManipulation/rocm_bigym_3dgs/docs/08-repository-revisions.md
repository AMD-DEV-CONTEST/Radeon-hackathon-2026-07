# Phase, repository, branch, and commit ledger

Last updated: 2026-08-06.

This is the single authoritative ledger for phase-level versioning. `Source branch` means upstream source of a commit; actual runs must use detached HEAD or equivalent lock with full SHA and must not drift with branch head.

## Stage version matrix

| Stage | Repo/resource | Source branch or revision | Execution commit/lock value | Role |
| --- | --- | --- | --- | --- |
| End-to-end orchestration | `eust-w/amd-bigym-3dgs-rocm` | `main` | `f66b9150ca7cfd48746147dfa8326a2657ab309e` | Baseline of this audit run |
| Documentation release | `eust-w/amd-bigym-3dgs-rocm` | `docs/pipeline-provenance` | Created from `f66b9150ca7cfd48746147dfa8326a2657ab309e` | Documentation and version-governance updates |
| AMD 3D reconstruction | `pierotofy/OpenSplat` | `main` | `9fb62fde8b7b8c416121d3cbdcda278ffd9682f7` | ROCm reconstruction engine |
| AMD 3D reconstruction | `DL3DV/DL3DV-ALL-2K` | Hugging Face revision | `e035bc5efd8dc5b2fa1e704cb2b1086fd9ec2c5c` | Input data |
| AMD 3D reconstruction | Project OpenSplat patches | Locked with this `main` baseline | Two `reconstruction/patches/opensplat-*.patch` | ROCm build adaptation |
| Reference reconstruction | `eust-w/amd-bigym-3dgs-rocm` | `reference` | `b35e318f4dfcfabaaeedd8347c6101384cd7c14d` | Cross-platform comparison orchestration |
| Reference reconstruction | `nerfstudio-project/gsplat` | `main` | `4d3a3b69db4de0326f983ccf7b7b255271a17b01` | Cross-platform comparison reconstruction/rendering |
| Reference integration | `discoverse-dev/DISCOVERSE` | `main` | `d67f47c084aba0e0cf422a8725235f8b9238655a` | Reference runtime |
| Shell publish/import | `eustance/amd-bigym-3dgs-kitchen-shell` | Hugging Face revision | `amd-rocm-w7900d-20260804` | Gaussian shell assets |
| Shell import/collection | `NeuracoreAI/bigym` | `master` | `14beb30318ad14c5d6723175c2ee2281129792af` | BiGym baseline |
| Shell import/collection | Project BiGym overlay | Locked with this `main` baseline | `patches/bigym-3dgs-shell-and-collector.patch` | 3DGS, camera, and collection integration |
| Closed-loop evaluation | `WuChao-2024/bigym_plus` | `master` | `d12937686833467b5013ac47a834cf4b6f5a9d53` | Evaluation client baseline |
| External inference OpenDM | `Kyrie-w8/amd-bigym-3dgs-opendm` | `main` | `8f018b253d0fd2b41a4fa4a87610829eaca74c44` | HTTP v2 provider; PR `#1` merged, valid OpenDM provider execution lock |
| Historical inference implementation | `eust-w/amd-bigym-3dgs-rocm` | `interence` | `eb1bdf844a20f02b2fcb419fa1d33ed4db06484f` | Trace-only, not current mainline dependency |

## Upstream contribution branches

These branches are for independent changes contributed upstream; they are not execution versions. Actual runs still follow the stage version matrix.

| fork | Current branch | commit | Upstream PR |
| --- | --- | --- | --- |
| `eust-w/bigym_plus` | `upstream/atomic-demo-save` | `2696412ee5064e53ed02d01f0add15f035886abf` | `NeuracoreAI/bigym#61` |
| `eust-w/bigym_plus` | `upstream/demo-recorder-save-state` | `062aa26fd6c19f42d8bb086ffd8130ce92183a00` | `NeuracoreAI/bigym#62` |
| `eust-w/bigym_plus` | `upstream/headless-egl-rendering` | `1eae7b41183789b8db9e25ab61f8849d7c68b75c` | `NeuracoreAI/bigym#63` |
| `eust-w/bigym_plus` | `upstream/lazy-demo-loading` | `f7309da8f9bbd18e4141776e0c8bceb316a9c033` | `NeuracoreAI/bigym#64` |
| `eust-w/bigym_plus` | `upstream/configurable-camera-rendering` | `d665b9536e3155e753d277276c57da51cb2b5086` | `NeuracoreAI/bigym#65` |
| `eust-w/gsplat` | `upstream/rocm-toolkit-probe` | `2e20e3566dd286f59d6df21b0b9364e48e862bc3` | `nerfstudio-project/gsplat#1045` |
| `eust-w/gsplat` | `upstream/rocm-jit-build-flags` | `337427aeccf0e15c5c798cafd0bc2fd84ccd3bb3` | `nerfstudio-project/gsplat#1046` |
| `eust-w/amd-bigym-3dgs-opendm` | `upstream/external-inference-v2` | `394f77f6c321c61e6c3a857728abd651ac09fd13` | `Kyrie-w8/amd-bigym-3dgs-opendm#1` |

## Work branches

| fork | Current branch | commit | Status |
| --- | --- | --- | --- |
| `eust-w/bigym_plus` | `work/trajectory-audit-recording` | `da7a86387498a9535a528bd435fc3c6f0a31e735` | Not submitted as independent upstream PR |
| `eust-w/gsplat` | `work/rocm-gfx1100-runtime` | `223bc85af4f8a8c3de7eac4fa90645cfc02372b0` | Project work branch |
| `eust-w/gsplat` | `work/rocm-jit-toolkit-detection` | `059a82ce84952447ff193ddf828fc772f663b083` | Project work branch |

## `agent/*` rename records

GitHub does not auto-migrate renamed head refs across fork PRs. To keep commit history intact and remove `agent/` prefixes, legacy PRs were closed and new Ready PRs were created from the same commits.

| Repo | Old branch/PR | New branch/PR | commit |
| --- | --- | --- | --- |
| `eust-w/bigym_plus` | `agent/atomic-demo-save`, BiGym `#56` | `upstream/atomic-demo-save`, BiGym `#61` | `2696412ee5064e53ed02d01f0add15f035886abf` |
| `eust-w/bigym_plus` | `agent/demo-recorder-save-state`, BiGym `#57` | `upstream/demo-recorder-save-state`, BiGym `#62` | `062aa26fd6c19f42d8bb086ffd8130ce92183a00` |
| `eust-w/bigym_plus` | `agent/headless-egl-rendering`, BiGym `#58` | `upstream/headless-egl-rendering`, BiGym `#63` | `1eae7b41183789b8db9e25ab61f8849d7c68b75c` |
| `eust-w/bigym_plus` | `agent/lazy-demo-loading`, BiGym `#59` | `upstream/lazy-demo-loading`, BiGym `#64` | `f7309da8f9bbd18e4141776e0c8bceb316a9c033` |
| `eust-w/bigym_plus` | `agent/configurable-camera-rendering`, BiGym `#60` | `upstream/configurable-camera-rendering`, BiGym `#65` | `d665b9536e3155e753d277276c57da51cb2b5086` |
| `eust-w/bigym_plus` | `agent/trajectory-audit-recording` | `work/trajectory-audit-recording` | `da7a86387498a9535a528bd435fc3c6f0a31e735` |
| `eust-w/gsplat` | `agent/rocm-toolkit-probe-upstream`, gsplat `#1043` | `upstream/rocm-toolkit-probe`, gsplat `#1045` | `2e20e3566dd286f59d6df21b0b9364e48e862bc3` |
| `eust-w/gsplat` | `agent/rocm-jit-build-flags`, gsplat `#1044` | `upstream/rocm-jit-build-flags`, gsplat `#1046` | `337427aeccf0e15c5c798cafd0bc2fd84ccd3bb3` |
| `eust-w/gsplat` | `agent/rocm-gfx1100-runtime` | `work/rocm-gfx1100-runtime` | `223bc85af4f8a8c3de7eac4fa90645cfc02372b0` |
| `eust-w/gsplat` | `agent/rocm-jit-toolkit-detection` | `work/rocm-jit-toolkit-detection` | `059a82ce84952447ff193ddf828fc772f663b083` |

This project's six local historical branches were also renamed from `agent/*` to `archive/*`; they were not pushed remotely and therefore are not part of executable dependencies in the phase matrix. Remote `eust-w/amd-bigym-3dgs-rocm` did not have effective `agent/*` branches. Legacy local tracking ref `origin/agent/full-evaluation-recording` has been removed.

## Version update process

1. Update this ledger with full SHA first, then update phase documents with commit summaries.
2. Record `git remote get-url origin`, `git branch --show-current`, and `git rev-parse HEAD` in the evaluation receipt.
3. Do not move phase locks silently when upstream branch HEAD changes; rerun corresponding phase acceptance.
4. When evaluator provider is outside the fixed matrix, supplement the same fields in the one evaluation receipt.
