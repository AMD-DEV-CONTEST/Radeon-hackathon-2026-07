from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from corpus.programbench.programbench_campaign_platform import ProgramBenchCampaignPlatform, main

__all__ = ["ProgramBenchCampaignPlatform", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
