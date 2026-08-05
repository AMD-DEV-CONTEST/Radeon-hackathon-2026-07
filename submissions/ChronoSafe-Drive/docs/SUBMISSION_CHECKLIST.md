# ChronoSafe-Drive Submission Checklist

This checklist is a release gate. A checked item must be supported by a file,
URL, command output, or committed machine-readable result.

## 1. Competition eligibility

- [ ] The final repository is forked from the official competition repository.
- [ ] The submission is delivered through the required pull-request workflow.
- [ ] The project is entered in Track 3: Physical AI.
- [ ] The README explicitly identifies AMD Radeon and ROCm usage.
- [ ] Training and/or inference evidence is generated on an AMD Radeon GPU.
- [ ] The selected simulator and all models are open source.
- [ ] Dataset licenses and terms are documented and respected.

## 2. English-only public materials

- [x] Root README is English only.
- [x] Dataset card is English only.
- [x] Experiment protocol is English only.
- [x] Technical report is English only.
- [x] Demo narration and on-screen script are English only.
- [x] ROCm benchmark plots, tables, and logs are English only.
- [ ] Final video contains no Chinese interface text or captions.
- [ ] Pull-request title and description are English only.

## 3. Required submission materials

- [x] Technical report defines and describes the target application.
- [x] Technical report documents the complete architecture and solution design.
- [x] Technical report documents training/evaluation datasets and split policy.
- [x] Technical report explains AMD Radeon use in training and inference.
- [x] Technical report states innovations and key technical contributions.
- [x] Technical report lists final deliverables and output formats.
- [x] Technical report states each team member's contribution.
- [x] A dedicated source repository structure is prepared.
- [x] Direct dependencies are specified in `requirements.txt`.
- [x] The README and reproducibility guide cover environment setup, execution,
  usage, dependencies, and step-by-step result reproduction.
- [ ] Reviewers can reproduce the submitted results from the final public repo.
- [ ] A public 3-5 minute video shows commands or GUI actions, execution, and
  final results.
- [ ] Optional: a validated Docker image or Dockerfile is provided.

## 4. Scientific validity

- [x] nuScenes split is grouped by complete `log_token`.
- [x] Train, calibration, and test partitions are frozen before final fitting.
- [x] Three training seeds are reported for the robust model.
- [x] MRM threshold `0.62` is selected only on calibration seeds `113` and `127`.
- [x] All 20 external closed-loop seeds are included.
- [x] Confidence intervals and standard deviations are reported where available.
- [x] Standard-versus-robust trade-offs are disclosed.
- [x] Raw-headless renderer-bypass results are excluded.
- [x] Official closed-loop results use Xvfb without the raw-headless effect bypass.
- [ ] Every headline table is cross-checked against its committed JSON file.

## 5. AMD Radeon and ROCm evidence

- [x] GPU name: AMD Radeon Graphics.
- [x] Architecture: `gfx1100`.
- [x] HIP version: `7.2.53211`.
- [x] PyTorch build: `2.9.1+rocm7.2.1`.
- [x] FP32 latency p50/p95/p99 is recorded.
- [x] AMP latency p50/p95/p99 is recorded.
- [x] Batch sizes 1, 32, 256, and 1024 are recorded.
- [x] Peak allocated and reserved memory is recorded.
- [x] AMP/FP32 numerical agreement is verified on real test sequences.
- [x] JSON, CSV, Markdown, and PNG benchmark evidence is preserved.
- [ ] Training log contains visible GPU/ROCm evidence and elapsed time.

## 6. Closed-loop demonstration

- [x] 20/20 external runs reach MRM.
- [x] 20/20 external runs satisfy the near-stop success criterion.
- [x] Premature MRM rate is 0%.
- [x] Aggregate metrics include accuracy, risk MAE, coverage, delay, braking
  time, final speed, and mode fractions.
- [ ] Final dashboard video uses an unseen seed from the frozen list.
- [ ] Video visibly labels fault onset, MRM trigger, and near-stop.
- [ ] Video states that the threshold was frozen before external testing.
- [ ] Video includes the 20-seed aggregate rather than a selected run alone.
- [ ] Video duration is between 3 and 5 minutes.
- [ ] Video shows the actual command-line or GUI workflow, execution, and output.

## 7. Repository release quality

- [ ] `python -m pytest -q` passes in the cloud ROCm environment.
- [ ] All Python files pass syntax compilation.
- [ ] Quick-start commands are re-run from a clean terminal.
- [ ] No raw nuScenes media is committed.
- [ ] No cloud credentials, tokens, cookies, or private URLs are committed.
- [ ] Small selected checkpoints are committed or attached as public artifacts.
- [ ] Large generated datasets are excluded and have regeneration instructions.
- [ ] Split manifests and hashes are committed.
- [ ] Selected evidence is trackable and not excluded by `.gitignore`.
- [x] Repository contains an explicit MIT License selected by the owner.
- [ ] A versioned release/tag identifies the submitted commit.

## 8. Upstream open-source contribution

- [ ] Reproduce the MetaDrive 0.4.3 SimplePBR headless failure from a minimal
  script on AMD ROCm.
- [ ] Document the invalid domain shift caused by bypassing camera effects.
- [ ] Document the validated Xvfb camera path and exact feature equality.
- [ ] Open an upstream issue with environment, traceback, reproducer, and fix
  direction.
- [ ] Submit a focused pull request or documentation patch if maintainers accept
  the proposed direction.
- [ ] Link the issue/PR in the final README and competition submission.

## 9. Final narrative

- [ ] One-sentence problem statement is understandable without reading code.
- [ ] Exactly three innovations are emphasized consistently.
- [ ] The demo connects diagnosis to risk calibration and physical control.
- [ ] Application value is tied to fail-operational or fail-safe autonomy.
- [ ] Limitations and non-certification are stated clearly.
- [ ] Every metric names its test split and sample/run count.
- [ ] No claim implies that AMP accelerates every batch size.

## 10. Final submission record

- [ ] Official GitHub pull-request URL recorded.
- [ ] Upstream issue/pull-request URL recorded.
- [ ] Demo video URL recorded.
- [ ] Model/checkpoint download URL recorded.
- [ ] Optional ModelScope project URL recorded if used.
- [ ] Submission confirmation screenshot saved outside the repository.
- [ ] Final repository commit hash recorded below.

```text
Submitted commit:
Competition PR:
Upstream contribution:
Demo video:
Model artifact:
ModelScope page:
```
