# Mantis LeRobot interface gate

The public `BlueWorm-EAI-Tech/lerobot_mantis_server` repository was audited at revision `53953bc9b3c63dfa1689904cc986ae9e09c1d35b`. Its Mantis adapter exposes 16 ordered joint-position features at 30 Hz and three cameras: `env_cam` at 320×240 plus left and right wrist cameras at 424×240. This matches the target state/action and camera ordering frozen in `configs/mantis-port-config.json`.

The same upstream history records a material dataset failure: a 109-episode, 231,763-frame dataset had zero action variance for `left_shoulder_roll_joint.pos` and `right_shoulder_roll_joint.pos` (indices 1 and 9). Editing parquet actions without recomputing both episode and dataset statistics produced invalid normalization. The upstream repair changed their standard deviations from zero to approximately `0.151826` and `0.136527`. That repaired dataset has not been found on the current server, so these numbers are provenance evidence, not a local-dataset claim.

`configs/mantis-lerobot-interface-v1.json` freezes the exact joint and camera interface. `tools/audit_mantis_lerobot_dataset.py` checks `meta/info.json` and `meta/stats.json`, rejects order or shape drift, rejects all action/state dimensions below the fixed `1e-4` standard-deviation floor, explicitly guards indices 1 and 9, and distinguishes policy statistics:

- ACT and SmolVLA require finite `mean` and `std` arrays;
- PI0.5 requires finite, strictly ordered `q01` and `q99` arrays;
- no policy is promoted from metadata alone because dense action/state alignment and episode quality remain separate gates.

Run the gate before any NVIDIA or AMD training command:

```bash
PYTHONPATH=src python tools/audit_mantis_lerobot_dataset.py \
  /path/to/mantis_dataset \
  --output /new/nonexistent/path/mantis-dataset-metadata-receipt.json
```

The output path is non-overwriting. A passing receipt proves only interface and normalization readiness; it does not prove demonstration quality, task success, or ROCm execution.

`src/mantis_rocm_bridge/lerobot_adapter.py` is the runtime boundary. It converts the 18 physical Genesis joint positions to the frozen 16D named LeRobot state, expands named 16D policy actions back to four physical clamp commands plus 14 arm joints, and refuses missing, extra, reordered, or non-finite features. It also requires the three policy image roles exactly; simulator images and real cameras may differ in native resolution, but they cannot silently swap semantic keys.

`configs/dense-dataset-gate-v1.json` and
`tools/audit_mantis_lerobot_dense.py` form the second data gate. They stream only
the scalar/vector parquet columns, require contiguous global/episode/frame
indices, a 30 Hz timestamp sequence, finite 16D state/action vectors, real
variation at the two historically broken shoulder indices, and one successful
strict task outcome for every expert episode. Image decoding and learned-policy
quality remain separate gates.

## Simulator episode export

`configs/sim-episode-export-v1.json` freezes the simulator capture array names,
18D physical state/action input, 30 Hz timebase, three native camera shapes, and
minimum episode length. `src/mantis_rocm_bridge/episode_export.py` collapses the
four physical clamp coordinates into the frozen 16D LeRobot interface and
streams frames into the public LeRobot 0.4.2 dataset API.

LeRobot 0.4.2 remains the tested NVIDIA/CPU development boundary. The official
2026-07-23 training material targets `lerobot==0.4.4` on ROCm 7.2.1 and PyTorch
2.9.1. That cloud version is now the final deployment target, but it is not yet
promoted: the 16D/18D adapter, three-camera ordering, episode export, dense
dataset audit, and ACT preflight must all pass against 0.4.4 on the Radeon
worker. No dataset conversion or compatibility result may be inferred from the
existing 0.4.2 receipts.

An episode is saved only after its serialized stage trace replays through the
same ordered state machine and the strict terminal predicate passes. Failed or
short captures invoke `clear_episode_buffer(delete_images=True)` and never enter
the dataset statistics. `tools/export_mantis_npz_to_lerobot.py` publishes into a
new dataset directory through a staging path and emits both an export receipt
and `strict_episode_outcomes.json` for the dense audit.

The export contract freezes a `0.011` normalized paired-finger tolerance and a
`0.003` normalized endpoint tolerance. These bounds come from a full scan of
the 1177-frame strict capture: the largest paired estimate spread was
`0.0102031`, and the largest averaged endpoint excursion was `0.00240638`.
They cover Genesis contact/sub-step tracking motion while remaining below
roughly `0.42 mm` and `0.12 mm` of physical finger travel respectively.
Paired estimates are averaged and endpoint excursions are clamped; anything
beyond either frozen bound is rejected.

