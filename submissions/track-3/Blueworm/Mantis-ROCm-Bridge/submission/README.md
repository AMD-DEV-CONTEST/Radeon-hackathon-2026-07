# Mantis-ROCm Bridge — Framework Submission Package

> **Status: local release candidate.** Local content and integrity gates pass.
> Clean-room reproduction, a public PR or submission, competition acceptance, G3
> success, convergence, robustness, real-robot safety, raw-asset redistribution
> rights, and any AMD performance advantage remain unproven. This package is
> ready for an authorized public PR only after independent `RELEASE_GO`. It is
> authored in English (the official repository language)
> and is mirrored as a navigation index by `README.zh-CN.md`. It contains no raw
> Mantis mesh, URDF, or other raw asset payload, dataset, checkpoint,
> credential, or private deployment payload; the only URDF/STL files present are
> the nine synthetic, non-Mantis test fixtures under `tests/fixtures/`.

- Official event: 2026 AMD AI DevMaster Hackathon — Track 3 (Physical AI)
- Submission deadline: 2026-08-06T23:59:00+08:00 (re-check before submitting)
- Rules snapshot: `configs/competition-resources-v1.json`
- Public authority: `docs/FRAMEWORK_STORY_V1.md`,
  `docs/G3_FAILURE_ATTRIBUTION_SUBMISSION_SPRINT.md`, and
  `submission/EVIDENCE_MATRIX.md`
- Participant: **Zhiwen Su**
- Team: **Blueworm**
- Application: **Mantis-ROCm Bridge**
- Project license: **Apache-2.0** for Blueworm-owned original material

## Product story

Mantis-ROCm Bridge is a **contract-driven, evidence-gated robot adaptation and
task-porting framework**. It makes source/target embodiment assumptions,
controller and safety rules, dataset interfaces, policy runtime, evaluation
thresholds, and evidence promotion explicit.

The project is designed as infrastructure for the **AMD embodied-AI
ecosystem**, not as a one-off Mantis demo. For robot manufacturers, it provides
a reusable route from custom URDFs, kinematics, cameras, state/action and
controller interfaces to Genesis simulation, LeRobot datasets and policies,
and staged execution on AMD Radeon + ROCm. The included profile model,
URDF-to-ROCm compiler, LeRobot adapter, and evidence gates are intended to
reduce the integration cost for additional vendor robots.

The Tron/RoboTwin `stack_bowls_three` → Mantis/Genesis/LeRobot/ROCm path is the
first evidence-backed **reference case**. Mantis is not the product definition,
and one real reference case plus one synthetic validation fixture does not
prove general multi-robot runtime support.

Within this individual, deadline-bound prototype, demonstration coverage and
training time limit policy quality; the current policy is not deployment-ready.
The primary contribution is therefore the reusable integration layer and its
auditable path to AMD hardware, not a claim that the three-bowl task has been
solved.

**Watch the submission demo:**
[`Mantis_ROCm_Bridge_demo_20260806_v4.mp4`](Mantis_ROCm_Bridge_demo_20260806_v4.mp4)

The minimum usable framework surface is complete:

- a blocked copy-and-edit robot-port profile template;
- a Mantis reference profile with 20 required local evidence references;
- a synthetic validation-only fixture;
- deterministic read-only `validate` and `plan` commands;
- explicit controller, safety, data, policy, evaluation, asset, runtime, and
  claim boundaries.

See `docs/FRAMEWORK_STORY_V1.md` and
`receipts/framework-mvp-terminal-20260729-v2/`.

## Honest result summary

This submission documents a **negative closed-loop result**, reported exactly.

| Phase | Outcome | Evidence receipt |
|---|---|---|
| Environment execution (ROCm, single Radeon GPU) | Verified | `receipts/amd-act-rocm-v2-live-20260726-v1/` |
| ACT model training on AMD | Completed optimization run; final loss 0.023 at step 60,000; `exit_code=0` | `receipts/amd-act-rocm-v2-live-20260726-v1/` |
| Real-time open-loop inference on AMD | PASS — 12 finite actions, fixed joint limits satisfied | `receipts/amd-act-openloop-inference-20260726-v1/` |
| Closed-loop G3 evaluation (seeds 101–110) | **0/10 strict successes — FAIL** (eight `timeout`, two `collision_safety`) | `receipts/amd-act-closedloop-g3-multiseed-final-20260726-v1/` |
| G3 failure attribution | deterministic CUDA replay reproduced seed 101 timeout and seeds 107/108 right-wrist collision families; ACT target counterfactuals enter the same collision family | `receipts/g3-r1r2-dynamic-replay-20260727-v2/`; `receipts/g3-commanded-target-counterfactual-20260727-v2/` |
| Single-variable correction | six accepted trajectories / 7,085 frames; from-scratch CUDA ACT training completed to 60,000 steps with verified provenance | `receipts/4090-multiseed6-trajectory-correction-20260727-v1/`; `receipts/4090-act-multiseed6-training-final-20260727-v1/` |
| Corrective CUDA representative / AMD promotion | seeds 101/107/108 completed with 0 successes and 2 safety failures; `COMPLETE_NOT_PROMOTABLE`; official-AMD corrective execution not started | `receipts/4090-g3-corrective-representative-terminal-20260728-v2/` |

