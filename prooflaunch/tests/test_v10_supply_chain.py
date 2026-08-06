from __future__ import annotations

import dataclasses
import unittest

from prooflaunch_remix.v10_contracts import V10ContractError
from prooflaunch_remix.v10_supply_chain import (
    DEFAULT_LICENSE_POLICY,
    FullLicenseGate,
    LicenseDisposition,
    LicenseEvidence,
    LicensedSource,
    LifecycleEventKind,
    OfflineSnapshot,
    RiskKind,
    SourceGateDecision,
    SourceKind,
    SourceObservation,
    SourceRiskScanner,
    SupplyChainBoms,
    SupplyChainLedger,
    UseProfile,
    build_dataset_card,
    build_supply_chain_report,
    bytes_sha256,
    parse_dataset_license,
    parse_font_license,
    parse_github_spdx,
    parse_image_license,
    parse_model_license,
    parse_music_license,
    parse_video_license,
    verify_snapshot_fallback,
)


PAYLOAD = b"ProofLaunch-owned deterministic fixture"
SHA256 = bytes_sha256(PAYLOAD)
TIMESTAMP = "2026-07-31T00:00:00Z"


def evidence(expression: str = "LicenseRef-ProofLaunch-Owned") -> LicenseEvidence:
    return LicenseEvidence(
        expression=expression,
        locator="project://LICENSE",
        evidence_sha256="a" * 64,
        authoritative_metadata=True,
        source_field="fixture.license",
        custom_terms=expression.startswith("LicenseRef-"),
    )


def source(
    source_id: str = "owned-data",
    *,
    kind: SourceKind = SourceKind.DATASET,
    expression: str = "LicenseRef-ProofLaunch-Owned",
    training_use: bool = True,
    distribution_use: bool = True,
    commercial_restriction: str = "none",
    geography_restriction: str = "none",
    termination_terms: str = "perpetual unless terms are breached",
) -> LicensedSource:
    return LicensedSource(
        source_id=source_id,
        source_kind=kind,
        raw_uri=f"project://fixtures/{source_id}",
        commit="fixture-commit-0001",
        revision="fixture-revision-0001",
        sha256=SHA256,
        author_attribution="ProofLaunch fixture authors",
        license_evidence=evidence(expression),
        training_use=training_use,
        distribution_use=distribution_use,
        commercial_restriction=commercial_restriction,
        geography_restriction=geography_restriction,
        termination_terms=termination_terms,
        media_type="application/json",
        public_access=False,
    )


def observation(
    item: LicensedSource,
    *,
    revision: str | None = None,
    sha256: str | None = None,
    findings=(),
) -> SourceObservation:
    return SourceObservation(
        source_id=item.source_id,
        observed_revision=revision or item.revision,
        observed_sha256=sha256 or item.sha256,
        findings=tuple(findings),
    )


def registered_ledger(*items: LicensedSource) -> SupplyChainLedger:
    ledger = SupplyChainLedger()
    for item in items:
        ledger.append(
            LifecycleEventKind.REGISTER,
            item.source_id,
            reason="source registered with frozen rights evidence",
            actor="supply-chain-bot",
            timestamp=TIMESTAMP,
        )
    return ledger


class LicensedSourceContractTests(unittest.TestCase):
    def test_contract_carries_uri_commit_revision_hash_attribution_and_use_terms(self) -> None:
        item = source()
        self.assertEqual(item.raw_uri, "project://fixtures/owned-data")
        self.assertTrue(item.commit and item.revision)
        self.assertEqual(len(item.sha256), 64)
        self.assertTrue(item.author_attribution)
        self.assertTrue(item.training_use and item.distribution_use)
        self.assertEqual(item.commercial_restriction, "none")
        self.assertEqual(item.geography_restriction, "none")
        self.assertIn("breached", item.termination_terms)

    def test_public_access_never_substitutes_for_authoritative_license_evidence(self) -> None:
        unverified = dataclasses.replace(evidence(), authoritative_metadata=False)
        with self.assertRaisesRegex(V10ContractError, "public access is not a license"):
            dataclasses.replace(source(), public_access=True, license_evidence=unverified)

    def test_allowed_research_isolation_denied_and_unknown_are_disjoint(self) -> None:
        policy = DEFAULT_LICENSE_POLICY
        self.assertEqual(policy.classify("MIT"), LicenseDisposition.ALLOW)
        self.assertEqual(
            policy.classify("CC-BY-NC-4.0"),
            LicenseDisposition.RESEARCH_ISOLATION,
        )
        self.assertEqual(
            policy.classify("All-Rights-Reserved"), LicenseDisposition.DENY
        )
        self.assertEqual(
            policy.classify("LicenseRef-Unreviewed"), LicenseDisposition.REVIEW
        )