The 4090 development host keeps its original Genesis/Torch environment
unchanged. Missing Hugging Face dataset-writing dependencies are installed into
a separate versioned overlay from
`requirements/lerobot-export-overlay-v1.txt` using `pip --no-deps`. The overlay
is placed before the audited LeRobot 0.4.2 source tree on `PYTHONPATH`.
`tools/smoke_lerobot_export_runtime.py` writes a one-frame synthetic schema
dataset to verify the real `info/stats/parquet` path. That artifact is explicitly
non-trainable and is expected to fail the zero-variance and minimum-length data
gates.

LeRobot 0.4.2's `add_frame()` validator rejects an explicitly supplied
`timestamp` even though the method later contains a timestamp-pop branch. The
bridge therefore validates every capture timestamp itself, omits that key from
the frame passed to LeRobot, and relies on LeRobot's deterministic
`frame_index / fps` timestamp generation. State and action vectors are handed
to the same validator as explicit NumPy `float32` arrays.

The remote v2 schema smoke
`mantis-lerobot-schema-smoke-cpu-20260723-v2` successfully wrote
`meta/info.json`, `meta/stats.json`, episode metadata, and
`data/chunk-000/file-000.parquet`; its receipt SHA-256 is
`22b60316f1f2b99032bb32c64805e2b5879a580bf43779915940ad5f9c2c0db6`.
The normal metadata gate then rejected it with exit code 2 for zero variance,
including the guarded action indices 1 and 9, exactly as intended. This is
runtime-schema evidence only and not an expert-data or task-success result.

`tools/run_genesis_lerobot_capture_smoke.py` is the next integration boundary:
it loads the real Mantis and three-bowl Genesis scene, renders the frozen world
and wrist cameras, samples 18D readback plus the active 18D command on the 30 Hz
policy clock, and sends the frames through the same LeRobot export session. The
smoke deliberately terminates at `missed_grasp`; passing means LeRobot reports
zero saved frames/episodes and no parquet or image payload survives buffer
clearing.

CPU run `mantis-genesis-lerobot-capture-rejection-cpu-20260723-v3` passes that
boundary with receipt SHA-256
`9d20d7b7843a11f13cef50faefaae05b43506fb2fdc8de400c439ad1a262ab25`.
It captures the real 18D readback and command plus all three cameras at policy
ticks 0, 1, and 2. The 250 Hz physics-to-30 Hz policy schedule has a measured
maximum non-early skew of `2.667 ms`; the deliberate failure leaves zero saved
frames, zero episodes, zero parquet files, and zero image files.

## Strict seed-1 demonstration

CPU run `mantis-stack-bowls-scripted-g1-stl-cpu-capture-20260723-v91`
captures the complete strict seed-1 episode: 1177 frames at 30 Hz, all three
cameras, no recorded safety failure, and 12 consecutive strict stabilization
frames. Its receipt SHA-256 is
`b64a28487475413b498bdd50367d6c355c70c3eec69bd12b2e0cc3326ce81d93`.

The fresh dataset
`/data01/suzw_data/tron/amd_track3/datasets/mantis_stack_bowls_scripted_g1_v1`
contains one accepted episode. Its export receipt SHA-256 is
`4663bd61557411c53f21aa7ec737b7b3652381e411e4fcd05b9fb581a15f7c44`;
`info.json` and `stats.json` hash to
`2dd4f61bed76b059d81c4e1d50e45712c00215c12334369819a913db4ed96f93`
and
`297063f7c7809ed33043d88a15fdcde3a427cd3d3f46d641ebe34de79ff15b56`.
The metadata gate passes ACT, SmolVLA, and PI0.5 readiness with no issues. The
dense gate audits all 1177 frames and passes with shoulder-roll action standard
deviations `0.3246761` and `0.09083415` at guarded indices 1 and 9. Direct
LeRobot reads of frames 0, 588, and 1176 decode finite 16D state/action tensors
and all three images at their frozen shapes.

This is enough to validate the complete capture/export/normalization path, but
one scripted seed is not a training-volume, learned-policy, multi-seed,
generalization, hardware, or ROCm result.

## Current v2 gate — gripper contract v2 dataset (seed 1007, two-stage replay)

