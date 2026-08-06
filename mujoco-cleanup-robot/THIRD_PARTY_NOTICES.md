# Third-party software and model notice

This file records the dependencies used by the reproducible competition path.
It is an inventory, not legal advice and not a license grant for this repository.
The repository owner has not yet selected a top-level project license.

## Active TidyBot path

- MuJoCo: Apache-2.0. Used for simulation and contact physics.
- PyTorch and TorchVision: BSD-style licenses. Used for AMD ROCm model
  inference and by the Ultralytics runtime.
- Ultralytics and YOLO11 weights: AGPL-3.0 or a separately purchased
  Ultralytics Enterprise license. The active V9 runtime imports `ultralytics`
  and uses the bundled `final_submission/models/detector/best.pt`. No
  Enterprise entitlement is asserted by this repository.
- Stanford TidyBot assets from MuJoCo Menagerie: model-specific license
  included in the pinned upstream `stanford_tidybot` directory. The assets are
  fetched by sparse checkout and are not redistributed here.

## Distribution requirement

Before publishing or accepting network users, the owner must choose a project
license and resolve the Ultralytics AGPL/Enterprise path while
`YOLO11DepthPerception` remains active.
