# G3 failure-attribution and submission sprint

Date: 2026-07-27  
Phase status: failure attribution and CUDA corrective training complete; representative evaluation pending; AMD corrective package and publication preflight prepared  
Authority: `docs/EXECUTION_PLAN.md`,
`configs/mantis-port-config.json`, and
`receipts/amd-act-closedloop-g3-multiseed-final-20260726-v1/`

## Phase objective

Produce a falsifiable root-cause classification for the frozen ACT G3 failure
families while advancing the asset-licensing and public-submission paths
without weakening the evaluation protocol or overstating robot capability.

## Entry criteria

- The official-AMD ACT v2 60,000-step optimization is terminal and verified.
- Open-loop inference admission passed.
- Exact G3 seeds 101–110 completed with 0/10 strict successes, eight
  `timeout` outcomes, and two `collision_safety` outcomes.
- Both G3 final-evidence manifests pass independent integrity checks.
- The local contract validator and current 702-test regression suite pass.
- One frozen, single-GPU 4090 ACT correction run completed at 60,000 steps;
  its representative evaluation package is frozen but not launched. Unrelated
  GPU processes remain out of scope.

## Dependency graph

```text
AMD G3 terminal evidence
        |
        v
WP-G3-ATTR-001 evidence/replay feasibility inventory
        |
        +--> missing-input manifest --> evidence transfer work package
        |
        +--> replay-ready -----------> bounded diagnostic replay
                                          |
                                          v
                              versioned controller/policy correction
                                          |
                                          v
                               fresh official-AMD exact-seed G3

Public license audit --> authorization request / externalized asset path
Submission skeleton --> final report/video/reproduction package
```

## Work packages

### WP-G3-ATTR-001 — failure-evidence and replay-feasibility inventory

Objective: determine whether the 4090 host contains every artifact required to
reproduce and localize the G3 collision and timeout families.

Authoritative inputs:

- Local final receipt:
  `receipts/amd-act-closedloop-g3-multiseed-final-20260726-v1/`
- 4090 G3 project:
  `/data01/suzw_data/tron/amd_track3/mantis_rocm_bridge_v121`
- 4090 auxiliary G3 package:
  the versioned 2026-07-26 multi-seed development mirror
- Frozen 4090 dataset:
  `/data01/suzw_data/tron/amd_track3/datasets/mantis_stack_bowls_multiseed4_gripper_v2_20260726_v1`
- Expected AMD checkpoint:
  `/workspace/mantis_act_rocm_multiseed4_20260726_v2/checkpoints/060000`

Deliverable manifest:

- Remote report root:
  `/data01/suzw_data/tron/amd_track3/ops/g3_failure_attribution_20260727_v1`
- `inventory.json`
- `replay_feasibility.md`
- `required_transfer_manifest.json`
- `source_files.SHA256SUMS`
- `final_evidence.SHA256SUMS`

Acceptance criteria:

1. No GPU workload, simulation replay, training, or inference is launched.
2. The report identifies the exact project, checkpoint, asset, dataset, and
   per-seed trajectory artifacts required for collision and timeout diagnosis.
3. Every present input is hashed; every missing input has a source path,
   destination path, purpose, and minimum required subset.
4. The report distinguishes code-level static hypotheses from replay-verified
   root causes.
5. The remote root is fresh and no existing evidence is overwritten.

Terminal condition: `replay_ready=true` with all required inputs present, or
`replay_ready=false` with a complete transfer manifest.

### WP-LIC-001 — Mantis public-distribution authorization path

Objective: convert the existing negative public-license audit into an
actionable, submission-safe authorization package.

Deliverable manifest:

- `docs/MANTIS_ASSET_AUTHORIZATION_REQUEST.md`
- updated `third_party/ASSET_LICENSES.md`
- updated `submission/README.md` asset boundary

Acceptance criteria:

1. Current public repository state is dated and source-backed.
2. The request identifies the exact repositories and permitted acts:
   competition source publication, Docker/runtime materialization, derived
   fixed-base URDF, screenshots, and demo video.
3. No authorization is implied, no legal conclusion is invented, and no
   message is sent.
4. The fallback remains an external hash-pinned materialization with no Mantis
   URDF or mesh redistribution.

Terminal condition: a user-reviewable authorization request and a complete
licensed/externalized asset matrix exist.

### WP-SUB-001 — public submission package skeleton

Objective: make every official Track 3 deliverable structurally present and
traceable to verified evidence while preserving the negative G3 result.

Deliverable manifest:

