---
license: cc-by-4.0
task_categories:
  - robotics
tags:
  - lerobot
  - robotics
  - imitation-learning
  - vision-language-action
  - amd-rocm
  - genesis
---

# RadeonVLA-Reflex Physical-2K Dataset Card

> Release status: public, strictly validated, and fixed to an immutable Hub revision.

## Overview

- Dataset name: RadeonVLA-Reflex Physical-2K
- Version: `2779b7c5566df9072bb9a7c43335d6203ea97887`
- Generator commits: `dbc12b69e88be787b679bb41cf2026ca43e0eda6`, `cbf07f9306cd175e82d1e60d1c02cc0b07d2f9d2`
- Genesis version: 1.1.2
- LeRobot version: 0.6.0
- License: CC BY 4.0
- Public URL: https://huggingface.co/datasets/a3124371940/radeonvla_reflex_physical_2k
- Dataset revision: `2779b7c5566df9072bb9a7c43335d6203ea97887`
- Verified size: 2,000 episodes / 468,889 frames / 2,000 strict certificates

## Download and validate

From the project directory, download the immutable public revision and run the strict validator:

```bash
python -m radeonvla.download_artifacts --artifact physical-2k
python -m radeonvla.validate_dataset \
  --repo-id a3124371940/radeonvla_reflex_physical_2k \
  --dataset-root datasets/radeonvla_reflex_physical_2k \
  --expected-episodes 2000 --episodes-per-task 100 --require-strict-physics
```

## Task coverage

The primary L1 dataset has 20 variations: five fruits × four bowl positions.

| Fruit | Bowl positions | Training target | Validation | Held-out evaluation |
|---|---|---:|---:|---:|
| banana | white-left, blue-left, white-right, blue-right | 100 each | disjoint seeds | 5 each |
| lemon | white-left, blue-left, white-right, blue-right | 100 each | disjoint seeds | 5 each |
| plum | white-left, blue-left, white-right, blue-right | 100 each | disjoint seeds | 5 each |
| apple | white-left, blue-left, white-right, blue-right | 100 each | disjoint seeds | 5 each |
| orange | white-left, blue-left, white-right, blue-right | 100 each | disjoint seeds | 5 each |

The release table is generated from the immutable dataset manifest. L2–L4 data are
reported separately and are not implied by the primary L1 total.

## Frame schema

| Field | Shape/type | Description |
|---|---|---|
| observation.images.world | (240, 320, 3) uint8 | World RGB camera |
| observation.images.wrist | (240, 320, 3) uint8 | Wrist RGB camera |
| observation.state | (9,) float32 | Ordered robot and gripper qpos |
| action | (9,) float32 | Absolute joint-position target |
| task | string | Natural-language instruction |
| timestamp | float | Episode time (dataset metadata) |
| episode_index | integer | Episode identifier |
| frame_index | integer | Frame within episode |
| seed | integer | Reset seed in the external per-episode certificate |
| success | boolean | Strict success verdict in the per-episode certificate |

`seed` and `success` are not tensor columns in the LeRobot frame schema. They live in
`certificates/episode_XXXXXX.json`, one atomic certificate for each committed episode.

## Action protocol

- Action type: absolute_joint_position
- Joint names and order: panda_joint1..7, panda_finger_joint1..2
- Dimension: 9
- Joint unit: radians (arm), meters (fingers)
- Gripper convention and range: [0.0, 0.04], open=0.04, closed=0.0
- Control frequency: 20 Hz dataset (sim 100 Hz, decimated)

## Data generation

Data collection uses the scripted multi-goal expert (`python -m radeonvla.record_dataset`):

1. expert states follow resolved L1–L4 goals after scene randomization;
2. success requires every fruit center to finish inside the inner bowl footprint after
   at least 60 simulation settle steps;
3. pose jitter is non-overlapping; optional appearance/physics DR flags are supported;
4. recording rate is 20 Hz (sim 100 Hz, decimated);
5. formal collection disables kinematic attachment, placement nudges, and off-table
   respawns; a context guard aborts any rigid-body pose write during the episode;
6. failed episodes are discarded and are not part of Physical-2K;
7. `validate_dataset` checks schema, non-finite values, image statistics, exact 20×100
   coverage, unique seeds, zero interventions, and certificate/episode correspondence;
8. camera videos under `datasets/*/videos/` are spot-checked before training;
9. Recording happens under `.inprogress`; the target path is replaced only after finalize,
   coverage checks, and a successful LeRobot reopen.
10. `--resume-incomplete` reconstructs saved counts from LeRobot metadata and reconciles
    the two-phase episode certificates before appending with a fresh seed.

## Split policy

- Strict smoke seeds: 12000–12999
- Training source seed ranges: 21000–26999 and 71000–76039
- Validation seeds: 40000–40999
- Formal 100-rollout evaluation seeds: 52000–52099
- Interruption/recovery seeds: 60000–60999

No seed may occur in more than one split.

## Quality checks

- no black or corrupt images;
- state and action match the frozen schema;
- no NaN or infinity;
- task, object, and container agree;
- episode success is independently verified;
- random replay videos were manually inspected.
- final validator result: `errors=[]`, `warnings=[]` across 2,000 certificates.

## Assets and limitations

Robot and YCB meshes are populated via `setup_assets` (see `assets/README.md` and
`THIRD_PARTY_NOTICES.md`). The YCB data portal publishes the object models under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); this release preserves that
license, credits the YCB authors, and notes that blue bowl appearance is applied at scene
build time. The Franka MJCF bundled by Genesis carries Apache-2.0 terms.

This dataset is simulation-only; object and language coverage are limited to the
registered fruit/bowl suite. Episode counts, frame counts, source revision, and checksums
are bound to the published card and immutable revision after the 2,000-episode validator passes.

## YCB attribution

Berk Calli, Aaron Walsman, Arjun Singh, Siddhartha Srinivasa, Pieter Abbeel, and
Aaron M. Dollar, “The YCB Object and Model Set: Towards Common Benchmarks for
Manipulation Research,” ICAR 2015. Source: https://www.ycbbenchmarks.com/ and
https://ycb-benchmarks.s3-website-us-east-1.amazonaws.com/.
