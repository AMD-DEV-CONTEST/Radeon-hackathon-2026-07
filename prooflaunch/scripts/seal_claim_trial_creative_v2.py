from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from prooflaunch_remix.files import atomic_write_text, sha256_file


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-creative-v2"
RECEIPT = OUTPUT / "receipt.json"
PNG = OUTPUT / "claim-trial-v2-1080x1350.png"


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def main() -> None:
    payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
    payload.pop("content_sha256", None)
    with Image.open(PNG) as image:
        size = list(image.size)
        mode = image.mode
    if size != [1080, 1350]:
        raise SystemExit(f"render size drifted: {size}")
    payload["card_png"] = {
        "path": str(PNG.relative_to(ROOT)),
        "sha256": sha256_file(PNG),
        "bytes": PNG.stat().st_size,
        "width": size[0],
        "height": size[1],
        "mode": mode,
    }
    payload["render_contract"] = {
        "engine": "Google Chrome headless",
        "device_scale_factor": 1,
        "exact_1080x1350": True,
        "post_render_image_editing": False,
    }
    payload["content_sha256"] = hashlib.sha256(canonical(payload)).hexdigest()
    atomic_write_text(RECEIPT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"receipt": str(RECEIPT), "content_sha256": payload["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
