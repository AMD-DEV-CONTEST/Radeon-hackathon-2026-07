"""Create a randomly initialized RAD-DINO classification head for testing.

This is intended only for development and CI: it lets the pipeline start
without a real fine-tuned classifier head. Predictions will be random noise,
but the architecture is exercised end-to-end.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import torch

from models.classifier import RADDINOHead
from models.vision_encoder import RADDINOVisionEncoder


def main():
    parser = argparse.ArgumentParser(description="Initialize a random RAD-DINO classifier head")
    parser.add_argument("--output", required=True, help="Output .pt checkpoint path")
    parser.add_argument("--device", default="cpu", help="Device to load encoder on")
    parser.add_argument("--hidden-size", type=int, default=None, help="Override hidden size")
    args = parser.parse_args()

    if args.hidden_size is None:
        print("Loading RAD-DINO to infer hidden size (this may download weights)...")
        encoder = RADDINOVisionEncoder(device=args.device)
        hidden_size = encoder.hidden_size
        print(f"RAD-DINO hidden size: {hidden_size}")
    else:
        hidden_size = args.hidden_size

    num_findings = 8
    head = RADDINOHead(hidden_size, num_findings)
    torch.save({"head": head.state_dict()}, args.output)
    print(f"Saved random classifier head to {args.output}")


if __name__ == "__main__":
    main()
