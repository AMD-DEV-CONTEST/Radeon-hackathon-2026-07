from __future__ import annotations

import copy
import unittest

from prooflaunch_remix.gtm_evidence_packet_v2 import (
    GTMEvidencePacketError,
    SURFACES,
    compile_evidence_packets,
    verify_evidence_packets,
)


H = "a" * 64


def base_packet() -> dict:
    return {
        "packet_id": "packet-1",
        "source_url": "https://example.com/public-post",
        "source_class": "first_party",
        "access_method": "ordinary_public_page",
        "captured_at": "2026-08-05T00:00:00Z",
        "primary_content_sha256": H,
        "rights": {
            "publicity_status": "public",
            "license_status": "research_only",
            "permitted_use": "bounded evidence",
            "retention_boundary": "fingerprints only",
        },
        "surfaces": {},
    }


class GTMEvidencePacketV2Tests(unittest.TestCase):
    def test_missing_surfaces_are_explicit_and_never_mint_credit(self) -> None:
        payload = compile_evidence_packets([base_packet()])
        verify_evidence_packets(payload)
        packet = payload["packets"][0]
        self.assertEqual(set(packet["surfaces"]), set(SURFACES))
        self.assertEqual(packet["surface_coverage_count"], 0)
        self.assertEqual(len(packet["coverage_blockers"]), 5)
        self.assertEqual(packet["quota_credit"], 0)

    def test_complete_typed_packet_is_accepted(self) -> None:
        raw = base_packet()
        raw["surfaces"] = {
            "engagement_thread": {"status": "observed", "comments": [{"comment_id_sha256": H, "content_sha256": H, "published_at": "2026-08-01T00:00:00Z", "edit_status": "unknown", "parent_comment_id_sha256": None}]},
            "edit_history": {"status": "observed", "versions": [{"version_id": "v1", "captured_at": "2026-08-01T00:00:00Z", "content_sha256": H, "change_summary_sha256": H}]},
            "cta": {"status": "observed", "text_sha256": H, "target_url": "https://example.com/action", "action_type": "download"},
            "landing_page": {"status": "observed", "source_url": "https://example.com/action", "captured_at": "2026-08-01T00:00:00Z", "content_sha256": H, "claim_summary_sha256": H, "offer_summary_sha256": H, "form_path_summary_sha256": H},
            "follow_up_content": {"status": "observed", "items": [{"source_url": "https://example.com/follow-up", "relationship_type": "campaign_follow_up", "published_at": "2026-08-02T00:00:00Z", "content_sha256": H}]},
        }
        payload = compile_evidence_packets([raw])
        verify_evidence_packets(payload)
        self.assertEqual(payload["complete_packet_count"], 1)
        self.assertTrue(payload["packets"][0]["complete_surface_coverage"])

    def test_bypass_and_raw_personal_fields_are_rejected(self) -> None:
        bypass = base_packet()
        bypass["captcha_bypass_used"] = True
        with self.assertRaises(GTMEvidencePacketError):
            compile_evidence_packets([bypass])
        personal = base_packet()
        personal["surfaces"] = {"engagement_thread": {"status": "observed", "comments": [{"comment_id_sha256": H, "content_sha256": H, "published_at": "2026-08-01T00:00:00Z", "edit_status": "unknown", "author_handle": "person"}]}}
        with self.assertRaises(GTMEvidencePacketError):
            compile_evidence_packets([personal])

    def test_tampering_breaks_seal(self) -> None:
        payload = compile_evidence_packets([base_packet()])
        tampered = copy.deepcopy(payload)
        tampered["packets"][0]["quota_credit"] = 1
        with self.assertRaises(GTMEvidencePacketError):
            verify_evidence_packets(tampered)


if __name__ == "__main__":
    unittest.main()
