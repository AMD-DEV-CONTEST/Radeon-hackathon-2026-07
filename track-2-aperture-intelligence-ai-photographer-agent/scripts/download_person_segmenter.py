"""Cache the official Torchvision Mask R-CNN weights for offline demo use."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.tools.person_segmenter import weights_cache_path


def main() -> None:
    from torchvision.models.detection import MaskRCNN_ResNet50_FPN_V2_Weights

    weights = MaskRCNN_ResNet50_FPN_V2_Weights.DEFAULT
    weights.get_state_dict(progress=True, check_hash=True)
    checkpoint = weights_cache_path()
    if not checkpoint.is_file():
        raise FileNotFoundError(checkpoint)
    print(f"Person segmentation weights ready: {checkpoint}")
    print(f"Size: {checkpoint.stat().st_size / 1024**2:.1f} MiB")


if __name__ == "__main__":
    main()
