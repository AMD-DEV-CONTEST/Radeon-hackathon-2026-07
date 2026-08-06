# Evidence and current status

This project treats "code exists," "process starts," "artifact parses," "visual pass," "full collection," and "closed-loop success" as distinct evidence layers.

## Evidence layers

| Layer | Can prove | Cannot prove |
| --- | --- | --- |
| Code/configuration | Paths and parameters are implemented | A successful runtime execution |
| Process/logs | Task started and executed to some point | Full artifact completeness |
| Artifact integrity | Files parse, attributes and hashes are valid | Visual quality is acceptable |
| Visual evidence | Specified camera or free-view images can be inspected | Physics, collection, or policy success |
| Trajectory evidence | Transition, frames, and actions are continuous | Task reaches success |
| Evaluation receipt | Provider, model, code, and metrics are traceable | Missing fields for external state |

## Internal evidence entry points

- AMD mainline status: `evidence/amd-rocm-main-status.json`.
- Cross-platform reference summary: `evidence/reference-validation-summary.json`.
- Evaluation/collection evidence guidance: `evaluation/bigym-3dgs/evidence/README.md`.
- Image evidence notes: [images/README.md](images/README.md).
- Video evidence notes: [videos/README.md](videos/README.md).

## Confirmed conclusions

- AMD mainline locks OpenSplat commit, DL3DV revision, and published shell revision.
- Shell import uses visual shell / MuJoCo physics decoupling design and defines Sim(3) alignment boundaries.
- BiGym collection design requires official demo, atomic episodes, complete transitions, and failed-replay isolation.
- Closed-loop evaluation protocol requires real policy requests, continuous action-execution cycles, full trajectories, and provider receipts.
- `cutlery32-dataset.public.json` / `reference-reconstruction.public.json` only reflect cross-platform reference collection/reconstruction status and are under manual visual control; they are not AMD ROCm mainline closed-loop acceptance.
- Reusable upstream changes for BiGym and gsplat are now represented by non-`agent/` branches and submitted as Ready PRs.

## Unconfirmed conclusions

- There is no unified continuous telemetry, so reliable GPU utilization and VRAM usage cannot be claimed for all stages.
- Presence of PLY alone cannot be claimed as free-view visual pass.
- Smoke replays alone cannot claim completion of target number of formal episodes.
- Cross-platform reference results cannot substitute for AMD ROCm mainline acceptance.

## Minimum follow-up evidence requirements

| Stage | Must add |
| --- | --- |
| Reconstruction | ROCm device info, continuous GPU/VRAM telemetry, training logs, final PLY hash, train and free-view rendering |
| Shell import | Sim(3) configuration, static multi-camera images and motion video, foreground/background occlusion, physics-collision regression |
| Collection | LeRobot v3 metadata, episode index, transition range, success/failure list, video-frame alignment |
| Evaluation | Provider `/health`, model and code revision, per-step requests/actions, termination reason, success rate and GPU timeline |
