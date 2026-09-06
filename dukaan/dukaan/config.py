"""Runtime configuration.

Every value is read from the environment. The only thing that has to change
between a laptop dry run and a real run on the Radeon box is DUKAAN_INSTANCE.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    #: JupyterLab base URL of the Radeon instance, e.g.
    #: https://<host>/instances/<instance-id>. Empty means the mock backend,
    #: which is how the whole pipeline stays testable without burning credits.
    instance: str = field(default_factory=lambda: os.getenv("DUKAAN_INSTANCE", ""))
    #: Where the runner and its outputs live on the instance. Has to sit on the
    #: persistent volume: the container gets restarted out from under you.
    remote_dir: str = field(default_factory=lambda: os.getenv("DUKAAN_REMOTE_DIR", "dukaan"))
    job_timeout_s: int = int(os.getenv("DUKAAN_JOB_TIMEOUT", "1800"))

    #: Generation resolution. The plate is composed at this size and the model
    #: works here, so it is the main lever on both time and VRAM.
    width: int = int(os.getenv("DUKAAN_WIDTH", "768"))
    height: int = int(os.getenv("DUKAAN_HEIGHT", "768"))
    #: LTX compresses time by 8, so frame counts want to be 8n+1.
    frames: int = int(os.getenv("DUKAAN_FRAMES", "49"))
    fps: int = int(os.getenv("DUKAAN_FPS", "25"))
    seed: int = int(os.getenv("DUKAAN_SEED", "7"))
    #: How far the model may drift from the seller's photo. Low keeps the
    #: product honest, which matters more here than a prettier frame.
    strength: float = float(os.getenv("DUKAAN_STRENGTH", "0.7"))
    #: Second pass at 2x resolution. Roughly doubles the run.
    refine: bool = os.getenv("DUKAAN_REFINE", "").lower() in {"1", "true", "yes"}

    out_dir: Path = field(default_factory=lambda: Path(os.getenv("DUKAAN_OUT", "out")))

    @property
    def offline(self) -> bool:
        """No instance configured, so run against the mock backend."""
        return not self.instance

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)


def load() -> Config:
    return Config()