- refreshed `submission/README.md`
- `submission/README.zh-CN.md`
- `submission/TECHNICAL_REPORT.md`
- `submission/EVIDENCE_MATRIX.md`
- `submission/VIDEO_STORYBOARD.md`
- `submission/PUBLICATION_CHECKLIST.md`

Acceptance criteria:

1. English remains the primary submission language and the Chinese README is a
   faithful navigation mirror.
2. The technical report covers task, architecture, data, AMD training,
   inference, closed-loop evaluation, migration contributions, application
   value, limitations, and individual contribution.
3. G3 is reported exactly as 0/10, eight timeouts, and two
   `collision_safety` failures; training loss is not presented as task
   success.
4. No credential, private deployment payload, Mantis asset, dataset,
   checkpoint, or file over 100 MB is included.
5. Every quantitative claim maps to a receipt or is explicitly marked
   `TODO-evidence`.

Terminal condition: all six skeleton files exist, contain no unsupported
claims, and pass link, secret, and prohibited-payload audits.

## Claim boundary

This sprint may establish diagnostic readiness, a licensed submission path, and
submission-document completeness. It cannot establish a G3 pass, policy
generalization, G4 robustness, real-robot safety, training convergence, or an
AMD performance advantage.

## Execution status — 2026-07-27

| Work package | Status | Evidence / next gate |
|---|---|---|
| `WP-G3-ATTR-001` | **Transfer and extraction complete** | Exact 194,583,158-byte archive and SHA-256 verified; all 334 substantive files pass in the fresh remote extraction; receipt `receipts/g3-r1r2-transfer-extraction-20260727-v1/` |
| `WP-G3-ATTR-002` | **Static, dynamic, and commanded-target attribution complete** | CUDA seeds 101/107/108 reproduce timeout and right-wrist collision families with exact clock/queue chronology; commanded ACT targets for 107/108 enter the same collision family in `receipts/g3-commanded-target-counterfactual-20260727-v2/` |
| `WP-G3-CORR-001` | **Six-seed correction admitted; 60k CUDA training complete** | Exit codes 0/0; exact twelve 5k milestones through 60k; 132 output files and terminal evidence verify in `receipts/4090-act-multiseed6-training-final-20260727-v1/` |
| `WP-G3-CORR-002` | **Representative evaluation frozen; not launched** | Exact checkpoint plus seeds 101/107/108, per-seed safety non-regression, strict improvement, code gate, and single-GPU supervisor are frozen in `docs/G3_CORRECTIVE_ACT_REPRESENTATIVE_EVAL_V1.md` |
| `WP-AMD-CORR-PREP-001` | **Prepared; execution blocked** | `configs/act-rocm-corrective-multiseed6-v1.json` and `docs/AMD_ACT_CORRECTIVE_TRAINING_GATE_V1.md` freeze the six-seed single-Radeon run; CUDA terminal status `COMPLETE_PROMOTABLE` is mandatory |
| `WP-LIC-001/002` | **Pre-send package complete; no grant received** | `docs/MANTIS_ASSET_AUTHORIZATION_REQUEST.md`, `third_party/ASSET_LICENSES.md`, `receipts/asset-license-public-audit-20260727-v2/` |
| `WP-SUB-001/002` | **Evidence-backed draft and terminal candidate verified; release blocked** | Six-seed CUDA completion, prepared AMD gate, individual-entry attribution boundary, license decision record, and revised video narrative are documented; current authority is `receipts/publication-candidate-preflight-20260727-v5/`; project LICENSE, clean-room execution, final video, participant name, public repository, and official PR remain open |

The working tree contains a local 385,607,680-byte dataset transfer archive
under `artifacts/transfers/`. The fail-closed allowlist excludes it and every
other file over 100 MB from the v2 candidate. That candidate is not releasable
until its remaining promotion gates pass and the final tree is rescanned.

### Next critical sequence

1. Pass the corrective representative package's CPU/source/checkpoint code
   gate without starting GPU work on failure.
2. Revalidate the single correction on representative seeds 101/107/108,
   sequentially on physical GPU0.
3. Promote only an evidence-complete, improved, safety-nonregressing result to
   the prepared six-seed official-AMD training package; run fresh dataset
   gates, 60k training, and open-loop admission in that order.
4. Run a fresh official-AMD exact-seed G3 only after the corrective checkpoint
   passes open-loop admission, under unchanged acceptance criteria.
5. In parallel, obtain or explicitly forgo Mantis redistribution permission
   and assemble an allowlisted clean-room public package.