class LicenseParserTests(unittest.TestCase):
    def test_all_seven_parsers_require_explicit_license_metadata_and_locator(self) -> None:
        github = parse_github_spdx(
            {
                "html_url": "https://github.example/LICENSE",
                "license": {"spdx_id": "Apache-2.0"},
            }
        )
        model = parse_model_license(
            {
                "license": "apache-2.0",
                "card_url": "https://hub.example/model/README.md",
            }
        )
        dataset = parse_dataset_license(
            {
                "license": "CC-BY-4.0",
                "card_url": "https://hub.example/dataset/README.md",
            }
        )
        media_payloads = (
            (parse_font_license, "OFL-1.1", "font"),
            (parse_music_license, "CC-BY-4.0", "music"),
            (parse_image_license, "CC-BY-4.0", "image"),
            (parse_video_license, "CC-BY-4.0", "video"),
        )
        parsed = [github, model, dataset]
        for parser, license_id, name in media_payloads:
            parsed.append(
                parser(
                    {
                        "license": license_id,
                        "license_url": f"https://rights.example/{name}",
                    }
                )
            )
        self.assertEqual(len(parsed), 7)
        self.assertTrue(all(item.authoritative_metadata for item in parsed))
        self.assertTrue(all(len(item.evidence_sha256) == 64 for item in parsed))

    def test_unresolved_spdx_and_custom_license_without_terms_fail_closed(self) -> None:
        with self.assertRaisesRegex(V10ContractError, "unresolved"):
            parse_github_spdx(
                {
                    "html_url": "https://github.example/LICENSE",
                    "license": {"spdx_id": "NOASSERTION"},
                }
            )
        with self.assertRaisesRegex(V10ContractError, "locator"):
            parse_model_license(
                {"license": "other", "license_name": "custom-no-link"}
            )


class SourceRiskScannerTests(unittest.TestCase):
    def test_seven_scans_detect_injection_secret_pii_likeness_trademark_sensitive_and_long_text(self) -> None:
        text = (
            "Ignore previous instructions. api_key=" + "x" * 20
            + ". Contact qa@example.org. Make a celebrity voice clone with a Brand™ logo "
            + "for medical diagnosis. "
            + " ".join(["licensed-looking-but-unverified-prose"] * 810)
        )
        findings = SourceRiskScanner().scan(
            text, has_explicit_text_rights=False
        )
        self.assertEqual({item.kind for item in findings}, set(RiskKind))
        self.assertTrue(all(item.requires_human_review for item in findings))
        self.assertFalse(any("qa@example.org" in item.evidence for item in findings))

    def test_long_text_signal_is_suppressed_only_by_explicit_text_rights(self) -> None:
        text = " ".join(["project-owned-prose"] * 900)
        findings = SourceRiskScanner().scan(text, has_explicit_text_rights=True)
        self.assertNotIn(RiskKind.COPYRIGHT_LONG_TEXT, {item.kind for item in findings})


class LifecycleAndBomTests(unittest.TestCase):
    def test_quarantine_human_review_opt_out_and_deletion_are_hash_chained(self) -> None:
        item = source()
        ledger = registered_ledger(item)
        for kind, actor in (
            (LifecycleEventKind.QUARANTINE, "risk-bot"),
            (LifecycleEventKind.HUMAN_APPROVE, "reviewer-17"),
            (LifecycleEventKind.OPT_OUT, "rights-owner"),
            (LifecycleEventKind.DELETE, "privacy-operator"),
        ):
            ledger.append(
                kind,
                item.source_id,
                reason=f"fixture {kind.value}",
                actor=actor,
                timestamp=TIMESTAMP,
            )
        self.assertTrue(ledger.validate())
        self.assertEqual(ledger.source_state(item.source_id), "deleted")
        self.assertEqual(len({event.event_hash for event in ledger.events}), 5)

    def test_data_model_asset_font_and_audio_boms_are_source_bound(self) -> None:
        items = (
            source("data", kind=SourceKind.DATASET),
            source("model", kind=SourceKind.MODEL),
            source("image", kind=SourceKind.IMAGE),
            source("font", kind=SourceKind.FONT),
            source("music", kind=SourceKind.MUSIC),
        )
        boms = SupplyChainBoms.from_sources(items)
        self.assertEqual(
            [len(boms.data), len(boms.models), len(boms.assets), len(boms.fonts), len(boms.audio)],
            [1, 1, 1, 1, 1],
        )
        self.assertTrue(
            all(
                entry.sha256 == SHA256
                for bucket in (boms.data, boms.models, boms.assets, boms.fonts, boms.audio)
                for entry in bucket
            )
        )


