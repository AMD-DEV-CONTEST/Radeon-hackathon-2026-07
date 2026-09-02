from __future__ import annotations

import hashlib
import os
import threading
import urllib.request
from functools import lru_cache
from pathlib import Path

from colorgraph.config import settings

DJI_MAVIC3_DLOG_TO_REC709_URL = (
    "https://terra-1-g.djicdn.com/851d20f7b9f64838a34cd02351370894/"
    "260%20downloads/DJI%20Mavic%203%20D-Log%20to%20Rec.709%20V1.cube"
)
DJI_MAVIC3_DLOG_TO_REC709_SHA256 = (
    "5e21b78dc23af8287b14301ec2c3803e6707385681ad348f4754aae2fd4562ee"
)
DJI_MAVIC3_DLOG_TO_REC709_FILENAME = "dji-mavic3-dlog-to-rec709-v1.cube"

_download_lock = threading.Lock()


class OfficialLutError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _download_official_lut(destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    request = urllib.request.Request(
        DJI_MAVIC3_DLOG_TO_REC709_URL,
        headers={"User-Agent": "ColorGraph/0.1"},
    )
    try:
        with (
            urllib.request.urlopen(request, timeout=30) as response,
            temporary.open("wb") as output,
        ):
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        if _sha256(temporary) != DJI_MAVIC3_DLOG_TO_REC709_SHA256:
            raise OfficialLutError("downloaded DJI LUT failed its SHA-256 integrity check")
        temporary.replace(destination)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        if isinstance(exc, OfficialLutError):
            raise
        raise OfficialLutError(
            "could not download the official DJI Mavic 3 D-Log to Rec.709 LUT; "
            "set COLORGRAPH_DJI_MAVIC3_DLOG_LUT to a downloaded .cube file"
        ) from exc


@lru_cache(maxsize=1)
def ensure_dji_mavic3_dlog_to_rec709_lut() -> Path:
    override = os.getenv("COLORGRAPH_DJI_MAVIC3_DLOG_LUT")
    if override:
        supplied = Path(override).expanduser().resolve()
        if not supplied.is_file():
            raise OfficialLutError(
                f"COLORGRAPH_DJI_MAVIC3_DLOG_LUT does not point to a file: {supplied}"
            )
        return supplied

    destination = (
        settings.cache_dir / "color-transforms" / DJI_MAVIC3_DLOG_TO_REC709_FILENAME
    ).resolve()
    with _download_lock:
        if destination.is_file() and _sha256(destination) == DJI_MAVIC3_DLOG_TO_REC709_SHA256:
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        _download_official_lut(destination)
    return destination
