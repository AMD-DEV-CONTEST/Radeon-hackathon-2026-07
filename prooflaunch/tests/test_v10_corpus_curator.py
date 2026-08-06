from __future__ import annotations

import unittest
from collections import defaultdict

from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_corpus_curator import (
    CorpusSample,
    CorpusTaxon,
    CuratedReference,
    GTMArtifactKind,
    Modality,
    ReviewDisposition,
    SelectionPolicy,
    alignment_score,
    bind_sources_to_samples,
    build_grounded_gtm_bundle,
    clean_image_metadata,
    concept_long_tail,
    corpus_distribution,
    cosine_similarity,
    deduplicate_audio,
    deduplicate_keyframes,
    detect_language,
    deterministic_audit_sample,
    grouped_split,
    krippendorff_alpha_ordinal,
    minhash_signature,
    minhash_similarity,
    normalize_audio_sample_rate,
    normalize_color_profile,
    normalize_unicode,
    normalize_video_fps,
    perceptual_hash_distance,
    review_disposition,
    scan_contamination,
    scan_prompt_leakage,
    score_batch,
    score_sample,
    select_super_batch,
    template_fingerprint,
    temporal_split,
)
from prooflaunch_remix.v10_supply_chain import (
    LicenseEvidence,
    LicensedSource,
    SourceKind,
)


SHA = "a" * 64


def sample(
    index: int,
    *,
    taxon: CorpusTaxon = CorpusTaxon.STRATEGY,
    modality: Modality = Modality.TEXT,
    source_id: str | None = None,
    template_id: str | None = None,
    synthetic: bool = False,
    success: bool = True,
    steps: int = 2,
    concepts: tuple[str, ...] = ("evidence", "gtm"),
    content: str | None = None,
    captured_at: str = "2026-01-01T00:00:00Z",
) -> CorpusSample:
    return CorpusSample(
        sample_id=f"sample-{index:03d}",
        taxon=taxon,
        modality=modality,
        source_id=source_id or f"source-{index:03d}",
        source_revision=f"revision-{index:03d}",
        source_sha256=SHA,
        product_entity_id=f"product-{index // 2:03d}",
        repository_entity_id=f"repo-{index // 3:03d}",
        captured_at=captured_at,
        content=content or f"Evidence grounded campaign planning record {index}",
        template_id=template_id or f"template-{index:03d}",
        language="en",
        synthetic=synthetic,
        success=success,
        trajectory_steps=steps,
        concept_tags=concepts,
        evidence_ids=(f"evidence-{index:03d}",),
    )


class CorpusOntologyTests(unittest.TestCase):
    def test_taxonomy_covers_twelve_physical_agent_evidence_and_agency_layers(self) -> None:
        self.assertEqual(len(CorpusTaxon), 12)
        self.assertEqual(
            {item.value for item in CorpusTaxon},
            {
                "physical_product", "ai_agent", "evidence", "strategy",
                "creative", "copy", "art", "channel", "compliance",
                "audit", "repair", "tool_trajectory",
            },
        )

    def test_grounded_bundle_contains_all_seventeen_gtm_artifacts_once(self) -> None:
        bundle = build_grounded_gtm_bundle(
            "bundle-001",
            ("source-001",),
            ("evidence-001",),
            {kind: f"project-owned {kind.value}" for kind in GTMArtifactKind},
        )
        self.assertEqual(len(bundle.artifacts), 17)
        self.assertEqual({item.kind for item in bundle.artifacts}, set(GTMArtifactKind))
        observed = [item for item in bundle.artifacts if item.observed]
        self.assertEqual(len(observed), 3)
        self.assertTrue(all(item.evidence_ids for item in observed))

    def test_observed_gtm_artifact_cannot_exist_without_evidence(self) -> None:
        values = {kind: kind.value for kind in GTMArtifactKind}
        with self.assertRaisesRegex(V10ContractError, "observed artifact"):
            build_grounded_gtm_bundle("bad", ("source",), (), values)


