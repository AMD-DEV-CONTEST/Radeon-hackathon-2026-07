from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from prooflaunch_remix.gtm_codex_integrated_campaign import (
    CodexIntegratedCampaignError,
    compile_codex_integrated_campaign_portfolio,
    verify_codex_integrated_campaign_portfolio,
)
from prooflaunch_remix.v10_submission_production_api import (
    load_verified_platform_capability_showcase,
)
from scripts.compile_gtm_codex_integrated_campaign import compile_from_files


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence/v10/gtm-codex-integrated-campaign-portfolio-v1.json"
BLUEPRINTS = ROOT / "config/codex-integrated-campaign-blueprints-v1.json"


class CodexIntegratedCampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.portfolio = compile_from_files()

    def test_sealed_portfolio_matches_the_compiler(self) -> None:
        self.assertEqual(
            json.loads(EVIDENCE.read_text(encoding="utf-8")),
            self.portfolio,
        )

    def test_two_campaign_systems_bind_all_last_mile_outputs(self) -> None:
        payload = self.portfolio
        self.assertEqual(payload["pack_count"], 2)
        self.assertEqual(payload["platform_candidate_count"], 26)
        self.assertEqual(payload["email_count"], 8)
        self.assertEqual(payload["production_direction_count"], 6)
        self.assertEqual(payload["search_geo_node_count"], 14)
        self.assertEqual(payload["seven_day_flight_slot_count"], 14)
        self.assertEqual(payload["experiment_count"], 8)
        for pack in payload["packs"]:
            self.assertEqual(len(pack["platform_candidates"]), 13)
            self.assertEqual(len(pack["lifecycle_phases"]), 4)
            self.assertEqual(len(pack["email_sequence"]), 4)
            self.assertEqual(len(pack["production_directions"]), 3)
            self.assertEqual(len(pack["search_geo_system"]["nodes"]), 7)
            self.assertEqual(len(pack["seven_day_flight"]), 7)
            self.assertEqual(len(pack["experiment_registry"]), 4)
            self.assertEqual(len(pack["channel_strategy"]["primary_surfaces"]), 2)
            self.assertFalse(pack["channel_strategy"]["paid_media_required"])

    def test_strategy_is_not_a_spray_and_pray_calendar(self) -> None:
        for pack in self.portfolio["packs"]:
            assigned = [
                surface
                for phase in pack["lifecycle_phases"]
                for surface in phase["surface_ids"]
            ]
            self.assertEqual(len(assigned), 13)
            self.assertEqual(len(set(assigned)), 13)
            phase_for_surface = {
                surface: phase["phase_id"]
                for phase in pack["lifecycle_phases"]
                for surface in phase["surface_ids"]
            }
            for candidate in pack["platform_candidates"]:
                self.assertEqual(
                    candidate["lifecycle_phase"],
                    phase_for_surface[candidate["surface_id"]],
                )
            self.assertTrue(
                all(
                    slot["status"] == "draft_pending_human_review"
                    for slot in pack["seven_day_flight"]
                )
            )

    def test_growth_experiments_have_real_denominators_and_stop_rules(self) -> None:
        for pack in self.portfolio["packs"]:
            for experiment in pack["experiment_registry"]:
                self.assertGreater(len(experiment["numerator"]), 20)
                self.assertGreater(len(experiment["denominator"]), 20)
                self.assertIn("baseline", experiment["minimum_sample_rule"].lower())
                self.assertTrue(experiment["kill_rule"].startswith("Stop"))
                self.assertFalse(experiment["causal_claim_allowed"])

    def test_capability_pack_never_gains_release_or_effect_authority(self) -> None:
        payload = self.portfolio
        self.assertEqual(payload["release_eligible_count"], 0)
        self.assertEqual(payload["human_review_completed_count"], 0)
        self.assertFalse(payload["production_effect_observed"])
        self.assertFalse(payload["causal_effect_claim_allowed"])
        self.assertFalse(payload["four_a_claim_eligible"])
        self.assertFalse(payload["top1_claim_eligible"])
        self.assertFalse(payload["external_publish_executed"])
        self.assertEqual(payload["paid_media_spend_usd"], 0)
        b2c = next(row for row in payload["packs"] if row["business_model"] == "b2c")
        self.assertEqual(
            b2c["publication_policy_state"],
            "permanently_blocked_synthetic_benchmark",
        )

    def test_digest_and_authority_tamper_fail_closed(self) -> None:
        tampered = copy.deepcopy(self.portfolio)
        tampered["packs"][0]["external_publish_executed"] = True
        with self.assertRaisesRegex(CodexIntegratedCampaignError, "digest"):
            verify_codex_integrated_campaign_portfolio(tampered)

        tampered = copy.deepcopy(self.portfolio)
        tampered["packs"][1]["publication_policy_state"] = "pending_review"
        unsigned_pack = dict(tampered["packs"][1])
        unsigned_pack.pop("content_sha256")
        import hashlib

        tampered["packs"][1]["content_sha256"] = hashlib.sha256(
            json.dumps(
                unsigned_pack,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        unsigned = dict(tampered)
        unsigned.pop("content_sha256")
        tampered["content_sha256"] = hashlib.sha256(
            json.dumps(
                unsigned,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with self.assertRaisesRegex(CodexIntegratedCampaignError, "synthetic"):
            verify_codex_integrated_campaign_portfolio(tampered)

    def test_source_showcase_or_blueprint_truth_tamper_is_rejected(self) -> None:
        showcase = load_verified_platform_capability_showcase(ROOT)
        blueprints = json.loads(BLUEPRINTS.read_text(encoding="utf-8"))
        tampered_showcase = copy.deepcopy(showcase)
        tampered_showcase["production_effect_observed"] = True
        with self.assertRaisesRegex(CodexIntegratedCampaignError, "digest"):
            compile_codex_integrated_campaign_portfolio(
                showcase=tampered_showcase,
                blueprints=blueprints,
            )
        tampered_blueprints = copy.deepcopy(blueprints)
        tampered_blueprints["blueprints"][0]["paid_media_spend_usd"] = 1
        with self.assertRaisesRegex(CodexIntegratedCampaignError, "overclaims"):
            compile_codex_integrated_campaign_portfolio(
                showcase=showcase,
                blueprints=tampered_blueprints,
            )


if __name__ == "__main__":
    unittest.main()
