# Data plane

Git stores public contracts only. The canonical binaries are distributed from
two manually gated Hugging Face dataset repositories:

- [32-episode LeRobot v3 package](https://huggingface.co/datasets/eustance/openSource_AMD_AI_DevMaster_Hackathon_202608), under
  `bigym-3dgs-light-floor-replay-plan-v2-20260802/dishwasher_unload_cutlery_long`;
- [matching 3DGS shell](https://huggingface.co/datasets/eustance/amd-bigym-3dgs-kitchen-shell).

The manifests in this directory lock the source scene, reconstruction, shell
hashes and complete collection hashes. Git never tracks DL3DV source files,
derived PLYs, checkpoints, BiGym demonstrations, real UUIDs or the collected
dataset.

The exact upstream source is
[`4K/90e70328...zip`](https://huggingface.co/datasets/DL3DV/DL3DV-ALL-2K/blob/e035bc5efd8dc5b2fa1e704cb2b1086fd9ec2c5c/4K/90e70328f9196bc78c7e6c695c1e8cbb55a3c961cccf34c566966a5e2d8d8947.zip).
Users must independently obtain access to
[DL3DV/DL3DV-ALL-2K](https://huggingface.co/datasets/DL3DV/DL3DV-ALL-2K)
and accept its current terms.

Private downloads belong under `data/private/`, which Git ignores.

On `main`, these files are immutable cross-platform reference inputs for the AMD
ROCm implementation. The exact verified reference repository state is preserved on
the `reference` branch for historical comparison. A new AMD run must emit its own
receipt and must not overwrite these baseline manifests.
