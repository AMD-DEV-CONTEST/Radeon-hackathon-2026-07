# SpecStyle Project Profile

## Project background

Creative teams often reproduce a visual direction by manually copying prompts,
sliders, and reference images. That process is difficult to audit, inconsistent
across creators, and weak at explaining why an output should be accepted or
rejected. SpecStyle treats visual direction as an executable, versioned contract
rather than a loose preset.

SpecStyle is a StyleOps engine running local inference on AMD Radeon through
ROCm. A Style Spec pins the model supply, assets, generation parameters,
verification rules, output profiles, and repair policy. The same Spec can be
compiled, replayed, and compared without silently mixing generation controls
with quality gates.

## Users and scenarios

- Brand and social-content teams that need repeatable visual direction across
  people and batches.
- MCNs and studios producing platform-specific image packages with audit-ready
  approved and rejected routing.
- Individual creators who want a fast Preview profile and a separately governed
  Production profile.
- Evaluation operators who need immutable inputs, deterministic seed evidence,
  explicit unverifiable states, and held-out calibration controls.

The primary workflow is: upload a source, a licensed style reference, and a
Style Spec; compile Preview and Production graphs; generate locally; evaluate
the applicable rules; apply bounded repair when policy allows; re-verify; then
export an approved package while isolating rejected and manual-review results.

## Architecture

SpecStyle keeps three planes separate:

1. Generation controls use SDXL img2img, IP-Adapter style conditioning, and
   Canny ControlNet structure conditioning. ControlNet is not a verifier.
2. Verification uses deterministic L1 checks, style/domain-versioned L2
   contracts, and domain-specific L3 plugins. Missing evidence produces
   `NOT_APPLICABLE` or `UNVERIFIABLE`, not a false pass.
3. Repair policy maps allow-listed rule failures to bounded actions, resolves
   conflicts by priority, enforces guardrails, and requires re-verification.

The compiler emits distinct graphs. Preview uses a local LCM-LoRA SDXL adapter
at 512 x 512 and four steps for direction feedback. Production uses the pinned
SDXL base path and separately governed output profiles. Preview outputs never
enter the Production approved package.

The workflow layer owns immutable job state, cancellation, sequential batches,
replay, export lifecycle, and audit records. The Gradio application injects
these services instead of embedding generation or verification policy in UI
callbacks.

## Models and algorithms

- SDXL base for the shared latent image-generation family.
- IP-Adapter Plus SDXL ViT-H for style-reference conditioning.
- ControlNet Canny for spatial structure control.
- LCM-LoRA SDXL plus `LCMScheduler` for the isolated Preview profile.
- Deterministic `specstyle.seed.v1` seed derivation and content-addressed
  execution evidence.
- L1 image decode, dimensions, pixels, layout, and text-overlay contracts.
- L2/L3 interfaces that require versioned evidence and fail closed when the
  approved calibration package is absent.
- Allow-listed repair actions with parameter bounds, conflict priority, retry
  limits, history, and full affected-rule re-verification.

Every runtime model is local-only and must match an immutable descriptor,
revision, manifest, file hash, role, family, and license approval. Model weights
and approval records are deployment inputs and are not committed.

## AMD and ROCm implementation

The verified candidate is
`fd4e45b3e62a837d4a613473abc9310ce0c9a1b4`. It ran on the AMD competition
instance with ROCm 7.2.1, PyTorch `2.9.1+gitff65f5b`, HIP
`7.2.53211-e1a6bc5663`, Diffusers 0.39.0, and Gradio 6.15.1.

The guarded installer pins application dependencies, uses `--no-deps`, rejects
generic `torch`, `torchvision`, and `torchaudio` packages, and compares the
pre/post AMD Torch installation. The local-only loaders validate descriptors,
weight manifests, file hashes, license approvals, scheduler identity, adapter
topology, dtype, and the reusable pipeline integrity contract before publishing
an artifact.

An actual browser-driven Gradio run uploaded the source, style, and Spec,
confirmed Preview readiness, and requested four seeds. The UI completed in
65.38 seconds. Its wall manifest reports four completed items, four unique
content hashes, zero failures, and completed runtime cleanup. The candidate
passed 1,009 focused AMD tests with one capability skip; repository-configured
Ruff check and format also passed. The stable service remained available during
candidate validation.

## Evidence and current boundaries

The submission includes the uncut raw UI recording, the completed UI screen,
four output files, their deterministic seeds, content hashes, execution
fingerprints, and sanitized environment records. The captured wall is labeled
`ENGINEERING_ONLY`; its quality and diversity fields remain `NOT_EVALUATED`.

Production examples previously completed and exported the `xhs_grid`
1080 x 1080, `talking_head_cover` 1080 x 1440, and `background_sequence`
1920 x 1080 profiles. Replay also produced an `EXACT` semantic assessment for
one pinned Production input set.

No calibrated L3 plugin is enabled. L2 cannot become a Production gate until an
approved held-out human-label workflow supplies the prepared evidence, test
reveal, protocol, and Production approval. A real Radeon
failure-to-repair-to-reverification comparison, equal-budget five-arm ablation,
and blind human evaluation remain empirical work rather than submission claims.

## Repository and run instructions

Source: <https://github.com/GuanJHCode/lookfile>

The root README contains the pinned dependency installation, AMD pre/post
environment probes, private runtime layout, security requirements, calibration
CLI, launch commands, and validation commands. No credentials, private media,
model weights, or unapproved threshold package are included in this submission.