The current dataset gate is the seed-1007 two-stage replay capture exported
under **gripper reduction contract v2**. Full receipts are mirrored at
`receipts/4090-gripper-contract-v2-20260725-v2/`, with a summary in that
directory's `README.md` and a three-frame decode in
`sample_decode_receipt.json`.

Source capture run
`mantis-stack-bowls-two-stage-replay-seed1007-stl-cpu-capture-20260725-v5-gripper-contract-v2`
ran on the CPU backend (`gs.cpu`, no GPU), generation mode `replay`, seed
1007, effective policy step limit 1200, 1198 frames, 12 strict frames, 0
safety failures. Its run-level `success=true` but
`episode_success_claim=false` and `g1_claim=false`. The source raw NPZ
(`episode_seed_1007.npz`) is remote-only; its SHA-256
`6a42ec42d2ffc216b1319845e3f125f61e19cd16f71af47e528dc405f862c88f`
is recorded from the source capture receipt and is the only NPZ-level
provenance carried locally.

The published dataset root (remote) is
`/data01/suzw_data/tron/amd_track3/datasets/mantis_stack_bowls_two_stage_seed1007_gripper_v2_20260725_v2`:
LeRobot 0.4.2, 1 accepted / 0 rejected episodes, 1198 frames,
`generation_mode=replay`. Contract v2 uses
`state = bounded_mean_with_residual` and
`action = strict_symmetric_inverse`. The action channel is strictly symmetric
(left/right max spread and residual all `0.0`, 0 frames above the `0.011`
tolerance); the state channel records bounded mean with residual
(left spread/residual `0.004444588372047913` / `0.00222229418602396`,
right `0.0147149957557942` / `0.0073574978778971`) instead of masking it.
This resolves the prior export blocker where large contact asymmetry rejected
the entire export.

The metadata/normalization gate passes with
`policy_ready = {act=true, pi05=true, smolvla=true}` and no issues. The dense
gate passes 1198/1198 frames with one successful strict outcome; guarded
action indices 1 and 9 have standard deviations `0.237800272243723` and
`0.12509573919345518`. A direct LeRobot 0.4.2 read of frames 0, 599, and
1197 decodes finite 16D `observation.state`/`action` and all three cameras at
their frozen shapes — `env_cam` `[3,240,320]`, both wrist cameras
`[3,240,424]` (CHW) — finite and in `[0,1]`. The mirrored primary receipt
hashes are
`dataset/sim_export_receipt.json = 13d1fe749bfaa7e7e873e4deadc06699d534113a11a5c30f1cbe9090c76d73bd`,
`dataset/info.json = c2c269b361aa76b6978f63f870e64f502bf439827ac3bbbc4d954c8f760594ba`,
`dataset/stats.json = 23b634863e720ba5c4037dd8f2c39abbed084c83932f93093be169214b55cedd`,
`dataset/strict_episode_outcomes.json = 9f10209a5ba3e3f41e833169b79ee7c1957339da9371f4e234b6d284a6c1028a`,
`audits/metadata_audit_receipt.json = 7f975b880168ccc3937d1cfbd8f4c22ab9fed47ac72acb0e4ae014034ad361b8`, and
`audits/dense_audit_receipt.json = eb9a0e6e8f6a8ace85a5ca2bd1ade8ab0eb3b6c90861000b5c0ca15822a07795`.

The earlier path
`.../mantis_stack_bowls_two_stage_seed1007_gripper_v2_20260725_v1` is
**disabled and history-only**: its export defaulted to relabeling `replay` as
`online`, producing an incorrect generation-mode declaration, and must never
be promoted. It is a distinct object from the canonical scripted
`mantis_stack_bowls_scripted_g1_v1` (seed 1 G1) above; the two must not be
conflated.

This v2 gate proves the complete contract-v2 export, normalization, dense, and
sample-decode path for one noncanonical seed. It is **not** multi-seed
evidence, a learned-policy result, a hardware result, or a GPU/AMD/ROCm
result.

## Current v3 gate — four-seed contract-v2 dataset

The versioned CPU/replay dataset
`mantis_stack_bowls_multiseed4_gripper_v2_20260726_v1` is the current
functional training-data gate. It contains four accepted episodes and no
rejections: seeds 1001/1004/1007/1008 with 1152/1200/1198/1188 frames,
respectively (4738 total at 30 Hz). Each source capture records 12 strict
stabilization rows and zero safety failures. Seeds 1002, 1003, 1005, 1006,
1009, and 1010 remain preserved negative evidence and did not enter the
dataset.

