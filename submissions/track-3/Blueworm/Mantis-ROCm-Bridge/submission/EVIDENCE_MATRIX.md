# Evidence Matrix

> Every quantitative or capability claim in the submission is mapped below to a
> verified receipt, a configuration authority, or an explicit `TODO-evidence`.
> Claims are partitioned by framework, CPU/CUDA (4090 development), AMD
> runtime, training, inference, and G3 closed-loop. Mantis is the
> `stack_bowls_three` reference case. **`TODO-evidence` marks a claim that must
> be backed before publication and is not currently asserted as fact.**

Release posture: local content and integrity gates pass for this candidate.
Clean-room reproduction, a public PR or submission, competition acceptance, G3
success, convergence, robustness, real-robot safety, raw-asset redistribution
rights, and any AMD performance advantage remain unproven. It is ready for an
authorized public PR only after independent `RELEASE_GO`.

Legend: `VERIFIED` = backed by an immutable receipt and independent hash check;
`CONFIG` = backed by a frozen configuration; `TODO-evidence` = not yet backed.

## 0. Framework surface

| Claim | Value | Source | Status |
|---|---|---|---|
| Product definition | contract-driven, evidence-gated robot adaptation and task-porting framework; Mantis is one reference case | `docs/FRAMEWORK_PRODUCT_RESET_V1.md` | VERIFIED |
| Generic profile kinds | blocked template, Mantis reference, synthetic validation-only fixture | `configs/robot-port-profile-*.json`; `tests/fixtures/robot-port-profile-synthetic-v1.json` | VERIFIED |
| Read-only interface | deterministic `validate/plan`; no simulator, data, training, inference, or remote option | `tools/plan_robot_port.py` | VERIFIED |
| Profile/reference parity | 22/22 focused tests; 20 required Mantis references; eight runtime hashes unchanged | `receipts/framework-mvp-terminal-20260729-v2/` | VERIFIED |
| Framework MVP terminal | `COMPLETE_FRAMEWORK_PROFILE_AND_READ_ONLY_PLANNER_VERIFIED` | MVP terminal receipt | VERIFIED |
| URDF→ROCm port compiler | deterministic 11-file bundle, generated runner, production runtime unmodified | `receipts/rocm-native-robot-port-terminal-20260729-v1/terminal.json` | VERIFIED |
| ROCm-native generated port | `gs.amdgpu` active, strict ROCm, bimanual 7+7 (14 DoF, unique), finite init/final states, 2 steps, zero controller commands; official AMD instance `u-11422-e97d3fd5`, torch 2.9.1+rocm7.2.1, HIP 7.2.53211, Genesis 1.3.0 | `receipts/rocm-native-robot-port-amd-20260729-v1/genesis-runtime.json` | VERIFIED |
| Bounded bf16 tuning (same AMD device) | recommended precision bfloat16; inference +12.9% (0.1287), training step +26.8% (0.2681), max abs error 0.0104, cosine 0.99999; state `ROCM_TUNING_MEASURED`; ACT quality not promoted, not AMD-deployable | `receipts/rocm-native-robot-port-amd-20260729-v1/benchmark.json` | VERIFIED |
| Second real robot port | — | — | TODO-evidence (synthetic fixture is not a real port) |
| Generic runtime execution | — | — | NOT CLAIMED |

## 1. CPU / CUDA (4090 development host)

