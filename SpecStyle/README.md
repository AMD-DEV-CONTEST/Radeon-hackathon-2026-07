# SpecStyle

SpecStyle is a StyleOps engine for AMD Radeon GPUs. It compiles a versioned
Style Spec into generation and verification plans, runs a local SDXL pipeline,
routes verified artifacts, and publishes an auditable export bundle.

The implementation keeps three planes separate:

- Generation controls: SDXL img2img, IP-Adapter style conditioning, and Canny
  ControlNet structure conditioning.
- Verification: deterministic L1 checks plus separately versioned L2/L3
  contracts. ControlNet is never treated as a verifier.
- Repair policy: allow-listed rule-to-action decisions, guardrails, bounded
  retries, and full re-verification.

## Current verified scope

The following path has been exercised on an AMD Radeon ROCm 7.2.1 runtime:

1. Load a local-only, hash-verified SDXL base, IP-Adapter Plus SDXL ViT-H, and
   ControlNet Canny supply.
2. Upload one source image, one style reference, and one Style Spec through the
   authenticated Gradio application.
3. Run an isolated LCM Preview or a Production job. Preview can publish a
   sequential one-to-four variation engineering wall from one staged input set.
4. Observe live persisted job status, request cancellation, and display approved
   and rejected outputs, QA rows, deterministic seed evidence, and the published
   bundle digest.

The current AMD candidate is `fd4e45b`. It serves 71 Gradio components on the
isolated candidate port and passed 1,009 affected AMD tests with one capability
skip, plus repository-configured Ruff check and format gates. The stable
`657ac0b` service remained online during candidate validation.

The Radeon runtime used PyTorch `2.9.1+gitff65f5b` with HIP
`7.2.53211-e1a6bc5663` and Diffusers `0.39.0`. Real GPU evidence was collected
on the following commits, all of which are ancestors of the current candidate:

- `fd4e45b`: an actual browser-driven Gradio Preview uploaded the source, style
  reference, and Spec, refreshed readiness, and generated a four-seed wall. The
  UI completed in 65.38 seconds; the workflow manifest reports four completed
  items, four unique content hashes, zero failures, and completed cleanup. All
  four outputs are visible in one row. This is engineering execution evidence;
  quality and diversity remain `NOT_EVALUATED`.
- `4cc3da8`: the strict local LCM Preview loader completed a Radeon N=4 wall
  while preserving the reusable SDXL/Canny/IP-Adapter/LCM-LoRA runtime integrity
  contract. Preview evidence records deterministic seeds, content hashes,
  execution fingerprints, FP16 at-rest VAE state, FP32 VAE compute, and the
  Diffusers force-upcast round trip.
- `a3832be`: one interactive job traversed `OPENING`, `GENERATING`,
  `VERIFYING`, `CLEANUP`, and `COMPLETED`; controls stayed responsive during
  generation. A separate real job was cancelled during `GENERATING` and
  published no bundle.
- `ec1e27d`: a two-item engineering smoke completed with distinct deterministic
  seeds and artifact hashes. This proves batch wiring, not calibrated
  perceptual diversity.
- `ec1e27d`: two new synthetic source materials reused the same Spec, style
  reference, compiler graph, rules, and environment and both completed. This is
  new-material contract reuse, not same-input semantic replay.
- `597642e`: a successful Production job established an in-process baseline,
  then Replay submitted the same nine form inputs into a new job and immutable
  bundle. The assessment was `EXACT`: both runs used seed
  `4493853825484117685`, L2 style score `0.9241587906927828`, and L2 delta
  `0/0`; L3 remained truthfully `NOT_APPLICABLE` with `NO_L3_CONFIG`. The two
  artifact hashes happened to match, but pixel equality is diagnostic and is
  not required by the semantic replay contract. Replay baselines are
  process-local and must be re-established after a UI restart.
- `6f78974`: `xhs_grid` job `run-one-2ac378454d6b4849be2f82d68c1b5ffc`
  completed and exported an approved `1080x1080` PNG.
- `e06d0ae`: `talking_head_cover` job
  `run-one-c9fc95a5afee42eab410dede99c832dd` completed and exported an
  approved `1080x1440` PNG.
- `2be6547`: `background_sequence` job
  `run-one-77e54905ae7c4d0a88d8e2d7f1bd6c4d` completed and exported an
  approved `1920x1080` PNG with single-item sequence semantics.

The checked-in competition pack contains the English Project Profile source,
sanitized Radeon evidence, media provenance, a rendered PDF, a presentation,
and a 3-5 minute demo video under
[`submission/track1-specstyle/`](submission/track1-specstyle/).

The pack also includes two complementary Radeon walls: a retained
Production-profile N=4 stability run whose formal threshold status remained
`DRAFT`, and a commit `4482837` Bold Preview N=4 run with visibly stronger
creative variation. Both are explicitly bounded as engineering evidence; no
calibrated L2/L3 or human-rated perceptual-diversity result is claimed.

## Evidence boundaries and remaining evaluation work

