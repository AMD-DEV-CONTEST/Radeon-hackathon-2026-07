"""Create a deployment copy of a trained RT-DETR model without changing it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from buildguard.vision.model_artifact import finalize_vision_model


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--source-uri", required=True)
    parser.add_argument("--license", dest="license_name", required=True)
    parser.add_argument("--validated-on-amd", action="store_true")
    args = parser.parse_args()
    manifest = finalize_vision_model(
        args.source,
        args.target,
        model_id=args.model_id,
        revision=args.revision,
        source_uri=args.source_uri,
        license_name=args.license_name,
        validated_on_amd=args.validated_on_amd,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