| Claim | Value | Source | Status |
|---|---|---|---|
| Audited LeRobot revision | `d9e74a9d374a8f26582ad326c699740a227b483c` | `configs/source-reference-4090.json` | VERIFIED |
| Canonical scripted G1 (seed 1) frames | 1,177 frames / 12 strict / both grippers released | `configs/mantis-port-config.json`; `docs/STACK_BOWLS_PORT.md` | VERIFIED |
| Four-seed dataset | 4 episodes / 4,738 frames | `configs/mantis-port-config.json` | VERIFIED |
| Six-seed corrective dataset | 6 accepted episodes / 7,085 frames; exact seeds 1001/1004/1007/1008/1012/1016; metadata, dense, LeRobot CPU, and Parquet gates pass | `receipts/4090-multiseed6-trajectory-correction-20260727-v1/` | VERIFIED (data readiness only) |
| G1 receipt SHA-256 | `384c4ee3950754dc819a6d2ff88d59e2ce73e3116c107f8ced425abd77d688fc` | `configs/mantis-port-config.json` | VERIFIED |
| Test suite parity (dated gates) | 2026-07-25: local 454 / 4090 454; AMD CPU-only gate 532 project tests pass | included historical summaries in `docs/FRAMEWORK_STORY_V1.md`; underlying execution evidence retained off-package | VERIFIED (historical) |
| Framework MVP local regression snapshot | 1,085 discovered / 1,083 functional passes; exactly two historical immutable source-pin sentinels fail | `receipts/framework-mvp-terminal-20260729-v2/` | VERIFIED (dated snapshot) |
| Corrective CUDA training terminal | exit codes 0/0; exact twelve 5,000-step milestones through 60,000; 11 regular files each; 600 metric records; 132-file output manifest; zero exact fatal signatures | `receipts/4090-act-multiseed6-training-final-20260727-v1/` plus versioned checkpoint receipts | VERIFIED (CUDA development completeness only; no convergence/task-success claim) |
| Corrective representative evaluation | exact seeds 101/107/108; 0 successes; 2 safety failures; safety non-regression but no strict improvement; `COMPLETE_NOT_PROMOTABLE` | `receipts/4090-g3-corrective-representative-terminal-20260728-v2/` | VERIFIED (CUDA development terminal; not official AMD) |
| CUDA-specific training/inference performance | n/a | — | TODO-evidence (CUDA is the development mirror only; no CUDA-vs-AMD performance claim is made) |

## 2. AMD runtime / ROCm environment

| Claim | Value | Source | Status |
|---|---|---|---|
| Official cloud instance | `u-11422-e97d3fd5` (Radeon Cloud, global portal) | `receipts/amd-act-rocm-v2-live-20260726-v1/` | VERIFIED |
| Single AMD Radeon HIP device | `HIP/ROCR/CUDA_VISIBLE_DEVICES=0` | training receipt | VERIFIED |
| LeRobot runtime version | 0.4.4 | training + open-loop receipts | VERIFIED |
| Checkpoint-receipt telemetry | 3,027,484,672 B VRAM; 51/62/54 °C; 60 W | training receipt | VERIFIED |
| Clean-room ROCm reproduction from published commands | no runner executed; latest archive-runner source review is `CLEANROOM_RUNNER_NO_GO` | independent clean-room source-review summary retained off-package | LIMITATION (unproven; not a local package blocker) |
| Fresh AMD worker runtime refresh (2026-08-04) | instance `u-11422-e97d3fd5`, gfx1100 AMD Radeon (model 0x744b), torch 2.9.1+rocm7.2.1, HIP 7.2.53211, cuda_available=true; Python 3.12.3 | `receipts/cloud-amd-runtime-refresh-20260804-v1/runtime.json` | VERIFIED |
| ROCm wheel inventory (sha256) | torch/vision/audio/triton +rocm7.2.1 wheels hashed; Genesis rev 084e9a43 (matches 07-29 port); numpy 2.4.6, scikit-image 0.26.0, transformers 4.45.2 | `receipts/cloud-amd-runtime-refresh-20260804-v1/versions.json` | VERIFIED |
| Genesis gs.amdgpu smoke (2026-08-04) | `gs.init(backend=gs.amdgpu)` 1.82s, `scene.build()` 34.6s, 3 sim steps ok on AMD Radeon Graphics | `receipts/cloud-amd-runtime-refresh-20260804-v1/genesis.json` | VERIFIED |
| Genesis gs.amdgpu offscreen render (2026-08-04) | 640x480x3 uint8 RGB from `camera.render()` on AMD; valid scene (plane + cube) confirmed | `receipts/cloud-amd-runtime-refresh-20260804-v1/render_probe.png` | VERIFIED |
| AMD-rendered demo clip (2026-08-04) | 90-frame physics sim rendered on gs.amdgpu + ffmpeg-encoded MP4 (3.0 s), fully on AMD Radeon | `receipts/cloud-amd-runtime-refresh-20260804-v1/amd_gs_amdgpu_demo_v1.mp4` | VERIFIED |
| Six-seed corrective AMD training package | exact six-seed identity and unchanged ACT hyperparameters prepared; required CUDA promotion dependency terminated `COMPLETE_NOT_PROMOTABLE` | `configs/act-rocm-corrective-multiseed6-v1.json`; CUDA terminal receipt | CONFIG (not executed; promotion dependency failed) |
| Six-seed corrective AMD training/inference/G3 | — | — | TODO-evidence (not started) |
| AMD performance advantage | n/a | — | NOT CLAIMED (forbidden) |