- Preview is a separate LCM execution profile and never enters the approved
  Production package. Its current N=4 wall is engineering evidence, not a
  calibrated quality or diversity result.
- L2 remains advisory until real held-out human annotations replace the current
  placeholder calibration evidence. The formal item/cohort evidence and atomic
  batch paths are CPU-validated, but no universal L2 threshold is claimed.
- A pinned `structure_only` edge-similarity L3 implementation and context v4
  contract are CPU-validated. No calibrated L3 profile is enabled;
  `NOT_APPLICABLE` and `UNVERIFIABLE` are not presented as `PASS`.
- A real failure-to-repair-to-reverification Radeon comparison, five-arm
  equal-budget ablation, and blind human evaluation require approved held-out
  assets, independent labels, and a trusted Production threshold package. The
  code paths and fail-closed evidence protocol exist; the empirical result is
  not claimed.
- The post-`2be6547` Production `VALIDATED` evidence gate has CPU verification
  but has not been exercised against an approved threshold package on Radeon.

## Repository layout

```text
deployment/amd/                 AMD environment probe, lock, and launcher
src/specstyle/generation/       generation contracts and Diffusers adapter
src/specstyle/spec/             schema, loader, compiler, migration, replay
src/specstyle/verification/     L1, L2, L3, routing
src/specstyle/repair/           actions, policy, guardrails, bounded loop
src/specstyle/workflow/         job state, production runtime, export lifecycle
src/specstyle/ui/               injectable Gradio application
tests/                          CPU-safe unit, property, and integration tests
```

## AMD runtime requirements

- Linux with CPython 3.12.
- ROCm 7.2.1 and a working PyTorch HIP installation supplied by the AMD image.
- A Radeon device visible through `torch.cuda` and capable of FP16 execution.
- Local model weights and the matching model descriptors, weight manifests,
  license approvals, and compiler context under the runtime root.

Do not install a generic PyPI `torch`, `torchvision`, or `torchaudio` wheel. The
installer deliberately uses `--no-deps`, rejects those package names, and checks
that the AMD image's Torch binaries did not change.

## Install pinned application dependencies

The checked-in runtime lock is
[`deployment/amd/requirements.lock.txt`](deployment/amd/requirements.lock.txt).
It is synchronized with the guarded installer by a unit test.

```bash
cd /path/to/lookfile
export PYTHONDONTWRITEBYTECODE=1
install -d -m 700 /workspace/persistence/lookfile-runtime/reports/install

/opt/venv/bin/python deployment/amd/scripts/probe_environment.py \
  --phase pre \
  --repo-sha "$(git rev-parse HEAD)" \
  --json-out /workspace/persistence/lookfile-runtime/reports/install/pre.json

/opt/venv/bin/python deployment/amd/scripts/install_dependencies.py \
  --repo-sha "$(git rev-parse HEAD)" \
  --json-out /workspace/persistence/lookfile-runtime/reports/install/install.json

/opt/venv/bin/python deployment/amd/scripts/probe_environment.py \
  --phase post \
  --baseline-json /workspace/persistence/lookfile-runtime/reports/install/pre.json \
  --repo-sha "$(git rev-parse HEAD)" \
  --json-out /workspace/persistence/lookfile-runtime/reports/install/post.json
```

All evidence paths must be canonical absolute paths. Each command exits nonzero
when the host, GPU, dependency, or Torch-integrity contract fails.

## Runtime layout

The launcher expects this layout by default:

```text
/workspace/persistence/lookfile-runtime/
  config/
    context.json
    models.json
    weight_manifests.json
    license_approvals.json
  evidence/
    sha256/<first-two-hex>/<full-sha256>
  models/<manifest-relative-root>/
  jobs/         private job state and artifacts
  tmp/          private upload staging
```

The four JSON files are mandatory. `context.json` supports
`specstyle.production.context.v1`, `.v2`, `.v3`, and `.v4`; the other files use
the `specstyle.production.models.v1`,
`specstyle.production.weight_manifests.v1`, and
`specstyle.production.license_approvals.v1` schemas. Every evidence digest in
`context.json` must resolve to a regular content-addressed file at the path
shown above. Every model descriptor, manifest, approval, local file hash, role,
revision, and license identifier must close over the same local supply.

These files are not generic examples: model manifests depend on the exact local
weight bytes, license approval is a human decision, and calibrated threshold
evidence must come from the approved annotation workflow. The repository does
not currently contain a fresh-runtime supply/calibration package generator.
Copy an independently approved package into these paths before launching; the
bootstrap intentionally fails closed when any file, approval, hash, permission,
or evidence object is absent. Do not reuse the engineering smoke threshold
markers as calibration evidence.

