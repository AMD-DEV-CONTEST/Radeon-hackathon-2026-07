# ProofLaunch competition-2X quality contract

## Purpose

`competition_2x` is a measured acceptance tier, not a marketing label. It adds
specialist local models and post-delivery gates to the bounded mission graph,
then refuses certification until every precommitted dataset, reliability,
identity, grounding, and human-preference metric is present.

## Sequential Radeon path

```text
Qwen3-VL understanding
  → unload
GroundingDINO product box
  → unload
Gemma 4 emotion critic
  → unload
SDXL still generation
  → unload
SigLIP2 still semantics
  → unload
LTX-Video 2B image-to-video
  → unload
SAM2 temporal product masks
  → unload
CLAP decoded-audio semantics
  → unload
Deterministic decoded-MP4 identity + A/V timing + cross-media gates
  → human release
```

The 46 GB+ LTX-2.3 path remains a candidate until a matched ROCm run proves
that it is stable on the actual instance. The 24 GB path never silently routes
to a closed online API.

## Mandatory acceptance bars

| Domain | Required bar |
|---|---:|
| Frozen permitted products | ≥30 |
| Output aspect ratios | ≥3: 1:1, 4:5, 9:16 |
| Seeds per product | ≥5 |
| Case-level still results | exactly 450: 30 × 3 × 5 |
| Full audio-video exports | ≥30: one per product |
| Independent human raters | ≥5 |
| Blind publish comparisons | ≥150 |
| Maximum repairs | ≤2 |
| Unsupported claims | 0 |
| Source locator coverage | 100% |
| Still identity pass | 100% |
| Pre-encode video identity pass | 100% |
| Decoded H.264 identity pass | ≥95% |
| Timestamped A/V alignment pass | ≥95% |
| Cross-media pass | ≥95% |
| End-to-end completion | ≥95% |
| Crash rate | ≤2% |
| Valid seed-diversity groups | ≥95% |
| Completion gap versus baseline | ≥0 percentage points |
| Publish preference | ≥60% |
| Publish-preference Wilson 95% lower bound | >50% |

The V7 evidence compiler derives every rate from frozen case-level JSONL,
same-case baseline JSONL, and blinded candidate-hash CSV. The contract rejects
raw aggregate JSON. It also derives preference rate, rating count, and the
Wilson lower bound from the compiled raw counts. Supplying derived percentages
directly cannot satisfy the contract.

## Frozen evidence schemas

1. `products.csv` contains exactly 30 unique, permitted product inputs. Every
   row binds a product ID to an input SHA-256, rights state, and source locator.
   The manifest also freezes the evaluation-protocol SHA-256, ProofLaunch
   package SHA-256, and the named baseline's version and settings SHA-256.
2. The deterministic manifest expands those inputs into exactly 450 case IDs:
   three fixed ratios and five fixed seeds. The first 9:16 seed for each
   product is also a required video case, producing 30 video cases.
3. `prooflaunch-results.jsonl` contains exactly one result for every manifest
   case, including explicit failure rows. Each row binds its still, required
   video, and per-case gate report by a traversal-free relative locator plus
   SHA-256. Append-only journals call `fsync` per case and resume from missing
   manifest IDs. The compiler re-hashes all bound files; missing, duplicate,
   path-traversing, or tampered evidence fails before aggregation.
4. `baseline-results.jsonl` covers the identical 450 IDs. Completion is
   compared on the same denominator.
5. `human-comparisons.csv` contains randomized candidate A/B artifact hashes.
   The compiler maps hashes back to the case outputs after review. It rejects
   unblinded rows, unknown hashes, duplicate rater/case pairs, direct contact
   identifiers, and raters who did not cover all 30 products.

Five-seed diversity is a mechanical anti-copy gate, not an aesthetic score.
For each of 90 product/ratio groups, the median of the ten pairwise 64-bit
perceptual-hash distances must be between `0.08` and `0.45`, and every member
must retain product identity. At least 95% of the groups must pass.

## Durable matrix execution

`CompetitionMatrixRunner` turns the frozen case list into nine deterministic
phases: prepare products, Qwen3-VL understanding, GroundingDINO grounding,
Gemma planning, SDXL still generation, SigLIP2 still audit, LTX-Video
generation, SAM2 tracking, and CLAP/post-codec video audit. The adapter loads
one phase model at a time and must release it before the next phase begins. A
hash-chained, atomically replaced checkpoint records every activity attempt,
duration, output locator, primary and sidecar SHA-256, model reference, and
peak VRAM.

