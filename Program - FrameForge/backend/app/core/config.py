"""
FrameForge configuration.

Everything that varies between environments lives here, read from environment
variables. The app now drives a remote video-generation API instead of a local
ComfyUI server, so the only required setup is a provider API token.
"""

import os
from pathlib import Path


class Settings:
    # --- Replicate connection ---
    # Get a token at https://replicate.com/account/api-tokens and set it as
    # REPLICATE_API_TOKEN or pass it at startup.
    REPLICATE_API_TOKEN: str | None = os.getenv("REPLICATE_API_TOKEN")
    REPLICATE_API_BASE: str = os.getenv("REPLICATE_API_BASE", "https://api.replicate.com")
    REPLICATE_API_VERSION: str = os.getenv("REPLICATE_API_VERSION", "v1")

    # Default model: Lightricks' LTX Video image-to-video on Replicate.
    # Format: "owner/name" or "owner/name:version_hash".
    REPLICATE_MODEL: str = os.getenv(
        "REPLICATE_MODEL",
        "lightricks/ltx-video:8c47da666861d081eeb4d1261853087de23923a268a69b63febdf5dc1dee08e4",
    )

    # How long to wait for a single prediction to finish (seconds).
    REPLICATE_TIMEOUT_SECONDS: float = float(
        os.getenv("REPLICATE_TIMEOUT_SECONDS", "600")
    )

    # --- GPU execution options ---
    # Force local GPU execution (disables Replicate API)
    USE_LOCAL_GPU: bool = os.getenv("USE_LOCAL_GPU", "false").lower() == "true"
    
    # Video generation backend selection: "auto", "replicate", "local"
    # "auto": Use Replicate if GPU not available locally, otherwise use local
    # "replicate": Always use Replicate cloud service
    # "local": Always use local GPU (CUDA/ROCm/DirectML)
    VIDEO_GENERATION_MODE: str = os.getenv("VIDEO_GENERATION_MODE", "auto")

    @property
    def replicate_api_url(self) -> str:
        return f"{self.REPLICATE_API_BASE}/{self.REPLICATE_API_VERSION}"

    # --- Paths ---
    # Where FrameForge stores its own state (job records, uploaded source
    # images before they're sent to Replicate, downloaded result videos).
    DATA_DIR: Path = Path(os.getenv("FRAMEFORGE_DATA_DIR", "./data")).resolve()

    # --- Job queue ---
    # How often (seconds) the queue worker polls a prediction's status.
    POLL_INTERVAL_SECONDS: float = float(os.getenv("FRAMEFORGE_POLL_INTERVAL", "2.0"))

    # Max concurrent jobs FrameForge will submit to Replicate at once.
    MAX_CONCURRENT_SUBMITTED: int = int(os.getenv("FRAMEFORGE_MAX_CONCURRENT", "2"))

    def ensure_dirs(self) -> None:
        (self.DATA_DIR / "uploads").mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "outputs").mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "jobs").mkdir(parents=True, exist_ok=True)


settings = Settings()
