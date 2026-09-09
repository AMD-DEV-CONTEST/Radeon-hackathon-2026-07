# ChronoSafe-Drive Submission Checklist

This checklist is a release gate. A checked item must be supported by a file,
URL, command output, or committed machine-readable result.

## 1. Competition eligibility

- [x] The final repository is forked from the official competition repository.
- [x] The submission is delivered through the required pull-request workflow.
- [x] The project is entered in Track 3: Physical AI.
- [x] The README explicitly identifies AMD Radeon and ROCm usage.
- [x] Training and inference evidence is generated on an AMD Radeon GPU.
- [x] The selected simulator and all models are open source.
- [x] Dataset licenses and terms are documented and respected.
- [x] Wang Zhenyu has separately registered for the AMD AI Developer Program.
- [ ] Wang Guanyu has separately registered for the AMD AI Developer Program.
- [ ] Han Liuxuan has separately registered for the AMD AI Developer Program.

## 2. English-only public materials

- [x] Root README is English only.
- [x] Dataset card is English only.
- [x] Experiment protocol is English only.
- [x] Technical report is English only.
- [x] Demo subtitles and on-screen script are English only.
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
- [x] README contains the five required sections: project overview, development
  process, code provenance, team contributions, and installation/running.
- [x] MIT License includes the year and all three team-member names.
- [x] Reviewers can verify the frozen submitted results from the public repo.
- [ ] A public video no longer than 3 minutes shows commands or GUI actions,
  execution, and
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
- [x] Every headline table is cross-checked against committed evidence by the
  118-check submission verifier.

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
- [x] Recorded dashboard footage uses unseen frozen seed `149`.
- [x] The final edit plan labels fault onset, MRM trigger, and near-stop.
- [x] The 3:00 subtitle track states that the threshold was frozen before
  external testing.
- [x] The final edit plan includes the 20-seed aggregate rather than a selected
  run alone.
- [ ] Exported video duration is no longer than 3 minutes.
- [x] Recorded footage shows the actual AMD command-line workflow and output.
- [ ] Final frame shows the GitHub repository and team contact.

## 7. Repository release quality

- [x] All five unit tests pass in the supplied project environment.
- [x] All 34 Python files pass syntax validation.
- [ ] Quick-start commands are re-run from a clean terminal.
- [x] No raw nuScenes media is committed.
- [x] No cloud credentials, tokens, cookies, or private URLs are committed.
- [x] Small selected checkpoints are committed as public artifacts.
- [x] Large generated datasets are excluded and have regeneration instructions.
- [x] Split manifests and hashes are committed.
- [x] Selected evidence is trackable and not excluded by `.gitignore`.
- [x] No repository file exceeds 100 MiB.
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

- [x] One-sentence problem statement is understandable without reading code.
- [x] Exactly three innovations are emphasized consistently.
- [x] The demo connects diagnosis to risk calibration and physical control.
- [x] Application value is tied to fail-safe autonomy.
- [x] Limitations and non-certification are stated clearly.
- [x] Every headline metric names its test split and sample/run count.
- [x] No claim implies that AMP accelerates every batch size.

## 10. Final submission record

- [x] Official GitHub pull-request URL recorded.
- [ ] Upstream issue/pull-request URL recorded.
- [ ] Demo video URL recorded.
- [ ] Model/checkpoint download URL recorded.
- [ ] Optional ModelScope project URL recorded if used.
- [ ] Submission confirmation screenshot saved outside the repository.
- [ ] Final repository commit hash recorded below.

```text
Submitted commit:
Competition PR: https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/pull/113
Upstream contribution:
Demo video:
Model artifact:
ModelScope page:
```
