# Mantis-ROCm Bridge Demo Video

Application: **Mantis-ROCm Bridge**  
Participant: **Zhiwen Su**  
Team: **Blueworm**

## Accepted deliverable

- File: `submission/Mantis_ROCm_Bridge_demo_20260806_v4.mp4`
- SHA-256: `220c54c7ca68760db53a5a9d8c80d1d8f39755a7365ee682758d6b5b50952017`
- Format: H.264 `avc1`, 1280x720, 30 fps, `yuv420p`
- Audio: English narration, AAC stereo, 48 kHz
- Duration: 168 seconds
- Acceptance: `VIDEO_GO`; 5,040/5,040 frames decoded, zero black-frame
  threshold findings, 33 pinned frames and 89 dense samples reviewed, no
  caption overlap or incorrect scene

## Story

The video explains a contract-driven, evidence-gated path for moving a custom
dual-arm robot into Genesis on AMD ROCm. The framework is the contribution;
Mantis and `stack_bowls_three` are its reference case. The opening, result, and
closing shots use the correct AMD `gs.amdgpu` three-bowl policy-in-loop output.

| # | Time | Duration | Beat | Visual and claim boundary |
|---|---|---:|---|---|
| 1 | 0:00-0:10 | 10 s | Live opening | Upright Mantis and three bowls on AMD; persistent `TASK NOT COMPLETED` label |
| 2 | 0:10-0:26 | 16 s | Porting thesis | Embodiment, perception, execution, and evidence are explicit interfaces |
| 3 | 0:26-0:46 | 20 s | Architecture | Source task -> robot profile -> URDF/ROCm port -> ACT adapter -> fail-closed evidence gate |
| 4 | 0:46-1:00 | 14 s | AMD runtime | One Radeon GPU; ROCm 7.2.1; PyTorch 2.9.1; Genesis 1.3.0; `gs.amdgpu` |
| 5 | 1:00-1:18 | 18 s | Expert data | Successful scripted episode 0, seed 1001, 1,152 frames; persistent `NOT POLICY OUTPUT` label |
| 6 | 1:18-1:36 | 18 s | Learning interface | 18D robot <-> 16D ACT; environment plus two simulation-only wrist observations; no physical calibration claim |
| 7 | 1:36-1:53 | 17 s | Training evidence | Fresh 50-step AMD pipeline smoke, historical 60,000-step baseline, and 12/12 finite open-loop actions; not task success |
| 8 | 1:53-2:09 | 16 s | Live result | Saved ACT processor and 50-step checkpoint inside the Genesis loop on AMD; task visibly not completed |
| 9 | 2:09-2:27 | 18 s | Honest result | Official strict G3 is 0/10: eight timeouts and two collision-safety stops |
| 10 | 2:27-2:40 | 13 s | Contribution | Contracts, URDF compiler, LeRobot adapter, safety gates, reproducible commands, and evidence separation |
| 11 | 2:40-2:48 | 8 s | Live close | Correct three-bowl scene, participant/team identity, and honest-evidence close |

## Visual policy

- The user's current authorization permits rendered Mantis visual media in the
  demonstration video. It does not establish general redistribution rights.
- Raw Mantis URDF, meshes, source assets, datasets, and checkpoints are
  externalized and are not in the public package.
- The successful expert segment is scripted data generated on the 4090 host
  and transferred to AMD. It is not learned-policy output.
- The policy segment is a fresh 50-step pipeline smoke on AMD. It does not
  complete the task and is not presented as task success.
- ACT consumes three simulation observations, but the two wrist views are not
  shown because their source-equivalent, uncalibrated mounts have poor
  visibility. Changing them would alter the checkpoint's visual input
  distribution and requires new data and retraining.
- Official G3 remains 0/10: eight `timeout` and two `collision_safety`
  outcomes. The CUDA corrective comparison remains
  `COMPLETE_NOT_PROMOTABLE`. Loss, finite actions, and a rendered clip do not
  establish convergence, robustness, real-robot safety, or an AMD performance
  advantage.

## Evidence map

- Correct AMD policy-in-loop scene:
  `receipts/cloud-amd-manual-live-infer-20260806-v1/`
- Fresh AMD runtime, training, and open-loop smoke:
  `receipts/cloud-amd-runtime-refresh-20260804-v1/`,
  `receipts/cloud-amd-act-fresh-training-20260804-v1/`, and
  `receipts/cloud-amd-act-fresh-openloop-20260804-v1/`
- Expert dataset identity: four episodes / 4,738 frames, with episode 0 at
  seed 1001 / 1,152 frames / strict success
- Historical official AMD baseline and G3:
  `receipts/amd-act-rocm-v2-live-20260726-v1/` and
  `receipts/amd-act-closedloop-g3-multiseed-final-20260726-v1/`
- Video acceptance: independent full-decode and visual review retained
  off-package; public facts are mirrored in `EVIDENCE_MATRIX.md`

## Claim boundary

`VIDEO_GO` establishes only that this exact media artifact is decodable,
coherent, correctly labelled, and includes intact English narration. It does
not establish policy task success, convergence, held-out success, robustness,
physical camera calibration, real-robot safety, a public repository, a Pull
Request, or competition submission.
