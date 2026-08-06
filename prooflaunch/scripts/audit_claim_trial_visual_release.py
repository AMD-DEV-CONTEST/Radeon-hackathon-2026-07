from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.visual_release_gate import evaluate_visual_release, seal


VISION = ROOT / "scripts/macos_vision_ocr.swift"
OUTPUT = ROOT / "evidence/v10/claim-trial-visual-release-gate-v1.json"


SPECS = [
    {
        "artifact_id": "qwen-image-raw-baseline",
        "path": ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baseline-inputs-v1/qwen-image/qwen-image-2512-raw-baseline.png",
        "required_phrases": [
            "PROOFLAUNCH CLAIM TRIAL",
            "WE ASKED OUR OWN AI TO PROVE IT 4A",
            "NO WITNESS",
            "NO VIRALITY EVIDENCE CLAIM REJECTED",
            "PUT YOUR CLAIM ON TRIAL BEFORE THE MARKET DOES",
        ],
        "forbidden_phrases": ["THE PUBLIC SELF CROSS EXAMINATION"],
        "maximum_occurrences": {"PUT YOUR CLAIM ON TRIAL BEFORE THE MARKET DOES": 1},
    },
    {
        "artifact_id": "claim-trial-v1",
        "path": ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-experience-v1/share-card-1080x1350.png",
        "required_phrases": [
            "PROOFLAUNCH CLAIM TRIAL",
            "IT REFUSED TO CALL ITSELF 4A",
            "A 4A GRADE GTM EMPLOYEE THAT MAKES ANY BRAND GO VIRAL",
            "NO WITNESS",
            "INDEPENDENT PREFERENCE OBSERVED ORGANIC BREAKOUT CONVERSION REVENUE",
            "IF YOUR AI WONT CHALLENGE YOUR CLAIM IT ISNT YOUR GTM EMPLOYEE",
        ],
    },
    {
        "artifact_id": "claim-trial-v2",
        "path": ROOT / "artifacts/gtm-last-mile-pk-v1/claim-trial-creative-v2/claim-trial-v2-1080x1350.png",
        "required_phrases": [
            "PROOFLAUNCH CLAIM TRIAL",
            "OUR AI PROMISED VIRAL",
            "A 4A GRADE GTM EMPLOYEE THAT MAKES ANY BRAND GO VIRAL",
            "SO WE MADE IT TESTIFY",
            "NO WITNESS",
            "INDEPENDENT WINS ENTERED",
            "ORGANIC BREAKOUTS OBSERVED",
            "CONVERSIONS ATTRIBUTED",
            "DROP THE HOMEPAGE LINE YOU TRUST LEAST",
        ],
    },
]


def luminance_range(path: Path) -> float:
    with Image.open(path).convert("RGB") as image:
        rgb = np.asarray(image, dtype=np.float32) / 255.0
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    luminance = linear[..., 0] * 0.2126 + linear[..., 1] * 0.7152 + linear[..., 2] * 0.0722
    return float(np.quantile(luminance, 0.95) - np.quantile(luminance, 0.05))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    results = []
    for spec in SPECS:
        path = spec["path"]
        result = subprocess.run(
            ["swift", str(VISION), str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Vision OCR failed for {path}: {result.stderr[-2000:]}")
        observation = json.loads(result.stdout)
        observation["luminance_dynamic_range"] = luminance_range(path)
        gate = evaluate_visual_release(
            artifact_id=spec["artifact_id"],
            expected_width=1080,
            expected_height=1350,
            observation=observation,
            required_phrases=spec["required_phrases"],
            forbidden_phrases=spec.get("forbidden_phrases", []),
            maximum_occurrences=spec.get("maximum_occurrences", {}),
        )
        results.append(
            {
                "artifact_id": spec["artifact_id"],
                "path": str(path.relative_to(ROOT)),
                "sha256": sha256_file(path),
                "ocr_observation": observation,
                "gate": gate,
            }
        )
    core = {
        "schema": "ProofLaunchClaimTrialVisualReleaseAuditV1",
        "artifact_count": len(results),
        "release_ready_count": sum(bool(item["gate"]["release_ready"]) for item in results),
        "results": results,
        "truth_boundary": (
            "Release-gate acceptance proves only deterministic craft prerequisites. It is not a preference vote, "
            "named-product win, publication result, organic breakout, conversion or revenue observation."
        ),
    }
    payload = seal(core)
    atomic_write_text(args.output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "release_ready_count": payload["release_ready_count"],
                "results": [
                    {
                        "artifact_id": item["artifact_id"],
                        "release_ready": item["gate"]["release_ready"],
                        "failure_gates": [failure["gate"] for failure in item["gate"]["failures"]],
                    }
                    for item in results
                ],
                "content_sha256": payload["content_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
