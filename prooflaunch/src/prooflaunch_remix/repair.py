from __future__ import annotations

from .contracts import CampaignState, CreativeAsset
from .studio import IdentityLockedStudio


class DeterministicRepairer:
    """Rebuilds layout from source and the saved background; never edits product pixels."""

    def __init__(self, studio: IdentityLockedStudio) -> None:
        self.studio = studio

    def repair(self, state: CampaignState) -> list[CreativeAsset]:
        blocked_ids = {
            finding.asset_id
            for finding in state.release_blockers
            if finding.repair_action
        }
        repaired: list[CreativeAsset] = []
        for asset in state.assets:
            if asset.id not in blocked_ids:
                repaired.append(asset)
                continue
            repaired.append(self.studio.rebuild(state, asset, safe_layout=True))
        return repaired