**Training loss is not task success.** The optimization curve is descriptive
only; it does not establish convergence, grasping, stacking, task success,
generalization, robustness, real-robot safety, or any AMD performance
advantage. No AMD performance advantage is claimed.

## Document index

| Document | Purpose |
|---|---|
| `TECHNICAL_REPORT.md` | Full technical report, one section per official Track 3 requirement |
| `EVIDENCE_MATRIX.md` | Every quantitative claim mapped to a verified receipt or `TODO-evidence` |
| `VIDEO_STORYBOARD.md` | Independently accepted 168-second 720p video with English narration and subtitles |
| `PUBLICATION_CHECKLIST.md` | Secret, size, license, clean-room, English, and PR gates before publishing |
| `../docs/REPRODUCIBILITY.md` | Public official-cloud command surface; clean-room execution remains pending |
| `README.zh-CN.md` | Chinese navigation mirror (English is authoritative) |

## Required public deliverables

| Deliverable | Source of truth | Current gate |
|---|---|---|
| Reproducible project README | top-level `README.md`, `docs/REPRODUCIBILITY.md` | command-complete draft; clean-room execution `TODO-evidence` |
| Technical report | `submission/TECHNICAL_REPORT.md` | evidence-backed framework-first draft; participant and terminal corrective result synchronized |
| Source code | `src/`, `tools/`, `configs/`, `tests/` | complete-source and package-policy gates pass; an authorized public PR remains gated on independent `RELEASE_GO`; project LICENSE remains Apache-2.0 / Blueworm / 2026 |
| ROCm environment | `docker/`, `requirements/`, official-cloud instructions | available; clean-room verification `TODO-evidence` |
| Training evidence | `receipts/amd-act-rocm-v2-live-20260726-v1/` | terminal audit complete |
| Open-loop inference evidence | `receipts/amd-act-openloop-inference-20260726-v1/` | complete |
| Closed-loop evaluation evidence | `receipts/amd-act-closedloop-g3-multiseed-final-20260726-v1/` | complete (negative) |
| Demonstration video (English narration + subtitles) | `submission/Mantis_ROCm_Bridge_demo_20260806_v4.mp4`; SHA-256 `220c54c7ca68760db53a5a9d8c80d1d8f39755a7365ee682758d6b5b50952017`; `submission/VIDEO_STORYBOARD.md` | `VIDEO_GO`; H.264 1280x720, 168 seconds, 5,040/5,040 frames decoded; correct three-bowl scene; scripted expert and incomplete 50-step policy smoke are visibly distinguished |
| Project LICENSE | `LICENSE`, `docs/PROJECT_LICENSE_DECISION.md` | Apache-2.0; copyright holder Blueworm; year 2026; decided 2026-07-29; original project material only |
| Third-party notices | `third_party/ASSET_LICENSES.md` | audit current as of 2026-07-27; identity authority: `receipts/asset-license-public-audit-20260727-v2/README.md`; rendered demo visuals are user-permitted, but raw Mantis asset redistribution remains blocked |
| Pull request to official repository | `https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07` | `TODO-evidence` (not created) |

## Asset policy (submission safety boundary)

Current authorization state: the user permits **rendered Mantis visual media in
the demonstration video**. This permission is limited to the rendered demo and
does not establish general redistribution rights, third-party licensing, or
permission to publish raw or derived asset payloads. No permission to
redistribute the Mantis URDF, meshes, source assets, derived raw asset files, or
asset payloads has been established.

The public submission therefore treats Mantis as an **externalized,
hash-pinned
dependency** until the owner publishes a redistributable license or supplies
written submission permission (see `third_party/ASSET_LICENSES.md` and the
current correction
`receipts/asset-license-public-audit-20260727-v2/README.md`; the immutable v1
audit is superseded for repository identity only). Public
scripts may materialize Mantis locally after an explicit acknowledgement, but
the repository and any Docker image **must not** embed the URDF, meshes, or
derived materializations, raw source assets, derived raw asset files, or asset
payloads. Permission for rendered demo visuals does not extend to source
publication. The MIT-licensed bowl asset (`002_bowl` model 3,
Tianxing Chen / RoboTwin2.0) may be packaged only with its pinned attribution
and verified license file. No credential, private deployment payload, dataset,
checkpoint, or file over 100 MB is proposed for publication.

The project license is a separate owner decision, now recorded: original
project source and documentation are licensed under **Apache License 2.0**,
copyright holder **Blueworm**, copyright year **2026**, decision dated
**2026-07-29** (see `LICENSE` and `docs/PROJECT_LICENSE_DECISION.md`). It
applies only to original project code and documentation that Blueworm has the
right to license; it cannot relicense or broaden the rights of any Mantis or
other third-party payload. Selecting this license does not by itself establish
clean-room reproduction, a public repository, a submitted pull request,
competition acceptance, a G3 pass, or third-party authorization. Archive
clean-room source review remains `CLEANROOM_RUNNER_NO_GO`; no runner executed,
so clean-room reproduction is unproven and disclosed as a limitation.

## Claim boundary

This package establishes **framework narrative completeness, configuration
readiness, and evidence traceability** for one Mantis reference case. It does
not establish a second real robot port, generic runtime execution, corrective
policy effectiveness, official-AMD corrective training, clean-room
reproduction, a public repository, a submitted pull request,
submission, a G3 pass, or competition acceptance. The independently accepted
168-second v4 video preserves those same claim boundaries.