The metadata gate passes ACT, PI0.5, and SmolVLA readiness with no issues
(receipt SHA-256
`f6719381e0ae72ea43574e8d25c559fbcae12b77c1028805a582ca45d2f20085`).
The dense gate audits all 4738 frames and four strict outcomes with no issues
(receipt
`9279bbef0bd9ec23ae53f793a90f1c7bb39c5a7b2230f2b9e352ce34dc5f9218`).
Direct LeRobot reads decode the first, middle, and last frame of every episode
(12 unique frames) and pass 15 episode-boundary/timebase checks; state/action
are finite `[16]`, the environment camera is `[3,240,320]`, both wrist cameras
are `[3,240,424]`, and image ranges remain within `[0,1]` (receipt
`67a35760b2c5dcd912013476da976b4d649b0452da69acd985a694c9739f0443`).

Full mirrored JSON evidence is under
`receipts/4090-multiseed4-gripper-v2-20260726-v1/`. This proves a
four-training-seed scripted dataset path, not learned-policy generalization,
hardware, GPU, AMD/ROCm, training convergence, or closed-loop success. AMD
LeRobot 0.4.4 auditing remains pending until the hash-verified transfer archive
lands under `/workspace`.

### AMD LeRobot 0.4.4 status for this gate

The AMD LeRobot 0.4.4 status has two distinct bodies of evidence, which must
not be conflated:

1. **Old bundles (397 tests).** The AMD LeRobot 0.4.4 old schema/runtime smoke
   is already verified on the official Radeon Cloud (the
   `mantis-lerobot-schema-smoke-cpu-20260723-v2` equivalent runtime and the
   Stage 2 import/version smoke under LeRobot 0.4.4), and the AMD
   project/scripted-G1 promotion and project bundles recorded 397 passing
   tests. These are the historical first cloud validation and are mirrored
   locally.

2. **Gripper contract v2 remote-only gate (448 tests, 2026-07-25).** A later
   gate on official AMD Radeon Cloud instance `u-11422-e97d3fd5` (single GPU,
   persistent `/workspace`) extracted the v4 project
   (`/workspace/mantis_rocm_bridge_project_v4`, from archive
   `/workspace/mantis_rocm_bridge_project_v4_20260725.tar.gz`, SHA-256
   `33c548de7154ab7008c47c4aec7c853fcf682edd8e1722faa7750fbbd798ba1b`) and
   ran 448 passing project tests with `contract valid=true` and 7 unchanged
   blockers. The first extraction returned `project_tests.status=1` because
   the archive had not landed (a `cd` failure, not a code failure); that
   negative evidence is retained, and the second extraction
   (`project_tests_v2`) passed. Strict ROCm runtime passed (torch
   `2.9.1+rocm7.2.1.gitff65f5bc`, HIP `7.2.53211-e1a6bc5663`, 1x AMD Radeon
   Graphics, memory `51522830336`, LeRobot 0.4.4); GPU preflight reported no
   running processes, GPU0 only, and ~49110 MiB idle. A LeRobot 0.4.4
   writer/schema synthetic smoke
   (`/workspace/mantis_lerobot_gripper_v2_smoke_20260725_v1`, 1 frame/episode,
   `training_eligible=false`) proves writer/schema only. The Genesis+LeRobot
   amdgpu capture/rejection smoke
   `mantis-amd-gripper-v2-capture-rejection-amdgpu-20260725-v1`
   (`backend_requested=amdgpu`, `device=cuda:0` ROCm PyTorch semantics,
   `runtime_capture_smoke_pass=true`, 3 frames, rejection leaves 0/0
   frames/episodes and `training_data_written=false`; rejection
   `generation_mode=online`, success/G1 claims false, contract v2, action max
   spread `0.0`, state left/right max spread
   `0.0002822279888752277` / `0.00028642401282896746`) and the focused replay
   test both pass. Its primary evidence package
   (`/workspace/mantis_amd_gripper_contract_v2_evidence_20260725_v1.tar.gz`,
   SHA-256
   `d2661b270d39eeae341189ef6d10bd29b35af9cae9b60f65d96457afdfbc19df`, remote
   directory `/workspace/mantis_amd_gripper_contract_v2_gate_20260725_v1`) is
   **remote-only and not mirrored locally** (a browser security policy blocks
   automatic download); a local index lives at
   `receipts/amd-gripper-contract-v2-20260725-v1/`.

