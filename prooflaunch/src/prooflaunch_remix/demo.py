from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adapters import AdapterBundle
from .contracts import (
    AudiencePulse,
    AuditFinding,
    CampaignRequest,
    CampaignState,
    Claim,
    CreativeAsset,
    CreativeBrief,
    Severity,
)
from .workflow import Supervisor


class DemoEvidence:
    def extract(self, request: CampaignRequest) -> list[Claim]:
        source = request.specification_text.strip()
        return [
            Claim(
                id="CLM-001",
                text=source,
                source_ref="demo-specification",
                source_span=source,
                approved=bool(source),
                confidence=1.0,
            )
        ]


class DemoDirector:
    def plan(self, state: CampaignState) -> list[CreativeBrief]:
        return [
            CreativeBrief(
                id="BRF-001",
                headline=f"Meet {state.request.product_name}: {state.claims[0].text}",
                claim_ids=("CLM-001",),
                visual_direction="evidence-forward product launch",
                target_emotion=state.request.target_emotion,
            )
        ]


class DemoStudio:
    def create(self, state: CampaignState) -> list[CreativeAsset]:
        return [
            CreativeAsset(
                id="AST-001",
                path="creative-unsafe-first-pass.png",
                aspect_ratio="9:16",
                seed=42,
                model_ref="mock-rocm-studio",
                metadata={"unsafe_zone": True, "product_layer_locked": True},
            )
        ]


class DemoAuditor:
    def audit(self, state: CampaignState) -> list[AuditFinding]:
        if any(asset.metadata.get("unsafe_zone") for asset in state.assets):
            return [
                AuditFinding(
                    id="AUD-001",
                    category="platform_safe_zone",
                    severity=Severity.ERROR,
                    message="CTA overlaps the platform action rail.",
                    asset_id=state.assets[0].id,
                    repair_action="move_to_safe_zone",
                    evidence={"template": state.request.platform},
                )
            ]
        return []


class DemoRepair:
    def repair(self, state: CampaignState) -> list[CreativeAsset]:
        return [
            CreativeAsset(
                id=asset.id,
                path="creative-repaired.png",
                aspect_ratio=asset.aspect_ratio,
                seed=asset.seed,
                model_ref=asset.model_ref,
                metadata={**asset.metadata, "unsafe_zone": False},
            )
            for asset in state.assets
        ]


class DemoExporter:
    def export(self, state: CampaignState) -> list[str]:
        export_path = state.output_path / "campaign-pack.json"
        export_path.write_text(
            json.dumps(
                {
                    "run_id": state.run_id,
                    "assets": [asset.path for asset in state.assets],
                    "audit_status": "pass",
                    "repairs": state.repair_count,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return [str(export_path)]


class DemoAudience:
    def review(self, brief: CreativeBrief) -> AudiencePulse:
        return AudiencePulse(
            target_emotion=brief.target_emotion,
            predicted_emotion=brief.target_emotion,
            confidence=1.0,
            matched=True,
            model_ref="mock-gemma4-emotion-lora",
            limitations=("Demo prediction; not a measured audience response.",),
        )


def build_demo_supervisor() -> Supervisor:
    return Supervisor(
        AdapterBundle(
            evidence=DemoEvidence(),
            director=DemoDirector(),
            studio=DemoStudio(),
            auditor=DemoAuditor(),
            repairer=DemoRepair(),
            exporter=DemoExporter(),
            audience=DemoAudience(),
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="./demo-output")
    args = parser.parse_args()
    request = CampaignRequest(
        product_name="Aster Arc",
        product_image="fixtures/aster-arc.png",
        specification_text="Battery life up to 18 hours under the documented test.",
        market="Japan",
        platform="TikTok",
        goal="launch",
        target_emotion="joy",
    )
    state = build_demo_supervisor().run(request, args.output, run_id="demo-run")
    print(json.dumps(state.serializable(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
