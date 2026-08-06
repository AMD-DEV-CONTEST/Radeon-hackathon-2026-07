from __future__ import annotations

import copy
import html
import json
from pathlib import Path
import unittest

from prooflaunch_remix.gtm_startup_landscape import (
    GTMStartupLandscapeError,
    compile_startup_distillation_queue,
    compile_startup_landscape,
    compile_startup_positioning_patterns,
    compile_startup_sampling_bridge,
    parse_yc_directory_page,
    verify_startup_distillation_queue,
    verify_startup_landscape,
    verify_startup_positioning_patterns,
    verify_startup_sampling_bridge,
)


ROOT = Path(__file__).resolve().parents[1]
STANDARD = ROOT / "evidence" / "v10" / "gtm-global-organic-signal-sampling-standard-v1.json"


def _company(company_id: int, slug: str, name: str, tags: list[str], team_size: int) -> dict:
    return {
        "id": company_id,
        "slug": slug,
        "name": name,
        "batch_name": "s2025",
        "one_liner": "A focused startup product",
        "website": f"https://{slug}.example",
        "tags": tags,
        "ycdc_status": "Active",
        "year_founded": 2025,
        "team_size": team_size,
        "location": "San Francisco, CA, USA",
        "country": "US",
        "linkedin_url": f"https://linkedin.com/company/{slug}",
        "twitter_url": "",
        "fb_url": "",
        "github_url": "",
    }


def _page(cohort: str, page: int, total: int, companies: list[dict]) -> dict:
    source_url = f"https://www.ycombinator.com/companies/industry/{cohort}?page={page}"
    payload = {
        "component": "CompanyListPage",
        "props": {
            "companies": companies,
            "currentPage": page,
            "totalPages": total,
            "title": cohort,
            "description": cohort,
        },
    }
    document = f'<div data-page="{html.escape(json.dumps(payload), quote=True)}"></div>'
    return parse_yc_directory_page(document, source_url, cohort)


class GTMStartupLandscapeTests(unittest.TestCase):
    def _landscape(self) -> dict:
        shared = _company(1, "shared", "Shared", ["b2b", "consumer", "artificial-intelligence"], 4)
        pages = [
            _page("b2b", 1, 1, [shared, _company(2, "factory", "Factory", ["manufacturing", "robotics"], 18)]),
            _page("b2c", 1, 1, [shared, _company(3, "market", "Market", ["consumer", "marketplace"], 70)]),
        ]
        return compile_startup_landscape(pages, captured_at="2026-08-04T00:00:00+00:00", minimum_records=3)

    def test_compile_deduplicates_and_preserves_b2b_b2c_mixed(self) -> None:
        landscape = self._landscape()
        verify_startup_landscape(landscape)
        self.assertEqual(landscape["record_count"], 3)
        self.assertEqual(landscape["business_model_counts"], {"b2b": 1, "b2c": 1, "mixed": 1})
        shared = next(record for record in landscape["records"] if record["company_id"] == 1)
        self.assertEqual(shared["directory_cohorts"], ["b2b", "b2c"])
        self.assertEqual(shared["business_model"], "mixed")
        self.assertFalse(shared["training_eligible"])

    def test_industry_stage_and_market_are_explicit_proxies(self) -> None:
        landscape = self._landscape()
        factory = next(record for record in landscape["records"] if record["company_id"] == 2)
        self.assertIn("industrial_manufacturing_robotics", factory["industry_families"])
        self.assertEqual(factory["size_stage_proxy"], "early_6_20")
        self.assertEqual(factory["market_region"], "north_america")

    def test_incomplete_pagination_fails(self) -> None:
        pages = [_page("b2b", 1, 2, [_company(1, "one", "One", ["b2b"], 2)])]
        with self.assertRaisesRegex(GTMStartupLandscapeError, "pagination is incomplete"):
            compile_startup_landscape(pages)

    def test_landscape_digest_detects_tampering(self) -> None:
        landscape = self._landscape()
        tampered = copy.deepcopy(landscape)
        tampered["records"][0]["name"] = "tampered"
        with self.assertRaisesRegex(GTMStartupLandscapeError, "digest"):
            verify_startup_landscape(tampered)

    def test_distillation_queue_is_blocked_and_has_eight_units_per_company(self) -> None:
        landscape = self._landscape()
        queue = compile_startup_distillation_queue(landscape)
        verify_startup_distillation_queue(queue, landscape)
        self.assertEqual(queue["distillation_audit_unit_count"], landscape["record_count"] * 8)
        self.assertTrue(all(len(item["missing_distillation_fields"]) == 8 for item in queue["queue"]))
        self.assertTrue(all(item["training_eligible"] is False for item in queue["queue"]))

    def test_queue_digest_detects_tampering(self) -> None:
        landscape = self._landscape()
        queue = compile_startup_distillation_queue(landscape)
        queue["queue"][0]["training_eligible"] = True
        with self.assertRaisesRegex(GTMStartupLandscapeError, "digest"):
            verify_startup_distillation_queue(queue, landscape)

    def test_sampling_bridge_maps_into_140_cells_and_168_lanes_without_claiming_signals(self) -> None:
        landscape = self._landscape()
        standard = json.loads(STANDARD.read_text(encoding="utf-8"))
        bridge = compile_startup_sampling_bridge(landscape, standard)
        verify_startup_sampling_bridge(bridge, landscape, standard)
        self.assertEqual(bridge["segment_market_cell_count"], 140)
        self.assertEqual(bridge["platform_market_lane_count"], 168)
        self.assertGreaterEqual(bridge["populated_segment_market_cell_count"], 2)
        self.assertTrue(all(cell["recent_signal_status"] == "not_collected_by_this_bridge" for cell in bridge["segment_market_cells"]))

    def test_sampling_bridge_digest_detects_tampering(self) -> None:
        landscape = self._landscape()
        standard = json.loads(STANDARD.read_text(encoding="utf-8"))
        bridge = compile_startup_sampling_bridge(landscape, standard)
        bridge["segment_market_cells"][0]["directory_company_count"] += 1
        with self.assertRaisesRegex(GTMStartupLandscapeError, "digest"):
            verify_startup_sampling_bridge(bridge, landscape, standard)

    def test_positioning_patterns_cover_twenty_profiles_without_claiming_effectiveness(self) -> None:
        landscape = self._landscape()
        standard = json.loads(STANDARD.read_text(encoding="utf-8"))
        patterns = compile_startup_positioning_patterns(landscape, standard)
        verify_startup_positioning_patterns(patterns, landscape, standard)
        self.assertEqual(patterns["profile_count"], 20)
        self.assertEqual(patterns["positioning_frame_count"], 14)
        self.assertTrue(all(profile["performance_status"] == "not_measured" for profile in patterns["profiles"]))
        self.assertTrue(patterns["top_level_generalization_contract"]["frequency_is_not_effectiveness"])

    def test_positioning_pattern_digest_detects_tampering(self) -> None:
        landscape = self._landscape()
        standard = json.loads(STANDARD.read_text(encoding="utf-8"))
        patterns = compile_startup_positioning_patterns(landscape, standard)
        patterns["profiles"][0]["company_count"] += 1
        with self.assertRaisesRegex(GTMStartupLandscapeError, "digest"):
            verify_startup_positioning_patterns(patterns, landscape, standard)


if __name__ == "__main__":
    unittest.main()
