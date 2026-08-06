#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run fixed-phrase inference for one mouth-ROI NPY clip"
    )
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--mouth-roi", type=Path, required=True)
    parser.add_argument("--language", choices=("zh", "en"), required=True)
    parser.add_argument("--probability-override", type=float, default=None)
    parser.add_argument("--distance-override", type=float, default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    import numpy as np

    from backend.config import Settings
    from command.inference import TorchCommandClassifierBackend

    backend = TorchCommandClassifierBackend(
        Settings(
            command_backend="torch",
            command_classifier_checkpoint=args.checkpoint,
            command_phrase_probability_override=args.probability_override,
            command_phrase_distance_override=args.distance_override,
        )
    )
    mouth_frames = np.load(args.mouth_roi, allow_pickle=False)
    decision = backend.predict(
        mouth_frames, args.language, {"mouthRoi": str(args.mouth_roi)}
    )
    metadata = decision.metadata
    output = {
        "intent": decision.intent,
        "accepted": decision.accepted,
        "executable": decision.executable,
        "confidence": decision.confidence,
        "margin": decision.margin,
        "topK": decision.topK,
        "reason": decision.reason,
        "backend": metadata["backend"],
        "device": str(backend.device),
        "thresholdSource": metadata["thresholdSource"],
        "predictedPhraseId": metadata["predictedPhraseId"],
        "openSetDistance": metadata["openSetDistance"],
        "minProbabilityThreshold": metadata["minProbabilityThreshold"],
        "maxCosineDistanceThreshold": metadata["maxCosineDistanceThreshold"],
        "metadata": {**metadata, "device": str(backend.device)},
    }
    if decision.accepted:
        output.update(
            {
                "phraseId": metadata["phraseId"],
                "matchedPhrase": metadata["matchedPhrase"],
                "displayText": metadata["displayText"],
                "language": metadata["language"],
            }
        )
    else:
        output["rejectionReason"] = metadata.get("rejectionReason", decision.reason)
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
