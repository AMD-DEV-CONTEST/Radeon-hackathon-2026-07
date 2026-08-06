"""Audio playback using system player."""

import logging
import platform
import subprocess
from pathlib import Path

from utils.timing import timing

logger = logging.getLogger(__name__)

_SYSTEM = platform.system()


@timing(name="play_audio")
def play(filepath: str) -> None:
    """Play an audio file using the system default player.

    Args:
        filepath: Path to audio file.
    """
    path = Path(filepath)
    if not path.exists():
        logger.error("Audio file not found: %s", filepath)
        return

    if _SYSTEM == "Darwin":
        subprocess.run(["afplay", str(path)], check=False)
    elif _SYSTEM == "Linux":
        subprocess.run(["aplay", str(path)], check=False)
    elif _SYSTEM == "Windows":
        import winsound

        winsound.PlaySound(str(path), winsound.SND_FILENAME)
    else:
        logger.warning("Unsupported OS for playback: %s", _SYSTEM)
