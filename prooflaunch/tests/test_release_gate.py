from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageDraw

from prooflaunch_remix.audience_pulse import LexicalAudiencePulse
from prooflaunch_remix.contracts import (
    CampaignRequest,
    ReleaseApproval,
    ReleaseDecision,
    Stage,
)
from prooflaunch_remix.runtime import build_supervisor
from prooflaunch_remix.workflow import Supervisor, WorkflowBlocked


class ReleaseGateTests(unittest.TestCase):
    @staticmethod
    def product(path: Path) -> Path:
        image = Image.new("RGBA", (96, 128), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((8, 6, 88, 120), radius=14, fill=(240, 244, 255, 255))
        draw.rectangle((26, 28, 70, 84), fill=(24, 86, 170, 255))
        image.save(path, format="PNG")
        return path

    def supervisor(self) -> Supervisor:
        return build_supervisor(
            audience=LexicalAudiencePulse(),
            seed=42,
            canvas_overrides={"TikTok": (360, 640)},
        )

    def request(self, root: Path) -> CampaignRequest:
        return CampaignRequest(
            product_name="Aster Arc",
            product_image=str(self.product(root / "product.png")),
            specification_text="Battery life up to 18 hours under the documented test.",
            market="Japan",
            platform="TikTok",
            goal="launch",
            target_emotion="joy",
        )

    @staticmethod
    def approval(state) -> ReleaseApproval:
        return ReleaseApproval.create(
            run_id=state.run_id,
            preview_digest=state.prepared_preview_digest or "",
            decision=ReleaseDecision.APPROVE,
            approver="release-gate-test-reviewer",
            reason="Reviewed the exact persisted preview fixture.",
            issued_at="2026-07-01T00:00:00+00:00",
        )

    def test_verified_exporter_refuses_unapproved_preview(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            supervisor = self.supervisor()
            state = supervisor.prepare(
                self.request(root), str(root / "run"), run_id="unapproved"
            )
            self.assertEqual(state.stage, Stage.AWAITING_RELEASE)
            with self.assertRaisesRegex(RuntimeError, "approval"):
                supervisor.adapters.exporter.export(state)

    def test_release_reloads_state_and_records_content_bound_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            supervisor = self.supervisor()
            prepared = supervisor.prepare(
                self.request(root), str(root / "run"), run_id="approved"
            )
            state = supervisor.release(root / "run", self.approval(prepared))
            self.assertEqual(state.stage, Stage.DELIVER, state.blocked_reason)
            pack = json.loads((root / "run" / "campaign-pack.json").read_text())
            self.assertEqual(pack["status"], "release_approved")
            self.assertEqual(pack["preview_digest"], prepared.prepared_preview_digest)
            self.assertEqual(
                pack["release_approval"]["approval_id"],
                state.release_approval.approval_id,
            )

    def test_asset_toctou_tampering_is_rejected_before_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            supervisor = self.supervisor()
            prepared = supervisor.prepare(
                self.request(root), str(root / "run"), run_id="asset-tamper"
            )
            Path(prepared.assets[0].path).write_bytes(b"replaced-after-audit")
            with self.assertRaisesRegex(WorkflowBlocked, "changed after audit"):
                supervisor.release(root / "run", self.approval(prepared))

    def test_release_resumes_after_approval_checkpoint_interruption(self) -> None:
        class InterruptingExporter:
            def export(self, state):
                del state
                raise KeyboardInterrupt("simulated process interruption")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            healthy = self.supervisor()
            interrupted = Supervisor(
                replace(healthy.adapters, exporter=InterruptingExporter())
            )
            prepared = interrupted.prepare(
                self.request(root), str(root / "run"), run_id="resume-release"
            )
            approval = self.approval(prepared)
            with self.assertRaises(KeyboardInterrupt):
                interrupted.release(root / "run", approval)

            recovered = healthy.release(root / "run", approval)
            self.assertEqual(recovered.stage, Stage.DELIVER, recovered.blocked_reason)
            self.assertTrue(all(Path(path).is_file() for path in recovered.exports))


if __name__ == "__main__":
    unittest.main()
