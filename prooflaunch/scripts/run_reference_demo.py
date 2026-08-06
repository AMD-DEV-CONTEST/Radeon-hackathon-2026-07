from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

from prooflaunch_remix.audience_pulse import LexicalAudiencePulse
from prooflaunch_remix.contracts import (
    CampaignRequest,
    ReleaseApproval,
    ReleaseApprovalKind,
    ReleaseDecision,
    Stage,
)
from prooflaunch_remix.runtime import build_supervisor


def make_product(path: Path) -> None:
    image = Image.new("RGBA", (720, 900), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (95, 55, 625, 835),
        radius=90,
        fill=(245, 248, 255, 255),
        outline=(174, 201, 239, 255),
        width=12,
    )
    draw.rounded_rectangle(
        (185, 180, 535, 565),
        radius=36,
        fill=(16, 74, 154, 255),
    )
    draw.ellipse((275, 655, 445, 825), fill=(255, 187, 76, 255))
    draw.text((282, 335), "18h", fill=(255, 255, 255, 255))
    image.save(path, format="PNG", optimize=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="evidence/local/reference-run")
    parser.add_argument("--unsafe-first-pass", action="store_true")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    product = output / "fixture-product.png"
    make_product(product)
    request = CampaignRequest(
        product_name="Aster Arc",
        product_image=str(product),
        specification_text="Battery life up to 18 hours under the documented test.",
        market="Japan",
        platform="TikTok",
        goal="launch",
        target_emotion="joy",
    )
    supervisor = build_supervisor(
        audience=LexicalAudiencePulse(),
        seed=202607,
        unsafe_first_pass=args.unsafe_first_pass,
    )
    prepared = supervisor.prepare(
        request,
        str(output),
        run_id="local-reference-run",
    )
    fixture_approval = None
    if prepared.stage is Stage.AWAITING_RELEASE:
        fixture_approval = ReleaseApproval.create(
            run_id=prepared.run_id,
            preview_digest=prepared.prepared_preview_digest or "",
            decision=ReleaseDecision.APPROVE,
            approver="offline-reference-fixture",
            reason=(
                "Explicit fixture-only approval for the deterministic reference demo; "
                "this is not a production human approval."
            ),
            kind=ReleaseApprovalKind.FIXTURE,
            issued_at="2026-07-01T00:00:00+00:00",
        )
        state = supervisor.release(output, fixture_approval)
    else:
        state = prepared
    summary = {
        "stage": state.stage.value,
        "repair_count": state.repair_count,
        "asset": state.assets[0].path if state.assets else None,
        "exports": state.exports,
        "blocked_reason": state.blocked_reason,
        "release_approval": (
            fixture_approval.serializable() if fixture_approval is not None else None
        ),
        "approval_truth_boundary": (
            "The bundled decision is an explicit offline fixture approval, not a "
            "production human authorization."
        ),
        "truth_boundary": (
            "This is the offline deterministic compositor, not Radeon model output."
        ),
    }
    (output / "reference-run-summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    raise SystemExit(0 if state.stage is Stage.DELIVER else 1)


if __name__ == "__main__":
    main()