Context v1/v2 remain compatible for `DRAFT` and `CALIBRATED` thresholds, but
they cannot claim `VALIDATED`. A v3 `VALIDATED` threshold is intentionally
limited to one `product_instance` output profile and one metric. It requires a
pinned metric implementation and four canonical, content-addressed objects:
prepared evidence, test reveal, annotation protocol, and a Production approval.
The loader cross-binds their hashes, style/domain/output and output pin,
threshold pin, metric/operator/value/implementation pin, verifier pin, and
preprocessor pin. It then matches the verified encoder at factory creation and
the loaded preprocessing provenance before the runtime becomes ready. Any
missing or mismatched field fails closed; the loader never generates approval,
rewrites evidence, or downgrades status.

The Production approval is an owner-only trusted-administrator record, not a
digital signature or third-party identity proof. Non-`VALIDATED` v3 contexts
must set `production_approval_sha256` to JSON `null`.

## Prepare held-out calibration evidence

The offline calibration entry point consumes canonical, precomputed JSON
observations. It does not read source images, run a model, create approval
receipts, modify `context.json`, or automatically select the Production
evidence root. Operators must keep `--out` in a private review directory.
Test observations remain sealed during `prepare` and require a separately
approved `reveal-test` action.

```bash
PYTHONPATH="$PWD/src" python -m specstyle.calibration.evidence prepare \
  --study-plan /approved-input/study_plan.json \
  --annotation-protocol /approved-input/annotation_protocol.json \
  --sample-manifest /approved-input/sample_manifest.json \
  --calibration-observations /approved-input/calibration_observations.json \
  --validation-observations /approved-input/validation_observations.json \
  --test-commitment /approved-input/test_commitment.json \
  --label-approval-receipt /approved-input/label_approval_receipt.json \
  --out /private-output/prepared_evidence.json

PYTHONPATH="$PWD/src" python -m specstyle.calibration.evidence reveal-test \
  --prepared-evidence /private-output/prepared_evidence.json \
  --test-observations /approved-input/sealed_test_observations.json \
  --reveal-authorization-receipt /approved-input/reveal_receipt.json \
  --out /private-output/test_reveal.json
```

Malformed, non-canonical, cross-split, or hash-inconsistent evidence is
rejected. Synthetic or unapproved labels produce a persistent `BLOCKED`
report. Numeric validation success is named `VALIDATION_PASSED`; a successful
test reveal is still only `TEST_PASSED_PENDING_PRODUCTION_APPROVAL`. Neither
status is a Production `VALIDATED` threshold. The current repository includes
no approved human label set, reveal authorization, or Production threshold
approval, so the competition calibration claim remains blocked.

For the three-metric context v4 process, use the English operator kit at
[`submission/track1-specstyle/formal-study-kit/`](submission/track1-specstyle/formal-study-kit/).
It defines the independent rater/label/reveal/Production approval roles, exact
item and complete-cohort templates, minimum study sizes, provenance register,
and the fail-closed `formal_study_workspace` prepare/reveal/validate commands.
The kit contains no approved labels and cannot make a metric `VALIDATED` by
itself.

The `config/` and `evidence/` directories, the four JSON files, and every
evidence object must be owned by the service process's effective user. The
runtime root and `models/` may be owned by root or that service user. None of
these paths may be group- or world-writable. Mutable job directories are
created with mode `0700`; the four config files and each evidence object must
use mode `0600`.

## Launch the UI

Local-only mode does not require application credentials:

```bash
cd /path/to/lookfile
PYTHONPATH="$PWD/src" /opt/venv/bin/python \
  deployment/amd/scripts/launch_production_ui.py \
  --runtime-root /workspace/persistence/lookfile-runtime \
  --host 127.0.0.1 \
  --port 7860
```

Binding to `0.0.0.0` requires both credentials. Use it only behind the AMD
platform's HTTPS reverse proxy:

```bash
export SPECSTYLE_UI_USERNAME='<username>'
export SPECSTYLE_UI_PASSWORD='<at-least-16-characters>'
PYTHONPATH="$PWD/src" /opt/venv/bin/python \
  deployment/amd/scripts/launch_production_ui.py \
  --runtime-root /workspace/persistence/lookfile-runtime \
  --host 0.0.0.0 \
  --port 7860
```

The UI returns only published bundle paths. Gradio allowlists the export root;
config, evidence, weights, job state, materialized artifacts, style assets, and
upload staging are explicitly blocked.

## Validation

With the pinned dependencies available:

```bash
export PYTHONPATH="$PWD/src"
export PYTHONDONTWRITEBYTECODE=1
python -m pytest -q
ruff check .
ruff format --check .
```

CPU unit tests use deterministic fakes. Production tests validate supply,
filesystem, workflow, routing, cleanup, and export contracts without downloading
weights. Radeon smoke evidence must be collected separately on the target AMD
runtime.

## Security and licensing

- Never commit model weights, credentials, private images, or unlicensed media.
- A code license does not grant a model-weight license. Every Production model
  requires an independently recorded revision, content hash, SPDX identifier,
  and approval evidence before it can load.
- Failed required gates route to `rejected/`; manual decisions remain separate;
  only the automatic whitelist state can enter `approved/`.
- ControlNet preserves a spatial condition. It does not establish identity.