This remote-only gate proves the **current contract-v2 code/tests, the strict
ROCm runtime, the LeRobot 0.4.4 writer/schema, and the Genesis amdgpu
three-camera capture/rejection path**. It does **not** prove the full 1198-frame
contract-v2 dataset under the AMD LeRobot 0.4.4 metadata/dense/decode gates,
and does not prove training, inference, a learned policy, multi-seed data, G1,
or an AMD performance advantage. Accordingly, **this gripper contract v2
dataset has not yet been run under the AMD LeRobot 0.4.4 gate**: the v2
dataset, metadata gate, dense gate, and sample decode above remain LeRobot
0.4.2 / CPU evidence only. No 0.4.4 dataset conversion, full-dataset
contract-v2 audit, training, or compatibility result may be inferred from
these 0.4.2 receipts or from the remote-only code/writer/capture smoke until
the full v2 dataset is transferred to the AMD worker and re-audited on 0.4.4.

## Four-seed AMD LeRobot 0.4.4 gate (2026-07-26)

The immutable four-seed dataset
`/workspace/mantis_stack_bowls_multiseed4_gripper_v2_20260726_v1` has now
completed the official Radeon Cloud gate. The 385,607,680-byte transfer archive
matched SHA-256
`f8bb383f2cfcda7af0aede5105c804d17f0116c796fb9e00416d683f7e55b1ab`,
and all 10 archived files passed their individual hashes.

On the AMD worker:

- metadata passes for 4 episodes, 4738 frames, 30 Hz, with no issues;
- dense audit passes all 4738 frames and all 4 strict outcomes;
- strict ROCm passes on one `AMD Radeon Graphics` device with PyTorch HIP
  `7.2.53211-e1a6bc5663`;
- LeRobot 0.4.4 loads the dataset through the real
  `lerobot.datasets.lerobot_dataset.LeRobotDataset` class and decodes all 12
  first/mid/last samples;
- decoded state/action tensors are finite 16D values, `env_cam` is
  `[3,240,320]`, and both wrist cameras are `[3,240,424]`;
- an independent direct-parquet decode cross-check also passes;
- the promoted project passes 494 unit tests.

The complete mirrored package is
`receipts/amd-multiseed4-gate-20260726-v1/`. The real runtime decode receipt
hashes to
`3f72bffeff733b5a138c3059fc0eb237e970eab5d4d397e88163fd6ee4a6c6ea`.
This supersedes the earlier “full dataset pending” boundary for the four-seed
dataset, but not for any other dataset revision.

The first ACT preflight correctly failed only the scripted-G1 fields because
the legacy fixture schema did not match the immutable generator receipt. That
negative result is preserved. The repaired preflight accepts both schemas but
requires the canonical receipt to prove online generation, G1 and episode
success claims, an empty safety-failure list, and 12 trailing frames whose
strict safety and physics checks all pass. The final AMD preflight has every
check true and `training_authorized=true`; its SHA-256 is
`4cd8c9be8ee56a53aa1c428720c83321d27d7e3d4fb1610b9f91a02ec0c22fcd`.
No ACT training was run while producing this gate.

## ACT-on-ROCm launch boundary

`configs/act-rocm-baseline-v2.json` is the authoritative training baseline:
ACT, 30-step chunks at 30 Hz, recomputed Mantis mean/std normalization, the
audited Mantis LeRobot revision, and explicit `policy.push_to_hub=false`. The
unchanged v1 contract is retained as historical negative evidence: its frozen
19-argument command reached LeRobot 0.4.4 on the official AMD worker but failed
before data loading because the implicit truthy `push_to_hub` required
`policy.repo_id`. The v2 preflight fails closed unless this flag is exactly
false and emits `--policy.push_to_hub=false` once.

`tools/preflight_act_rocm.py` also verifies that the dataset receipt still
hashes the on-disk metadata, that dense-demonstration and scripted-G1 receipts
refer to the same task/data, and that PyTorch reports a HIP build with at least
one visible device. Its generated command deliberately uses
`--policy.device=cuda`: ROCm-enabled PyTorch exposes AMD devices through that
API.

The tool only emits a command contract. It does not itself start training,
create the training output directory, or convert a passing preflight into a
convergence or closed-loop success claim.

## Official AMD ACT v2 live gate (2026-07-26)

