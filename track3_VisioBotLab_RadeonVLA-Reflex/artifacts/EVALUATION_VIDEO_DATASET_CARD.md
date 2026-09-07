---
pretty_name: RadeonVLA-Reflex Evaluation Videos
license: apache-2.0
task_categories:
- robotics
tags:
- robotics
- physical-ai
- vision-language-action
- rocm
- amd-radeon
---

# RadeonVLA-Reflex evaluation videos

This repository is the public video-and-evidence companion for **RadeonVLA-Reflex**, a Track 3 Physical AI submission by VisioBot Lab. It keeps videos beside the machine-readable results and hashes used to describe them.

## Linked releases

- Physical-1K: [`a3124371940/radeonvla_reflex_physical_1k`](https://huggingface.co/datasets/a3124371940/radeonvla_reflex_physical_1k), revision `b0f72c60e9100739fd82bd498c8f3d9bed7b75af`
- Physical-2K: [`a3124371940/radeonvla_reflex_physical_2k`](https://huggingface.co/datasets/a3124371940/radeonvla_reflex_physical_2k), revision `2779b7c5566df9072bb9a7c43335d6203ea97887`
- Primary 20K model: [`a3124371940/radeonvla_reflex_smolvla_1k`](https://huggingface.co/a3124371940/radeonvla_reflex_smolvla_1k), revision `abcca9f2b313e378b554449016b520b8117016fe`
- 50K model: [`a3124371940/radeonvla_reflex_smolvla_1k_50k`](https://huggingface.co/a3124371940/radeonvla_reflex_smolvla_1k_50k), revision `59f6f0ad720054505667a652fe07e03d65e82915`
- 200K model: [`a3124371940/radeonvla_reflex_smolvla_2k_200k`](https://huggingface.co/a3124371940/radeonvla_reflex_smolvla_2k_200k), revision `1ea32da3d59ce0905d0f1331bc3c6643e42beb7e`

## What is included

| Path | Scope |
|---|---|
| `videos/policy_success_20k/` | Release-verified 20K first-attempt successes for banana and lemon |
| `videos/policy_success_20k_world/` | Single-panel derivatives of both verified 20K policy successes |
| `videos/data_collection/` | Successful strict-physics Physical-2K collection episodes for apple, banana, and plum |
| `videos/task_success_world/` | One certified Physical-2K success for each of the 20 fruit-and-destination tasks |
| `videos/walkthrough/radeonvla_reflex_3min.mp4` | 200-second English walkthrough with bilingual captions and successful footage only |
| `evidence/policy_success_20k/banana/` | Standard one-episode JSON, CSV, and summary for scene/episode seed `53001` |
| `evidence/policy_success_20k/lemon/` | Replay-probe JSON with scene seed `54000` and episode seed `54006` recorded separately |
| `evidence/formal100/` | Formal 100-rollout JSON and CSV evidence |
| `evidence/world_success_examples.json` | Task, episode, seed, source timestamps, checksums, and certificate provenance for all 20 examples |
| `SHA256SUMS` | Content hashes for every uploaded payload file |

## Formal result boundary

The released 100-rollout benchmark contains 20 tasks × 5 disjoint seeds:

- Learned-policy first-attempt success: **36/100**
- Explicit strict-physics Precision-Reflex contribution: **+55/100**
- Final system success: **91/100**
- P50 / P95 policy inference latency: **4.54 / 37.27 ms**

The representative clips are a replay library, not the benchmark denominator. Aggregate results remain tied to `evidence/formal100/evaluation.json` and its CSV companion. The twenty clips under `task_success_world/` are certified Physical-2K collection trajectories; they provide one successful visual example for every task but are not presented as policy-evaluation rollouts.

## Video acceptance boundary

Every policy video in this repository passes a release-specific gate: the target fruit is inside the requested bowl, both the commanded and measured gripper positions are open, and the result remains valid after two additional seconds of physical simulation. The banana replay is a standard fixed-seed evaluation. The lemon replay records its fixed scene seed (`54000`) and episode seed (`54006`) separately because the scene was initialized once for that evaluation batch. Collection clips likewise show the full release and settled ending. The 20-task manifest binds each clip to its strict-physics certificate, zero kinematic interventions, exact source interval, and SHA256. Object pose teleportation, grasp glue, and post-hoc placement correction remain forbidden.

## Language

Commands use the exact collected-language instruction source. The long walkthrough uses English narration and bilingual English/Chinese captions.