class TextAndMediaCurationTests(unittest.TestCase):
    def test_unicode_language_template_and_minhash_pipeline_is_deterministic(self) -> None:
        text = "ＡＩ\x00  GTM   launch 123"
        cleaned = normalize_unicode(text)
        self.assertEqual(cleaned, "AI GTM launch 123")
        self.assertEqual(detect_language(cleaned), "en")
        self.assertEqual(detect_language("新品上市证据"), "zh")
        self.assertEqual(template_fingerprint("Offer 123"), template_fingerprint("Offer 456"))
        left = minhash_signature("evidence grounded campaign system")
        right = minhash_signature("evidence grounded campaign system")
        self.assertEqual(minhash_similarity(left, right), 1.0)

    def test_image_exif_color_phash_and_embedding_controls_are_executable(self) -> None:
        cleaned = clean_image_metadata(
            {"GPSLatitude": "1", "SerialNumber": "private", "Width": "4096"}
        )
        self.assertEqual(cleaned, {"Width": "4096"})
        self.assertEqual(normalize_color_profile("Display-P3"), "convert-to-sRGB IEC61966-2.1")
        self.assertEqual(perceptual_hash_distance("0000", "0001"), 1)
        self.assertAlmostEqual(cosine_similarity((1.0, 0.0), (1.0, 0.0)), 1.0)

    def test_video_keyframe_and_audio_normalization_remove_duplicates(self) -> None:
        self.assertEqual(normalize_video_fps(29.97), 30.0)
        frames = deduplicate_keyframes(("0000", "0001", "ffff"), threshold=1)
        self.assertEqual(frames, ("0000", "ffff"))
        self.assertEqual(normalize_audio_sample_rate(44_100), 48_000)
        self.assertEqual(deduplicate_audio(("a", "a", "b")), ("a", "b"))


class AlignmentAndScoringTests(unittest.TestCase):
    def test_image_text_video_copy_and_claim_evidence_alignment_share_grounded_contract(self) -> None:
        for kind in ("image_text", "video_copy", "claim_evidence"):
            result = alignment_score(
                kind,
                ("product", "red", "portable"),
                ("product", "red", "portable", "verified"),
                threshold=0.7,
            )
            self.assertTrue(result.passed)
            self.assertEqual(result.evidence_overlap, ("portable", "product", "red"))

    def test_sample_and_batch_scores_measure_quality_difficulty_novelty_coverage_information(self) -> None:
        items = [
            sample(index, steps=index + 1, concepts=("evidence", f"concept-{index}"))
            for index in range(4)
        ]
        scores = {
            item.sample_id: score_sample(
                item,
                alignment=0.9,
                evidence_coverage=1.0,
                verifier_confidence=0.95,
                rarity=0.8,
                failure_value=0.6,
            )
            for item in items
        }
        batch = score_batch(items, scores)
        self.assertGreater(min(item.quality for item in scores.values()), 0.9)
        self.assertGreater(batch.diversity, 0.5)
        self.assertGreater(batch.information, 0.5)


class ReferenceSelectionTests(unittest.TestCase):
    def _balanced_candidates(self):
        taxa = (
            CorpusTaxon.PHYSICAL_PRODUCT, CorpusTaxon.PHYSICAL_PRODUCT,
            CorpusTaxon.PHYSICAL_PRODUCT, CorpusTaxon.AI_AGENT,
            CorpusTaxon.STRATEGY, CorpusTaxon.ART, CorpusTaxon.CREATIVE,
            CorpusTaxon.EVIDENCE, CorpusTaxon.REPAIR, CorpusTaxon.AUDIT,
            CorpusTaxon.CHANNEL, CorpusTaxon.TOOL_TRAJECTORY,
        )
        modalities = (
            Modality.IMAGE, Modality.VIDEO, Modality.SCREEN, Modality.TEXT,
            Modality.TEXT, Modality.IMAGE, Modality.VIDEO, Modality.DOCUMENT,
            Modality.TEXT, Modality.TEXT, Modality.AUDIO, Modality.TRAJECTORY,
        )
        return [
            sample(
                index,
                taxon=taxa[index],
                modality=modalities[index],
                synthetic=index < 3,
                success=index >= 3,
                steps=10 if index in {0, 1} else 2,
                concepts=("evidence", "product", "strategy", "production"),
            )
            for index in range(12)
        ]

    def test_reference_guided_super_batch_enforces_caps_and_six_balances(self) -> None:
        items = self._balanced_candidates()
        scores = {
            item.sample_id: score_sample(
                item,
                alignment=0.95,
                evidence_coverage=1.0,
                verifier_confidence=0.95,
                rarity=0.9,
                failure_value=0.7,
            )
            for item in items
        }
        reference = CuratedReference(
            reference_id="curated-v1",
            required_taxa=frozenset(
                {CorpusTaxon.PHYSICAL_PRODUCT, CorpusTaxon.STRATEGY, CorpusTaxon.ART}
            ),
            required_modalities=frozenset({Modality.TEXT, Modality.IMAGE, Modality.VIDEO}),
            required_concepts=frozenset({"evidence", "product", "strategy", "production"}),
            minimum_quality=0.8,
        )
        result = select_super_batch(
            items, scores, reference, SelectionPolicy(), batch_size=12
        )
        self.assertEqual(len(result.samples), 12)
        self.assertTrue(all(result.constraints.values()))
        self.assertEqual(len(result.content_sha256), 64)

    def test_source_template_or_synthetic_concentration_blocks_selection(self) -> None:
        items = [
            sample(index, source_id="same", template_id="same", synthetic=True)
            for index in range(8)
        ]
        scores = {
            item.sample_id: score_sample(
                item,
                alignment=1.0,
                evidence_coverage=1.0,
                verifier_confidence=1.0,
                rarity=1.0,
                failure_value=1.0,
            )
            for item in items
        }
        reference = CuratedReference(
            "reference", frozenset(), frozenset(), frozenset(), 0.5
        )
        with self.assertRaisesRegex(V10ContractError, "caps"):
            select_super_batch(items, scores, reference, SelectionPolicy(), batch_size=8)