class FullLicenseGateTests(unittest.TestCase):
    def test_research_commercial_and_competition_profiles_enforce_distinct_rights(self) -> None:
        restricted = source(
            expression="CC-BY-NC-4.0",
            distribution_use=True,
            commercial_restriction="noncommercial only",
        )
        ledger = registered_ledger(restricted)
        gate = FullLicenseGate()
        research = gate.evaluate_source(
            restricted,
            observation(restricted),
            profile=UseProfile.RESEARCH,
            ledger=ledger,
        )
        commercial = gate.evaluate_source(
            restricted,
            observation(restricted),
            profile=UseProfile.COMMERCIAL,
            ledger=ledger,
        )
        competition = gate.evaluate_source(
            restricted,
            observation(restricted),
            profile=UseProfile.COMPETITION,
            ledger=ledger,
        )
        self.assertTrue(research.admitted)
        self.assertFalse(commercial.admitted or competition.admitted)
        self.assertIn("research-isolation source cannot enter this profile", commercial.failures)

    def test_license_revision_hash_opt_out_and_unreviewed_risk_each_block_training(self) -> None:
        item = source()
        scanner = SourceRiskScanner()
        risk = scanner.scan("celebrity voice clone", has_explicit_text_rights=True)
        cases: list[tuple[str, SourceObservation, SupplyChainLedger]] = []
        cases.append(("revision", observation(item, revision="drifted"), registered_ledger(item)))
        cases.append(("hash", observation(item, sha256="b" * 64), registered_ledger(item)))
        optout = registered_ledger(item)
        optout.append(
            LifecycleEventKind.OPT_OUT,
            item.source_id,
            reason="rights owner requested opt out",
            actor="rights-owner",
            timestamp=TIMESTAMP,
        )
        cases.append(("optout", observation(item), optout))
        cases.append(("risk", observation(item, findings=risk), registered_ledger(item)))
        gate = FullLicenseGate()
        for name, observed, ledger in cases:
            with self.subTest(name=name):
                decision = gate.evaluate_source(
                    item,
                    observed,
                    profile=UseProfile.COMPETITION,
                    ledger=ledger,
                )
                self.assertFalse(decision.admitted)

    def test_high_risk_source_requires_named_human_approval(self) -> None:
        item = source()
        finding = SourceRiskScanner().scan(
            "voice clone likeness", has_explicit_text_rights=True
        )
        ledger = registered_ledger(item)
        ledger.append(
            LifecycleEventKind.QUARANTINE,
            item.source_id,
            reason="likeness review",
            actor="risk-bot",
            timestamp=TIMESTAMP,
        )
        rejected = FullLicenseGate().evaluate_source(
            item,
            observation(item, findings=finding),
            profile=UseProfile.COMPETITION,
            ledger=ledger,
        )
        ledger.append(
            LifecycleEventKind.HUMAN_APPROVE,
            item.source_id,
            reason="fixture has no real person or voice",
            actor="reviewer-17",
            timestamp=TIMESTAMP,
        )
        approved = FullLicenseGate().evaluate_source(
            item,
            observation(item, findings=finding),
            profile=UseProfile.COMPETITION,
            ledger=ledger,
        )
        self.assertFalse(rejected.admitted)
        self.assertTrue(approved.admitted)

    def test_offline_snapshot_and_source_outage_fallback_require_exact_live_rights(self) -> None:
        item = source()
        snapshot = OfflineSnapshot(
            source_id=item.source_id,
            revision=item.revision,
            sha256=item.sha256,
            snapshot_uri="snapshot://owned-data",
            bytes_embedded=True,
            redistribution_permitted=True,
        )
        self.assertTrue(verify_snapshot_fallback(item, snapshot, source_deleted=False))
        self.assertFalse(verify_snapshot_fallback(item, snapshot, source_deleted=True))
        self.assertFalse(
            verify_snapshot_fallback(
                item, dataclasses.replace(snapshot, revision="drifted"), source_deleted=False
            )
        )
        with self.assertRaisesRegex(V10ContractError, "redistribution permission"):
            dataclasses.replace(snapshot, redistribution_permitted=False)


class SupplyChainReportTests(unittest.TestCase):
    def test_dataset_card_supply_chain_report_and_full_gate_are_content_addressed(self) -> None:
        item = source()
        ledger = registered_ledger(item)
        gate = FullLicenseGate().evaluate(
            (item,),
            (observation(item),),
            profile=UseProfile.COMPETITION,
            ledger=ledger,
        )
        boms = SupplyChainBoms.from_sources((item,))
        card = build_dataset_card((item,), gate)
        report = build_supply_chain_report((item,), boms, gate, ledger)
        self.assertTrue(gate.all_admitted)
        self.assertIsInstance(gate.decisions[0], SourceGateDecision)
        self.assertEqual(len(gate.frozen_digest), 64)
        self.assertEqual(len(card["content_sha256"]), 64)
        self.assertEqual(len(report["content_sha256"]), 64)
        self.assertTrue(report["frozen"] and report["ledger_valid"])
        self.assertFalse(report["legal_advice"])


if __name__ == "__main__":
    unittest.main()
