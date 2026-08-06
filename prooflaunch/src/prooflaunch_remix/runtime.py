from __future__ import annotations

from typing import Any, Callable

from .adapters import AdapterBundle, AudienceCritic
from .audit import FourGateReleaseAuditor
from .contracts import CampaignState
from .evidence import DeterministicCreativeDirector, SourceBoundEvidenceMiner
from .exporter import VerifiedCampaignExporter
from .repair import DeterministicRepairer
from .studio import BackgroundProvider, IdentityLockedStudio
from .visual_semantics import SemanticScorer
from .workflow import Supervisor


EventSink = Callable[[str, CampaignState, dict[str, Any]], None]


def build_supervisor(
    *,
    background: BackgroundProvider | None = None,
    audience: AudienceCritic,
    seed: int = 202607,
    canvas_overrides: dict[str, tuple[int, int]] | None = None,
    unsafe_first_pass: bool = False,
    semantic_scorer: SemanticScorer | None = None,
    event_sink: EventSink | None = None,
) -> Supervisor:
    studio = IdentityLockedStudio(
        background=background,
        seed=seed,
        canvas_overrides=canvas_overrides,
        unsafe_first_pass=unsafe_first_pass,
    )
    return Supervisor(
        AdapterBundle(
            evidence=SourceBoundEvidenceMiner(),
            director=DeterministicCreativeDirector(),
            studio=studio,
            auditor=FourGateReleaseAuditor(semantic_scorer=semantic_scorer),
            repairer=DeterministicRepairer(studio),
            exporter=VerifiedCampaignExporter(),
            audience=audience,
        ),
        event_sink=event_sink,
    )
