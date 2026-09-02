# Third-Party Notices and Review Boundaries

## Scope of the project license

`LICENSE` applies only to copyrightable LifePreview-originated software that its copyright holders are entitled to license. It does not replace or modify the licenses for third-party software, pretrained model weights, datasets, fonts, brands, or media assets.

The current competition package deliberately excludes model weights, ComfyUI installations, generated runtime assets, local databases, caches, logs, and secrets. Its `source/` directory contains only the explicitly allowlisted LifePreview project snapshot; it is not a distribution of model weights or third-party source releases. The absence of excluded materials is not a representation that they are unlicensed or public-domain materials.

## Runtime and model components

The project profile and README describe AMD Radeon/ROCm, PyTorch, ComfyUI, FLUX reference-image generation, and MiniMax H3 video generation as runtime components. Their software, model, service, and distribution terms are controlled by their respective copyright holders and providers.

No model weight or third-party source distribution is included in this package. Before publishing a subsequent source snapshot, maintainers must:

1. retain the upstream `LICENSE`, `NOTICE`, and attribution files required by every included dependency;
2. pin each model's filename, version or revision, source URL, SHA-256, and applicable usage terms in the AMD deployment model manifests;
3. confirm that the intended competition demonstration and repository distribution are allowed by each dependency and model license; and
4. keep provider credentials, private configurations, and any assets without redistribution rights out of Git.

## Demonstration and document assets

The demo video, project profile, and presentation deck are included for competition review. They may contain product names, screenshots, quotations, or generated material that are not separately relicensed by the PolyForm license. Do not reuse a third party's trademarks, personal likenesses, source text, or media based solely on their appearance in these materials.

## Submission review record

The submission evidence is indexed in [evidence/AMD_ROCm_Evidence.md](evidence/AMD_ROCm_Evidence.md). It distinguishes prior showcase media from live AMD execution evidence. The imported source snapshot and its working-tree status are recorded in [source/SNAPSHOT.md](source/SNAPSHOT.md).