The v2 command emitted by the passing preflight is now running on the official
single-GPU Radeon Cloud worker. The immutable identities are:

- project:
  `/workspace/mantis_rocm_bridge_project_v6_act_pushhub_20260726_v1`;
- dataset:
  `/workspace/mantis_stack_bowls_multiseed4_gripper_v2_20260726_v1`;
- output:
  `/workspace/mantis_act_rocm_multiseed4_20260726_v2`;
- evidence:
  `/workspace/mantis_act_rocm_multiseed4_training_evidence_20260726_v2`.

The exact command uses ACT, 60,000 steps, batch size 8, 30-step chunks/actions,
seed 20260723, 100-step metric logging, 5,000-step checkpoints, ROCm PyTorch
device spelling `cuda`, and explicit `policy.push_to_hub=false`. The process
loaded the real 4-episode / 4738-frame dataset and constructed a 51,581,840
parameter ACT policy.

`tools/extract_lerobot_train_metrics.py` is a read-only, no-overwrite parser
for the live LeRobot 0.4.4 log. It resolves the exact tqdm numerator when
LeRobot humanizes a metric token such as `step:2K`, fails closed on incomplete
or non-finite metrics, and emits versioned CSV/JSON/PNG artifacts with an
explicit no-convergence boundary. The current project regression gate contains
532 passing tests locally and on the AMD worker.

The first immutable metric extraction contains 74 complete records from exact
step 100 to 7400: loss 9.945 to 0.143, minimum 0.143 at step 7400. The remote
CSV/JSON/PNG hashes are respectively:

- `a866f394ee5acad5683bd22818b47ca43d77efec5efe9b97f89b86c687fd8e65`;
- `46a1d893f8fd564ff89e0b521239c51c46d19b64ca00ab552d4cc6d31e8aec90`;
- `954e96a18c083201aa78f6966f436fdc4c34770d561adf8664375e4e992415f8`.

A second versioned snapshot contains 113 records through exact step 11,300:
latest loss 0.082 and minimum 0.081 at step 11,100. It is additive and does not
overwrite the first extraction.

The additive v3 snapshot contains 373 complete records through exact step
37,300: latest loss 0.029 and observed minimum 0.029 at step 37,000. These are
descriptive optimization metrics only; no convergence threshold has yet been
defined or satisfied.

The additive v4 snapshot contains 430 complete records through exact step
43,000: latest loss 0.027 and observed minimum 0.027 at step 42,000. Its
versioned CSV/JSON/PNG and sidecar artifacts passed independent
`sha256sum -c` verification. This is still a descriptive optimization
snapshot, not evidence of convergence.

The additive v5 snapshot contains 511 complete records through exact step
51,100: latest loss 0.026 and observed minimum 0.025 at step 48,000. Its
versioned CSV/JSON/PNG and sidecar artifacts passed independent
`sha256sum -c` verification. This is still a descriptive optimization
snapshot, not evidence of convergence.

The additive v6 snapshot contains 597 complete records through exact step
59,700: latest loss 0.024 and observed minimum 0.023 at step 56,100. The
terminal v7 snapshot contains all 600 records through exact step 60,000:
first loss 9.945, final loss 0.023, and observed minimum 0.023 at step 56,100.
Both manifests pass independent `sha256sum -c` verification. These remain
descriptive optimization metrics, not evidence of convergence.

Checkpoint `005000` is independently inventoried: 11 files totaling
619,237,880 bytes, with `training_step={"step":5000}`, a 206,494,976-byte
model state, and a 412,694,860-byte optimizer state. The checkpoint SHA-256
manifest itself hashes to
`a97c6b96d0112d24c252a250084d3bd7d92cade00f951592110d9761f98a5a8a`;
the exact error scan found zero traceback, CUDA/HIP OOM, runtime-error, or
non-finite loss/gradient matches.

Checkpoint `010000` independently repeats that save contract: 11 files,
619,237,881 bytes, `training_step={"step":10000}`, zero exact error matches,
and checkpoint-manifest hash
`65de30b0f6d50e4d4bbe8622bfc27dfb62da5d776c126308700c3dac42c57ea2`.

`tools/capture_act_checkpoint_receipt.py` replaces repeated handwritten
checkpoint commands with a deterministic provenance collector. It validates
required model/optimizer/training-step files, detects input mutation while
hashing, scans the frozen error taxonomy, captures a real `rocm-smi` snapshot,
and commits its six-file receipt set with per-file atomic no-clobber semantics
and inode-verified rollback. Its source SHA-256 is
`7c8693569192e5daa63bc86f53bd822b95a1a37117b27f605fbf16e8ded618e5`;
25 focused tests and the 532-test CPU-only AMD regression gate pass.