## 3. Training (ACT v2, official AMD)

| Claim | Value | Source | Status |
|---|---|---|---|
| Trainable parameters | 51,581,840 | `receipts/amd-act-rocm-v2-live-20260726-v1/` | VERIFIED |
| Frozen contract | 60,000 steps; batch 8; chunk 30; seed 20260723; push_to_hub=false | `configs/act-rocm-baseline-v2.json` | CONFIG |
| Terminal exit | `train.exit_code=0`, `TRAINING_EXIT_0`, finished `2026-07-26T08:00:38Z` | training receipt | VERIFIED |
| Metric records | 600 records, step 100 → 60,000 | training receipt (v7 snapshot) | VERIFIED |
| First loss / final loss / observed min | 9.945 / 0.023 / 0.023 @ step 56,100 | training receipt | VERIFIED |
| Checkpoints verified | 12 × 5,000-step (5k–60k); 11 files each; zero exact-error matches | training receipt | VERIFIED |
| 60,000 checkpoint manifest hash | `fb93395602729584e2e63500be7f4edcdc4c32761af41fa21bb415daacd27fea` | training receipt | VERIFIED |
| Provenance collector source hash | `7c8693569192e5daa63bc86f53bd822b95a1a37117b27f605fbf16e8ded618e5` | training receipt | VERIFIED |
| Fresh AMD worker pipeline smoke — ACT training (2026-08-04) | same AMD worker `u-11422-e97d3fd5`, not a clean room; dataset `mantis_stack_bowls_multiseed4_gripper_v2_20260726_v1` (4 episodes / 4,738 frames); LeRobot 0.6.2, ACT, chunk 30, 16D, 50 steps @ 2.71 s/step on AMD Radeon (gfx1100, ROCm); valid `model.safetensors` checkpoint sha256 `aeb0b849…` (206 MB) + 11-file manifest | `receipts/cloud-amd-act-fresh-training-20260804-v1/training_receipt.json` | VERIFIED (pipeline-smoke execution only; not convergence, not a clean-room run) |
| **Convergence** | n/a | — | NOT CLAIMED (loss is descriptive only) |
| **Task success from training** | n/a | — | NOT CLAIMED (forbidden) |

## 4. Inference (open-loop, official AMD)

| Claim | Value | Source | Status |
|---|---|---|---|
| Gate status | PASS, `terminal_rc=0` | `receipts/amd-act-openloop-inference-20260726-v1/` | VERIFIED |
| Decoded / selected samples | 12 / 12 distinct | open-loop receipt | VERIFIED |
| Finite actions | 12 / 12 | open-loop receipt | VERIFIED |
| Postprojection fixed-limit safety | 12 / 12 pass | open-loop receipt | VERIFIED |
| Normalized-gripper projection | 11 samples / 18 channels; max delta 0.01294165849685669 | open-loop receipt | VERIFIED |
| Physical 18D projection | 4 samples / 4 left-wrist-yaw; max delta 0.010144191741943365 | open-loop receipt | VERIFIED |
| Archive SHA-256 | `71a0fed4864ecf5a1cb8ccac7c181ca6d7a3c4c3975119d282398182a8249ac7` | open-loop receipt | VERIFIED |
| Fresh AMD worker pipeline smoke — open-loop inference (2026-08-04) | same AMD worker `u-11422-e97d3fd5`, not a clean room; dataset `mantis_stack_bowls_multiseed4_gripper_v2_20260726_v1` (4 episodes / 4,738 frames); fresh 50-step checkpoint loaded on AMD (`cuda:0`, gfx1100/ROCm); 12/12 selected samples produced finite actions on AMD; actions archived sha256 `cf8d9ad6…` | `receipts/cloud-amd-act-fresh-openloop-20260804-v1/receipt.json` | GATE FALSE — `open_loop_inference_pass=false`: LeRobot 0.6.2 differs from the frozen 0.4.4 pin and six gripper values exceed [0,1] |
| Closed-loop control / task success | n/a | — | NOT CLAIMED (open-loop interoperability only) |