class SplitLeakageAndAuditTests(unittest.TestCase):
    def test_product_repository_and_time_splits_are_group_or_time_isolated(self) -> None:
        items = [
            sample(index, captured_at=f"2026-{1 + index // 3:02d}-01T00:00:00Z")
            for index in range(9)
        ]
        for field in ("product_entity_id", "repository_entity_id"):
            splits = grouped_split(items, field)
            memberships = defaultdict(set)
            for partition, values in splits.items():
                for item in values:
                    memberships[getattr(item, field)].add(partition)
            self.assertTrue(all(len(value) == 1 for value in memberships.values()))
        temporal = temporal_split(items, "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z")
        self.assertTrue(temporal["train"] and temporal["validation"] and temporal["test"])

    def test_benchmark_contamination_and_prompt_canary_leakage_are_detected(self) -> None:
        items = [
            sample(1, content="sealed benchmark exact evidence grounded answer"),
            sample(2, content="normal training sample CANARY-DO-NOT-TRAIN"),
        ]
        findings = scan_contamination(
            items, {"sealed-1": "sealed benchmark exact evidence grounded answer"}
        )
        leaked = scan_prompt_leakage(items, ("CANARY-DO-NOT-TRAIN",))
        self.assertEqual(findings[0].sample_id, "sample-001")
        self.assertEqual(leaked, ("sample-002",))

    def test_deterministic_audit_alpha_review_routing_and_distributions_are_frozen(self) -> None:
        items = [sample(index, concepts=("head" if index < 4 else "tail",)) for index in range(8)]
        self.assertEqual(
            [item.sample_id for item in deterministic_audit_sample(items, 3, "seed")],
            [item.sample_id for item in deterministic_audit_sample(items, 3, "seed")],
        )
        self.assertGreaterEqual(
            krippendorff_alpha_ordinal(((5, 5, 5), (3, 3, 3), (1, 1, 1))),
            0.85,
        )
        self.assertEqual(review_disposition(4.8, 0.2), ReviewDisposition.GOLD_POSITIVE)
        self.assertEqual(review_disposition(2.0, 0.2), ReviewDisposition.REMOVE)
        self.assertEqual(review_disposition(3.8, 0.4), ReviewDisposition.REPAIR)
        self.assertEqual(review_disposition(3.8, 0.9), ReviewDisposition.REPLAY)
        distribution = corpus_distribution(items)
        self.assertEqual(distribution["concept"], {"head": 4, "tail": 4})
        self.assertEqual(concept_long_tail(items), (("head", 4), ("tail", 4)))

    def test_every_sample_is_bound_to_licensed_source_revision_and_hash(self) -> None:
        item = sample(1)
        licensed = LicensedSource(
            source_id=item.source_id,
            source_kind=SourceKind.DATASET,
            raw_uri="project://fixture",
            commit="commit-1",
            revision=item.source_revision,
            sha256=item.source_sha256,
            author_attribution="ProofLaunch fixture authors",
            license_evidence=LicenseEvidence(
                expression="LicenseRef-ProofLaunch-Owned",
                locator="project://LICENSE",
                evidence_sha256="b" * 64,
                authoritative_metadata=True,
                source_field="fixture.license",
            ),
            training_use=True,
            distribution_use=True,
            commercial_restriction="none",
            geography_restriction="none",
            termination_terms="perpetual unless breached",
            media_type="application/json",
        )
        self.assertEqual(bind_sources_to_samples((item,), (licensed,)), ())
        self.assertTrue(bind_sources_to_samples((sample(2),), (licensed,)))


if __name__ == "__main__":
    unittest.main()
