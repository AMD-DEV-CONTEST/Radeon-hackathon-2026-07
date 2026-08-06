"""Download the Whisper-tiny checkpoint used to export the WebGPU encoder weights.

This is a build-time dependency, not a runtime one: `scripts/export_whisper_weights.py`
reads the checkpoint to produce the int8 blob and golden vectors that ship in
`frontend/webgpu/whisper/weights/`. The browser never sees this file.

Also fetches the mel filterbank (80 x 201) from the `openai-whisper` sdist. It is a
4 KB asset rather than something to recompute: matching OpenAI's filterbank exactly
matters, since any difference shows up as a systematic offset against the golden
vectors and is easily mistaken for a kernel bug.

Sources are chosen for reachability behind a TLS-intercepting proxy: the checkpoint
comes from the Azure CDN OpenAI publishes to, and the filterbank from PyPI. Both are
verified before being accepted.

Usage:
    python scripts/download_whisper_model.py
"""

import hashlib
import io
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT / "models"

# OpenAI addresses its checkpoints by content hash, so the URL carries its own
# integrity guarantee — the digest below is the same string as the path segment.
CHECKPOINT_SHA256 = "65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9"
CHECKPOINT_URL = (
    f"https://openaipublic.azureedge.net/main/whisper/models/{CHECKPOINT_SHA256}/tiny.pt"
)
CHECKPOINT_BYTES = 75572083
CHECKPOINT_PATH = MODEL_DIR / "whisper-tiny.pt"

WHISPER_PACKAGE = "openai-whisper"
MEL_MEMBER = "whisper/assets/mel_filters.npz"
MEL_PATH = MODEL_DIR / "whisper_mel_filters.npz"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _verify(path: Path, expected: str) -> None:
    actual = _sha256(path)
    if actual != expected:
        raise ValueError(
            f"checksum mismatch: expected {expected}, got {actual} "
            f"({path.stat().st_size} bytes). The download was truncated, or a proxy "
            f"returned something that is not the checkpoint."
        )


def download_checkpoint() -> Path | None:
    MODEL_DIR.mkdir(exist_ok=True)

    if CHECKPOINT_PATH.exists():
        try:
            _verify(CHECKPOINT_PATH, CHECKPOINT_SHA256)
        except ValueError as e:
            print(f"Existing checkpoint is not usable ({e}); re-downloading.")
            CHECKPOINT_PATH.unlink()
        else:
            print(f"Checkpoint already present: {CHECKPOINT_PATH} (checksum ok)")
            return CHECKPOINT_PATH

    print(f"Downloading Whisper-tiny ({CHECKPOINT_BYTES / 1e6:.0f} MB)...")
    print(f"  From: {CHECKPOINT_URL}")
    # Stage to a temp file so a failed transfer never lands on the real path.
    with tempfile.NamedTemporaryFile(dir=MODEL_DIR, suffix=".part", delete=False) as tmp:
        staging = Path(tmp.name)
    try:
        urllib.request.urlretrieve(CHECKPOINT_URL, staging)
        _verify(staging, CHECKPOINT_SHA256)
        staging.replace(CHECKPOINT_PATH)
    except Exception as e:  # noqa: BLE001 — the caller only needs the reason
        print(f"  failed: {type(e).__name__}: {e}")
        print("\n  Manual download:")
        print(f"  1. Open: {CHECKPOINT_URL}")
        print(f"  2. Save to: {CHECKPOINT_PATH}")
        print(f"  3. Verify: sha256sum should be {CHECKPOINT_SHA256}")
        return None
    finally:
        staging.unlink(missing_ok=True)

    print(f"  Done. {CHECKPOINT_PATH.stat().st_size} bytes, checksum verified.")
    return CHECKPOINT_PATH


def download_mel_filters() -> Path | None:
    """Extract mel_filters.npz from the openai-whisper source distribution."""
    if MEL_PATH.exists():
        print(f"Mel filterbank already present: {MEL_PATH}")
        return MEL_PATH

    print(f"Fetching the mel filterbank from the {WHISPER_PACKAGE} sdist...")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(
                [
                    sys.executable, "-m", "pip", "download", WHISPER_PACKAGE,
                    "--no-deps", "--no-binary", ":all:", "-d", tmpdir,
                ],
                check=True,
                capture_output=True,
            )
            sdists = list(Path(tmpdir).glob("*.tar.gz"))
            if not sdists:
                raise FileNotFoundError("pip download produced no sdist")

            with tarfile.open(sdists[0]) as tar:
                member = next(
                    (m for m in tar.getnames() if m.endswith(MEL_MEMBER)),
                    None,
                )
                if member is None:
                    raise FileNotFoundError(f"{MEL_MEMBER} not in {sdists[0].name}")
                src = tar.extractfile(member)
                if src is None:
                    raise FileNotFoundError(f"{member} is not a regular file")
                data = src.read()

        # Only accept it if numpy can actually read the arrays we need.
        import numpy as np

        with np.load(io.BytesIO(data)) as z:
            if "mel_80" not in z:
                raise ValueError(f"mel_80 missing; found {z.files}")
            if z["mel_80"].shape != (80, 201):
                raise ValueError(f"unexpected mel_80 shape {z['mel_80'].shape}")

        MODEL_DIR.mkdir(exist_ok=True)
        MEL_PATH.write_bytes(data)
    except Exception as e:  # noqa: BLE001
        print(f"  failed: {type(e).__name__}: {e}")
        return None

    print(f"  Done. {MEL_PATH} ({len(data)} bytes)")
    return MEL_PATH


def main() -> int:
    ok = download_checkpoint() is not None
    ok = download_mel_filters() is not None and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
