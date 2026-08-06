from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from prooflaunch_remix.ledger import canonical_json
from prooflaunch_remix.v10_submission_runtime import ProductionRuntimeError
from scripts.run_public_signal_gtm_pilot import run_pilot


def _json_bytes(payload: object) -> bytes:
    return canonical_json(payload).encode("utf-8")


def _product_png() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (96, 96), (24, 86, 170)).save(stream, format="PNG")
    return stream.getvalue()


def _signal_pair() -> tuple[bytes, bytes]:
    snapshot = {
        "schema": "ProofLaunchCreativeSignalSnapshotV1",
        "captured_at": "2026-08-02T18:00:00+00:00",
        "purpose": "creative experiment planning",
        "retention_days": 7,
        "contains_personal_data": False,
        "contains_copied_creative": False,
        "signals": [
            {
                "signal_id": f"signal-{index}",
                "platform": platform,
                "source_kind": "authorized_open_source_collector",
                "source_uri": f"https://example.test/public/{index}",
                "observed_at": "2026-08-02T17:55:00+00:00",
                "rights": "public_measurement",
                "metric": "format_presence",
                "value": index,
                "sample_size": 1,
                "format_features": [feature],
            }
            for index, (platform, feature) in enumerate(
                (
                    ("YouTube", "long_form"),
                    ("YouTube", "subtitles"),
                    ("Vimeo", "public_media"),
                    ("Vimeo", "long_form"),
                    ("Vimeo", "subtitles"),
                ),
                start=1,
            )
        ],
    }
    snapshot_bytes = _json_bytes(snapshot)
    unsigned = {
        "schema": "ProofLaunchOpenSourceSocialCollectionRunV2",
        "plan_sha256": hashlib.sha256(b"public-signal-pilot-plan").hexdigest(),
        "captured_at": snapshot["captured_at"],
        "status": "completed",
        "runs": [
            {
                "source_url_sha256": hashlib.sha256(b"youtube").hexdigest(),
                "connector_id": "yt-dlp",
                "connector_revision": "1" * 40,
                "status": "completed",
                "normalized_signal_count": 2,
                "captcha_or_auth_bypass_attempted": False,
                "raw_content_training_admitted": False,
            },
            {
                "source_url_sha256": hashlib.sha256(b"vimeo").hexdigest(),
                "connector_id": "yt-dlp",
                "connector_revision": "1" * 40,
                "status": "completed",
                "normalized_signal_count": 3,
                "captcha_or_auth_bypass_attempted": False,
                "raw_content_training_admitted": False,
            },
        ],
        "raw_output_isolated": True,
        "pii_and_rights_filter_pending_for_raw": True,
        "derived_signal_filter_passed": True,
        "normalized_signal_count": 5,
        "creative_signal_snapshot_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
        "creative_signal_intelligence_sha256": hashlib.sha256(
            b"public-signal-intelligence"
        ).hexdigest(),
        "training_admitted": False,
        "strategy_mutation_executed": False,
        "external_publish_executed": False,
        "truth_boundary": "Bounded public metadata fixture.",
    }
    receipt = {
        **unsigned,
        "receipt_sha256": hashlib.sha256(_json_bytes(unsigned)).hexdigest(),
    }
    return snapshot_bytes, _json_bytes(receipt)


class PublicSignalGTMPilotTests(unittest.TestCase):
    def test_pilot_binds_public_signals_and_stops_at_human_release(self) -> None:
        snapshot, collection_receipt = _signal_pair()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image_path = root / "product.png"
            snapshot_path = root / "creative-signal-snapshot.json"
            receipt_path = root / "collection-receipt.json"
            image_path.write_bytes(_product_png())
            snapshot_path.write_bytes(snapshot)
            receipt_path.write_bytes(collection_receipt)
            result = run_pilot(
                output_dir=root / "output",
                product_image=image_path,
                signal_snapshot=snapshot_path,
                collection_receipt=receipt_path,
            )
            self.assertEqual(result["status"], "awaiting_human_release")
            self.assertEqual(result["creative_signal_data_class"], "public")
            self.assertEqual(result["run_data_class"], "internal")
            self.assertEqual(result["signal_count"], 5)
            self.assertEqual(set(result["platform_counts"]), {"YouTube", "Vimeo"})
            self.assertGreaterEqual(result["hypothesis_count"], 2)
            self.assertFalse(result["automatic_strategy_mutation_executed"])
            self.assertFalse(result["automatic_schedule_mutation_executed"])
            self.assertFalse(result["external_release_executed"])
            self.assertTrue(result["human_release_required"])

    def test_pilot_rejects_a_tampered_collection_receipt(self) -> None:
        snapshot, collection_receipt = _signal_pair()
        tampered = json.loads(collection_receipt)
        tampered["normalized_signal_count"] = 999
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image_path = root / "product.png"
            snapshot_path = root / "creative-signal-snapshot.json"
            receipt_path = root / "collection-receipt.json"
            image_path.write_bytes(_product_png())
            snapshot_path.write_bytes(snapshot)
            receipt_path.write_bytes(_json_bytes(tampered))
            with self.assertRaises(ProductionRuntimeError):
                run_pilot(
                    output_dir=root / "output",
                    product_image=image_path,
                    signal_snapshot=snapshot_path,
                    collection_receipt=receipt_path,
                )


if __name__ == "__main__":
    unittest.main()