## 5. G3 closed-loop evaluation (official AMD) — negative

| Claim | Value | Source | Status |
|---|---|---|---|
| Exact seed set | unique 101–110 (10/10 episodes) | `receipts/amd-act-closedloop-g3-multiseed-final-20260726-v1/` | VERIFIED |
| Strict task successes | **0/10** (0.0 success rate) | G3 receipt | VERIFIED |
| Failure taxonomy | **eight `timeout`, two `collision_safety`** | G3 receipt | VERIFIED |
| Safety failures | 2 (seeds 107, 108; terminal at row 28) | G3 receipt | VERIFIED |
| Aggregate status / exit | `FAIL` / exit code 2 | G3 receipt | VERIFIED |
| Frozen gate | ≥6 successes, ≥0.6 rate, 0 safety failures (not met) | G3 receipt | VERIFIED |
| Time window | started 15:34:08Z, finished 15:58:38Z (2026-07-26) | G3 receipt | VERIFIED |
| During-run GPU telemetry | 2,223 single-`GPU[0]` samples; 803 nonzero; max 87% | G3 receipt | VERIFIED |
| Post-run device state | GPU use → 0; no running KFD PID | G3 receipt | VERIFIED |
| Aggregate final-manifest SHA-256 | `12ad5c1971280f7dc2835722c9c8b542053ce681a5fc6681b5e80751d2303637` | G3 receipt | VERIFIED |
| Supervisor final-manifest SHA-256 | `36b4afda1071e83af5454632cc46180f83d7e0b1503658310fad7d5381496ecf` | G3 receipt | VERIFIED |
| G3 summary SHA-256 | `069e523cfada85bbf05bd9a96b66289f0943da856f09654469589ec5b8d5e60f` | G3 receipt | VERIFIED |
| KFD `/proc` direct collector | unavailable before/after (managed worker) | G3 receipt | VERIFIED (evidence limitation, noted) |
| Representative static failure attribution | timeout seeds 101/106/110: zero success rows, negligible lift, associated-identity maximum XY motion 0.000000031/0.000171487/0.014344552 m, left-wrist-yaw projection clipping; collision seeds 107/108: exact bowl-to-right-wrist contacts at step 27 | v1 observation receipt plus additive identity correction `receipts/amd-act-g3-failure-attribution-static-correction-20260727-v2/` | VERIFIED (static; replay required) |
| Representative CUDA dynamic replay | seed 101 `timeout@1199`, zero robot-bowl contacts; seeds 107/108 right-wrist source-mesh collisions at steps 28/27; exact 250→30 Hz holds and ACT queue chronology | `receipts/g3-r1r2-dynamic-replay-20260727-v2/` | VERIFIED (CUDA development evidence only) |
| Commanded-target counterfactual | seed 107 target collision family at steps 27/28; seed 108 at steps 25/26/27; pose admissions pass; shim invocations zero | `receipts/g3-commanded-target-counterfactual-20260727-v2/` | VERIFIED (CUDA development evidence only) |
| Causal correction selection | controller tracking error is not required to create the diagnosed target-path collision family; first intervention changes only successful ACT trajectory distribution | `configs/act-trajectory-distribution-correction-v1.json` | CONFIG (correction effectiveness not yet claimed) |
| G3 pass / generalization / G4 robustness | n/a | — | NOT CLAIMED (G3 is FAIL) |

## 6. Asset / licensing claims

