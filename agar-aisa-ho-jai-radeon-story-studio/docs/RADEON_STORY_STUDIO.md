# AMD DevMaster - Radeon Story Studio

Radeon Story Studio is AAHJ's Track 1 CLI workflow for generating and accepting
child-safety storyboards on an AMD Radeon GPU through ROCm. The project uses the
existing deterministic Radeon Cloud package, preflight, transport, and returned
artifact verification as its execution authority.

## Competition boundary

- Core image inference runs locally in Radeon Cloud on AMD Radeon GPU.
- PyTorch, Diffusers, and ROCm perform the key inference process.
- No closed-source online inference API implements the core function.
- Hugging Face is used only to retrieve the declared model artifacts.
- The model revision is pinned to an immutable commit.
- Every warm-up image, candidate, report, review, and final artifact is hashed.
- Generated candidates remain unaccepted until explicit editorial review.

Credit 1 findings, including the rejected calibration batch and the dtype
reporting correction, are documented in
[`CREDIT_1_FINDINGS.md`](CREDIT_1_FINDINGS.md).

## Why the workflow is modular

A single prompt that combined a child, damaged electrical equipment, distance,
an adult, and several negated actions produced unsafe or contradictory images.
Story Studio v2 does not rely on negated prompt language as a safety boundary.
Instead, it separates the workflow into content classes:

1. a canonical character reference;
2. a hazard-only panel containing no person;
3. a reference-conditioned child reaction containing no hazard;
4. a reference-conditioned child-and-adult panel containing no hazard.

The example manifest requires one character lineage across all selected panels.
A candidate cannot enter the final storyboard until technical, safety, semantic,
and continuity review passes.

## Story Studio v2 outputs

A Radeon run produces:

```text
outputs/
├── candidates/                 # generated candidates, grouped by lineage
├── evidence/                   # unmeasured warm-up images
├── contact-sheet.png
├── review-template.json        # fail-closed; editorial statuses start pending
└── run-report.json             # runtime, dtype, timing, memory, and hashes
```

After human review, local finalization produces:

```text
accepted/
├── selected/                   # one accepted candidate per scene
├── accepted-storyboard.png
├── acceptance-report.json      # all four acceptance dimensions must pass
└── rejected-candidates.json    # hashes and reasons; no rejected images embedded
```

## Local preparation - no GPU credit

Validate the sealed manifest:

```bash
python3 tools/episode_factory/amd_story_studio.py validate \
  examples/story-studio-manifest.json
```

Prepare a deterministic Radeon Cloud package. The validated ROCm Python path
observed during Credit 1 was `/workspace/aahj-rocm-venv/bin/python`; verify it
again on a fresh instance rather than assuming it still exists.

```bash
rm -rf /tmp/aahj-amd-devmaster-demo

python3 tools/episode_factory/manage_amd_story_studio.py prepare \
  --manifest examples/story-studio-manifest.json \
  --output-directory /tmp/aahj-amd-devmaster-demo \
  --remote-python /workspace/aahj-rocm-venv/bin/python

python3 tools/episode_factory/manage_amd_story_studio.py inspect-package \
  /tmp/aahj-amd-devmaster-demo/execution-package.tar.gz
```

## Radeon Cloud environment

The Credit 1 template provided local ROCm 7.2.1 PyTorch and Triton wheels but no
preinstalled `torch` package. The successful isolated environment used:

```text
/workspace/aahj-rocm-venv
```

Do not replace a working ROCm PyTorch installation with a generic PyPI wheel.
Install only the application dependencies from
`requirements-amd-hackathon.txt` into the validated environment.

A valid probe must report:

- a non-empty `torch.version.hip`;
- `torch.cuda.is_available()` equal to `True`;
- at least one device;
- an AMD Radeon device name;
- a successful tensor operation on `cuda:0`.

The `torch.cuda` spelling is PyTorch's device API for both CUDA and ROCm; the HIP
version proves that this run uses ROCm.

## Execute through verified transport

After attaching the Radeon Cloud workspace as documented in
`docs/RADEON_CLOUD_SESSIONS.md`:

```bash
python3 tools/episode_factory/manage_radeon_cloud_session.py probe-ssh \
  local/radeon-cloud/session.json

python3 tools/episode_factory/manage_radeon_cloud_session.py run-remote \
  local/radeon-cloud/session.json \
  /tmp/aahj-amd-devmaster-demo/execution-package.tar.gz \
  --destination /tmp/aahj-amd-devmaster-demo/result

python3 tools/episode_factory/manage_amd_story_studio.py verify-result \
  /tmp/aahj-amd-devmaster-demo/result/result.json \
  --result-root /tmp/aahj-amd-devmaster-demo/result
```

## Dtype truthfulness

Story Studio v2 loads Diffusers with `torch_dtype=` and records the actual dtype
of:

- UNet;
- primary text encoder;
- secondary text encoder when present;
- VAE.

The VAE remains in its loaded dtype during ordinary inference. Diffusers may
coordinate a decode-time upcast when the selected pipeline requires it; AAHJ
records the observed component dtypes instead of forcing a partial VAE
conversion.
Technical acceptance fails when the requested core dtype is not verified. A
manifest field by itself is never runtime proof.

## Warm-up and benchmark separation

The run performs the configured unmeasured warm-up images before collecting
candidate timings. The report separates:

- model load time;
- warm-up time;
- measured candidate time;
- mean, median, and p95 candidate latency;
- measured candidates per minute;
- peak allocated and reserved GPU memory.

This prevents first-use compilation from being silently mixed into the warm
throughput claim.

## Human review and finalization

Open the returned `review-template.json`. For every candidate:

1. Preserve `candidate_id`, `output_sha256`, and `technical` exactly.
2. Set `safety`, `semantic`, and `continuity` to `pass` or `reject`.
3. Select exactly one candidate for every scene.
4. Give every non-selected candidate at least one rejection reason.
5. Use one lineage consistently across the character reference and story panels.
6. Fill `reviewer` and `reviewed_at`.

Then finalize locally:

```bash
python3 tools/episode_factory/manage_amd_story_studio.py finalize \
  --manifest examples/story-studio-manifest.json \
  --run-report /path/to/outputs/run-report.json \
  --review /path/to/outputs/review-template.json \
  --output-directory /tmp/aahj-amd-devmaster-accepted
```

Finalization fails closed for a modified report, modified candidate, pending
status, rejected selected candidate, missing scene, duplicate selection, or
mixed character lineage.

## Submission evidence boundary

Do not publish unsafe rejected images as contest artwork. The public submission
may include:

- the accepted storyboard;
- the accepted source images;
- the acceptance report;
- metadata-only rejected candidate hashes and reasons;
- the benchmark report and ROCm runtime evidence.

The complete private Credit 1 archive remains outside source control. Its hash
is recorded in
`evidence/sdxl/credit-1-evidence-summary.json`.