Resume re-hashes all successful artifacts and sidecars and revalidates every
frozen source product before it trusts their checkpoints.
A process interruption may rerun only the interrupted activity. Explicit
`TransientActivityError` failures receive at most two bounded retries;
unclassified, schema, path, input-hash, or permission failures are permanent
and become explicit crashed case rows. Finalization remains deterministic and
never grants human release.

The runner refuses adapters that declare a closed online inference API.
Optional modulo shards are disjoint by immutable manifest index. Each shard
has its own checkpoint and JSONL, while all artifacts remain under one evidence
root. Merge revalidates every shard, rejects wrong-shard or duplicate IDs, and
re-appends all 450 cases in manifest order.

## Video identity method

The lossless pre-encode compositor hashes only fully opaque product pixels and
requires equality on every frame. The delivery audit then decodes the final
MP4 and compares the same protected region against the source layer. It
requires at least 95% expected-frame coverage and a p95 normalized RGB mean
absolute error no greater than 0.04. The two gates are reported separately;
the lossy delivery check never replaces the exact pre-encode check.

## Audio-video alignment method

The final MP4 audio is decoded before CLAP scoring. Audio and visual evidence
are represented as labeled time intervals with locators and confidence.
One-to-one matching uses the closest midpoint among identical normalized event
labels. A fixture passes only when:

- matched-event coverage is at least 95%;
- p95 midpoint drift is no more than 0.50 seconds; and
- decoded audio/video duration drift is no more than 0.25 seconds.

CLAP provides semantic evidence; it does not invent timestamps. The
deterministic event matcher provides timing evidence; it does not pretend to
measure aesthetics.

## Reproduction

```bash
PYTHONPATH=src python scripts/build_competition_2x_manifest.py \
  evidence/radeon/multimodal-v7/products.csv \
  --benchmark-id prooflaunch-radeon-final \
  --protocol-sha256 <sha256-of-protocol> \
  --prooflaunch-build-sha256 <sha256-of-v7-archive> \
  --baseline-name "<named baseline>" \
  --baseline-version "<exact version>" \
  --baseline-settings-sha256 <sha256-of-settings> \
  --baseline-source-locator "baseline-settings.json" \
  --output evidence/radeon/multimodal-v7/manifest.json

PYTHONPATH=src python scripts/run_competition_2x_matrix.py preflight \
  --settings config/radeon_matrix_adapter.json \
  --manifest evidence/radeon/multimodal-v7/manifest.json \
  --strict-cache \
  --output evidence/radeon/multimodal-v7/radeon-preflight.json

PYTHONPATH=src python scripts/run_competition_2x_matrix.py run \
  --manifest evidence/radeon/multimodal-v7/manifest.json \
  --run-dir evidence/radeon/multimodal-v7/competition-2x \
  --adapter prooflaunch_remix.radeon_matrix_adapter:create_adapter \
  --resume

PYTHONPATH=src python scripts/compile_competition_2x_evidence.py \
  --manifest evidence/radeon/multimodal-v7/manifest.json \
  --results evidence/radeon/multimodal-v7/prooflaunch-results.jsonl \
  --baseline-results evidence/radeon/multimodal-v7/baseline-results.jsonl \
  --human-comparisons evidence/human/human-comparisons.csv \
  --evidence-output evidence/radeon/multimodal-v7/competition-2x-evidence.json \
  --report-output evidence/radeon/multimodal-v7/competition-2x-report.json
```

The preflight command exits `0` only when all blocking runtime, local-model,
and frozen-source requirements pass. The evidence compiler exits `0` only
when every quality bar passes; exit `1` means at least one metric failed or
was missing. Schema, coverage, or hash errors abort before certification. A
one-product Notebook fixture is explicitly asserted not to certify the
benchmark.

## Truth boundary

The 117 local tests prove contract logic, artifact and sidecar binding, phase exclusivity,
bounded retry, process-interruption recovery, exact shard coverage/merge,
resumable journaling, tamper detection, routing, and fail-closed behavior.
They also prove that missing HIP, low VRAM, missing strict caches, invalid
Gemma retention, and frozen-source tampering block
`ProofLaunchRadeonPreflightV2`, including wrong-commit cache and model-license
drift attacks. They do not prove Radeon model execution,
output quality, human preference, or superiority. Those claims remain blocked
until the frozen benchmark, 3–5 minute Radeon demo, and official submission
checklist are complete.
