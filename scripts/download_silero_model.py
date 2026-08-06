"""Download the Silero VAD ONNX model for offline use.

One-time setup: saves a ~2 MB model file to models/. After this, SileroVAD runs with
zero network calls.

Two sources, tried in order:

  1. The upstream file on GitHub.
  2. The ``silero-vad`` wheel on PyPI, which vendors the same ONNX file in its package
     data. This is the fallback for networks that cannot reach GitHub — a corporate
     TLS-intercepting proxy will break the direct download while leaving PyPI usable.

Both paths are verified against the expected SHA-256 before the file is accepted, so a
proxy error page or a truncated transfer fails loudly rather than landing on disk as a
corrupt model.

Usage:
    python scripts/download_silero_model.py
    python scripts/download_silero_model.py --test
"""

import hashlib
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MODEL_URL = "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"

# The copy inside the wheel is byte-identical to the upstream file.
WHEEL_PACKAGE = "silero-vad==6.2.1"
WHEEL_MEMBER = "silero_vad/data/silero_vad.onnx"

EXPECTED_SHA256 = "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3"
EXPECTED_BYTES = 2327524

MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
MODEL_PATH = MODEL_DIR / "silero_vad.onnx"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _verify(path: Path) -> None:
    """Raise unless the file on disk is the model we expect."""
    actual = _sha256(path)
    if actual != EXPECTED_SHA256:
        raise ValueError(
            f"checksum mismatch: expected {EXPECTED_SHA256}, got {actual} "
            f"({path.stat().st_size} bytes). The download was truncated, or a proxy "
            f"returned something that is not the model."
        )


def _from_github(dest: Path) -> None:
    print(f"  trying {MODEL_URL}")
    with tempfile.NamedTemporaryFile(dir=dest.parent, suffix=".part", delete=False) as tmp:
        staging = Path(tmp.name)
    try:
        urllib.request.urlretrieve(MODEL_URL, staging)
        _verify(staging)
        staging.replace(dest)
    finally:
        staging.unlink(missing_ok=True)


def _from_wheel(dest: Path) -> None:
    """Pull the vendored ONNX out of the silero-vad wheel via pip download."""
    import subprocess

    print(f"  trying the {WHEEL_PACKAGE} wheel from PyPI")
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(
            [sys.executable, "-m", "pip", "download", WHEEL_PACKAGE, "--no-deps", "-d", tmpdir],
            check=True,
            capture_output=True,
        )
        wheels = list(Path(tmpdir).glob("*.whl"))
        if not wheels:
            raise FileNotFoundError("pip download produced no wheel")

        staging = Path(tmpdir) / "silero_vad.onnx"
        with zipfile.ZipFile(wheels[0]) as z, z.open(WHEEL_MEMBER) as src:
            with open(staging, "wb") as out:
                shutil.copyfileobj(src, out)

        _verify(staging)
        shutil.move(str(staging), dest)


def download_model() -> str | None:
    """Fetch the model if it is not already present. Returns the path, or None."""
    MODEL_DIR.mkdir(exist_ok=True)

    if MODEL_PATH.exists():
        try:
            _verify(MODEL_PATH)
        except ValueError as e:
            print(f"Existing model is not usable ({e}); re-downloading.")
            MODEL_PATH.unlink()
        else:
            size = MODEL_PATH.stat().st_size
            print(f"Model already present: {MODEL_PATH} ({size} bytes, checksum ok)")
            return str(MODEL_PATH)

    print("Downloading Silero VAD ONNX model...")
    print(f"  To: {MODEL_PATH}")

    failures = []
    for source in (_from_github, _from_wheel):
        try:
            source(MODEL_PATH)
        except Exception as e:  # noqa: BLE001 — report every source before giving up
            print(f"    failed: {type(e).__name__}: {e}")
            failures.append(f"{source.__name__}: {e}")
            continue

        size = MODEL_PATH.stat().st_size
        print(f"  Done. {size} bytes ({size / 1024:.1f} KB), checksum verified.")
        return str(MODEL_PATH)

    print("\n  Every source failed:")
    for f in failures:
        print(f"    - {f}")
    print("\n  Manual download:")
    print(f"  1. Open: {MODEL_URL}")
    print(f"  2. Save to: {MODEL_PATH}")
    print(f"  3. Verify: sha256sum should be {EXPECTED_SHA256}")
    return None


def test_model():
    """Quick check that the ONNX model loads and scores audio."""
    try:
        from audio.vad_onnx import SileroVAD

        if not MODEL_PATH.exists():
            print("Model not found — run the download first")
            return

        vad = SileroVAD(str(MODEL_PATH))
        print("Model loaded successfully!")

        silence = b"\x00" * 1024
        print(f"  Silence:    speech={vad.is_speech(silence)}")

        import math
        import struct

        vad.reset_states()
        samples = [int(20000 * math.sin(2 * math.pi * 440 * t / 16000)) for t in range(512)]
        pcm = struct.pack("<" + "h" * 512, *samples)
        print(f"  440Hz tone: speech={vad.is_speech(pcm)}")

    except Exception as e:
        print(f"  ERROR: {e}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Test the downloaded model")
    args = parser.parse_args()

    if args.test:
        test_model()
    else:
        if download_model() is None:
            sys.exit(1)
