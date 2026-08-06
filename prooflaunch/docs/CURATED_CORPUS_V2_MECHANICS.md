# Curated Corpus V2 — mechanical layer

This layer implements the curation mechanics in TODO 0451–0488 and 0501–0539
without pretending that the required scaled, human-reviewed 4A corpus exists.

The ontology contains twelve corpus taxa spanning physical products, AI agents,
evidence, strategy, creative, copy, art, channel, compliance, audit, repair, and
tool trajectories. A complete grounded bundle contains seventeen distinct GTM
artifacts: facts, limits, Claim risks, ICP, JTBD, market tension, category
convention, SMP, reason-to-believe, offer, Big Idea, key-visual brief, copy
system, channel system, storyboard, audit finding, and repair action. Observed
facts cannot be constructed without evidence IDs; strategic and creative
outputs remain explicitly inferred.

The curation pipeline provides deterministic Unicode cleanup, language and
template detection, text MinHash, EXIF privacy stripping, sRGB conversion
plans, image pHash and embedding similarity, video FPS and keyframe
normalization, audio resampling and fingerprint deduplication, and three
evidence-overlap alignment gates. Each sample receives independently visible
quality, difficulty, novelty, coverage, and information scores. Batch selection
adds diversity and enforces source, template, synthetic-data, product-type,
modality, production, outcome, and trajectory-length constraints.

Leakage controls split by product entity, repository entity, and time. Sealed
benchmark MinHash and private-canary scans run before admission. This is in
addition to Supply Chain V3; clean content without a valid source revision,
hash, and use permission remains inadmissible.

## Evidence boundary

The generated runtime fixture contains twelve ProofLaunch-owned synthetic
metadata samples. It deliberately records:

- 0 CPT tokens;
- 0 SFT episodes;
- 0 preference pairs;
- 0 human reviews;
- 0 gold briefs and campaigns;
- `agency_corpus_v2_frozen=false`;
- `curated_corpus_v2_frozen=false`;
- `promotion_eligible=false`.

Open Materials V1 provides the 24-record rights gate for TODO 0463–0470, and
Agency Source Bundle V2 provides exactly 2,000 unique rights-bound source
records for TODO 0471. TODO 0489–0492 are now independently audited data builds;
TODO 0493–0500 and 0540–0550 remain open. The twelve-row curated seed by itself
is not evidence for those later builds; the exact 15M CPT, 15,000 SFT, 5,000
preference-pair and 2,000 region-pair claims are supported only by their named
independent recounts. Five-person review, 4.7 mean score, and Alpha ≥0.85 remain
unobserved.

Reproduce the mechanical layer with:

```bash
PYTHONPATH=src python scripts/build_v10_supply_chain.py
PYTHONPATH=src python scripts/build_v10_curated_corpus.py
PYTHONPATH=src python -m unittest -v tests.test_v10_corpus_curator
```

Outputs are under `data/v10_curated_corpus/`; the frozen truth-boundary receipt
is `evidence/v10/curated-corpus-v2-mechanical-audit.json`.