The collector independently accepted checkpoints `015000`, `020000`,
`025000`, `030000`, `035000`, `040000`, `045000`, `050000`, `055000`, and
`060000`. Each contains 11 files / 619,237,881 bytes, with recorded step equal
to expected step, zero exact log-error matches, and non-skipped ROCm telemetry.
Their
checkpoint-manifest hashes are respectively:

- `374a93b7657291170c4c5fb4efa5dc4022e23a90461eff0b96d08be8ae7fabcd`;
- `09d0212a27830bcdc97a45c41c313006a00fe1fb188aaa888f427ce79bcd60ed`;
- `2d4e35888508e6265362aa8f1da370adc5a93b76917ef2a3c325a97fd4c1240e`;
- `5ce7e51944f89e7c68f0ae7a486269b59079a7edb4b218d56d6a77aff1da44d0`;
- `06f3717b08ed3470eadc35c38e0eafd878d10981bd33ddf1a6fa740fe6ad1012`;
- `efaec7923de4656b1484b9671c945ccecd89869cd23d6f75abcddcf740a1bfce`;
- `d376353b23884fd2cf9136d22d4c211a4f0fc704ce67e6bfc0ac3ab9e7066534`;
- `ad84994fc964cb835a948bd2eba91e43c64dabc068ff58d003f010c92185edef`;
- `8adc65e4a941a6e6d6667136c798b7a8ad2074fb3f5b5ac709447c7dc04df0ff`;
- `fb93395602729584e2e63500be7f4edcdc4c32761af41fa21bb415daacd27fea`.

The versioned 35,000/40,000 batch receipt is `PASS`. A separate
`sha256sum -c` run accepted both checkpoint artifact manifests, the batch
manifest, and the v4 metric manifest; its immutable log/status pair is stored
under the remote evidence root.

The versioned 45,000/50,000 batch receipt is also `PASS`. A separate
`sha256sum -c` run accepted both new checkpoint artifact manifests, the new
batch manifest, and the v5 metric manifest; its immutable log/status pair is
stored under the remote evidence root.

The compact interim evidence package is
`/workspace/mantis_amd_ops/training_evidence_packages/mantis_act_rocm_v2_interim_step7400_evidence_20260726_v1.tar.gz`,
47,025 bytes, SHA-256
`cea1166892fbeff1c77979be83b6499bf3e1b5f11c6867e1b7a8dff4f2e6bce2`.
It carries manifests and receipts rather than duplicating the 619 MB
checkpoint. A local visual/index mirror lives under
`receipts/amd-act-rocm-v2-live-20260726-v1/`.

The additive current package including the step-11,300 curve and both
checkpoint manifests is
`/workspace/mantis_amd_ops/training_evidence_packages/mantis_act_rocm_v2_interim_step11300_evidence_20260726_v2.tar.gz`,
37,936 bytes, SHA-256
`621480f5693765c2133aa7fe43e80d02a8887469bd99ddbc1e19332fc30796bc`.

The additive current package through step 37,300 is
`/workspace/mantis_amd_ops/training_evidence_packages/mantis_act_rocm_v2_interim_step37300_evidence_20260726_v3.tar.gz`,
35,204 bytes, SHA-256
`e011cbfb98994e4ce6d0f87cf722daaf958668d196ec95237223f3e605fd15e9`.
It contains 69 lightweight evidence inputs and explicitly excludes checkpoint
payloads and mutable live logs. A macOS AppleDouble-contaminated deployment
archive is preserved as negative evidence: the exact member whitelist rejected
it before extraction, after which the corrected archive passed without
overwriting any prior artifact.

The run completed exact step 60,000 and exited naturally with code 0 at
`2026-07-26T08:00:38Z`. The terminal audit verifies all six automatic
completion files, absence of the training PID from the post-run ROCm process
snapshot, the 60,000 checkpoint manifests, the v7 metric manifest, and both
132-entry output/final-evidence manifests with zero failures. This proves
official-AMD ROCm execution, real-data optimization completion, loss logging,
checkpoint production, and artifact provenance. It does not prove convergence,
policy inference, closed-loop task success, generalization, robustness, or an
AMD performance advantage.
