# CESARops: AMD Lemonade Hackathon Demo Notes

These notes outline the key facts for the Lemonade Hackathon write-up, specifically regarding the **Forge Test Lab**.

## What We Built
We successfully built and froze the **Test Lab Architecture (v1)**. The Test Lab is an offline, bounded, deterministic qualification pipeline for evaluating new remote-sensing techniques against known ground truth data. 

## Key Architectural Principles
1. **No Autonomous Detection**: The Test Lab is strictly prohibited from claiming aircraft detection. Its highest permitted output is: *"This method appears to contribute useful evidence toward search-grid prioritization."*
2. **Evidence Contribution over "Finding"**: Rather than building an "AI scientist" to hunt missing planes, we built a rigorous scientific qualification system that measures metric improvements (like `TargetRankAfter` and `SearchAreaReductionAtFixedRecall`).
3. **Strict Qualification**: A `TestContract` executes offline against a verified `SiteQualificationRecord`. Outputs pass through a `SkepticalReviewerWorker` which produces an `EvidenceLayerCandidate` strictly awaiting human review. There is NO automatic promotion to production.

## The Fixture Set (`aircraft-search-grid-v1`)
We curated a diverse, highly verified, ethically bounded testing dataset of known crash sites to stress-test our qualification pipeline without raising ethical concerns:
- **Sólheimasandur DC-3 (Iceland)**: Validates baseline optical contrast on black sand.
- **Atka Island B-24 (Alaska)**: Validates structural footprint algorithms on open tundra.
- **Gauli Glacier C-53 (Switzerland)**: Validates temporal change-detection on ice.
- **Loon Lake B-23 (Idaho)**: Validates sub-canopy geometric algorithms in dense forests.

## Why This Matters for AMD Lemonade
1. **Safety and Provenance First**: By preventing the system from web crawling or acting as an unbounded "agent," we prove that AI systems can be heavily constrained to perform rigorous, determinable scientific work.
2. **The "Next Step" for AMD Hardware**: The pipeline currently executes in `DerivedFixtureMetrics` mode (offline metrics calculation). The immediate next boundary—and the perfect case for AMD compute—is extending the `SandboxExecutorWorker` to process real satellite imagery chips deterministically on local ROCm infrastructure, executing the exact same `TestContract` at a massive scale locally, entirely offline.

## Remaining Boundary
*Next sprint replaces fixture metrics with one small real imagery-processing test and optionally executes the same bounded contract on AMD ROCm infrastructure.*