| Claim | Value | Source | Status |
|---|---|---|---|
| Mantis redistribution license | none detected; `package.xml` still `TODO: License declaration`; rendered demo visuals are user-permitted, while raw URDF, meshes, source assets, derived raw asset files, materializations, and asset payloads remain externalized | `third_party/ASSET_LICENSES.md`; identity authority: `receipts/asset-license-public-audit-20260727-v2/README.md` (v1 historical/superseded for identity) | VERIFIED (raw-asset redistribution blocked; rendered-video permission is not a general license) |
| Bowl asset license | MIT (Tianxing Chen / RoboTwin2.0 `002_bowl` model 3) | `third_party/ASSET_LICENSES.md` | VERIFIED |
| Mantis owner authorization to redistribute | none received | — | TODO-evidence |
| Project LICENSE selected by owner | Apache-2.0; copyright holder Blueworm; copyright year 2026; decided 2026-07-29; canonical `LICENSE` SHA-256 `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30` (11358 bytes); original project material only; no third-party right broadened | `LICENSE`, `docs/PROJECT_LICENSE_DECISION.md` | VERIFIED |

## 7. Publication / reproducibility claims

| Claim | Value | Source | Status |
|---|---|---|---|
| Demo video (English narration + subtitles) | selected v4 (168 s, 1280x720, H.264/yuv420p, AAC 48 kHz stereo): correct upright Mantis three-bowl scene, successful scripted expert episode 0 labelled `NOT POLICY OUTPUT`, AMD 50-step policy-in-loop smoke labelled `TASK NOT COMPLETED`, framework/ROCm/training/interface cards, and strict G3 0/10; exact MP4 SHA-256 `220c54c7ca68760db53a5a9d8c80d1d8f39755a7365ee682758d6b5b50952017` | `submission/Mantis_ROCm_Bridge_demo_20260806_v4.mp4`; independent full-decode and visual-acceptance summary retained off-package; storyboard `submission/VIDEO_STORYBOARD.md` | VERIFIED (`VIDEO_GO`; 5,040/5,040 frames decoded, 0 black-threshold findings, 33 pinned and 89 dense visual samples reviewed, no caption overlap) |
| Historical release-mode packaging | v14 `COMPLETE_RELEASE`; 246 allowlisted files; zero content findings; zero promotion findings; 12/12 local Markdown links resolved; 163 inventoried provenance paths | `receipts/publication-release-20260729-v6/` | VERIFIED (historical candidate) |
| Local release candidate admission | secrets, size, complete-source, packaged ROCm evidence, links, and package-policy gates pass; no future release identity or acceptance is asserted | `submission/PUBLICATION_CHECKLIST.md`; independent release-audit summary retained off-package | RELEASE-GATED (ready for authorized PR only after independent `RELEASE_GO`) |
| Historical machine-path boundary | 26 occurrences, restricted to seven explicitly exempt non-executable frozen-provenance files | v5 preflight receipt (`receipts/publication-candidate-preflight-20260727-v5/`); superseded for current counts by the release-mode package above | VERIFIED (historical; inventoried; runtime surfaces remain fail-closed) |
| Release-promotion blocker | the historical v5 preflight recorded the project LICENSE as its sole promotion blocker; the owner decision (Apache-2.0, Blueworm, 2026) and the root `LICENSE` resolve it, and an independent release-mode packaging build reached `COMPLETE_RELEASE` with zero promotion findings | `docs/PROJECT_LICENSE_DECISION.md`; `receipts/publication-candidate-preflight-20260727-v5/` | VERIFIED (license resolved; release packaging gate passed) |
| Reproduction command surface | read-only profile walkthrough plus official ROCm bootstrap, externalized asset, scene, data, 60k ACT, open-loop, G3, and final-evidence commands documented | `docs/REPRODUCIBILITY.md` | CONFIG (clean-room execution still TODO-evidence) |
| Clean-room reproduction pass | no runner executed; source review remains `CLEANROOM_RUNNER_NO_GO` | independent clean-room source-review summary retained off-package | LIMITATION (unproven; not a local package blocker) |
| Public repository / PR to official repo | — | `https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07` | PENDING_EXTERNAL (not created) |
| Upstream PR(s) accepted | — | — | TODO-evidence |

## Cross-cutting integrity note

All training, inference, and G3 receipts are independently verified by
`sha256sum -c` with documented return code 0, per the receipt READMEs. No
receipt was overwritten or relabeled to change a negative result into a
positive one.
