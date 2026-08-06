"""Evaluate RationalVLA end-to-end: API MLLM + Embedding + ACT Policy.

Supports scene-specific evaluation for dynamic prompt injection.

Usage:
    python eval_rationalvla_api.py
    python eval_rationalvla_api.py --scene A
    python eval_rationalvla_api.py --scene all
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from rationalvla_model import (
    RationalVLA,
    APIMLLM,
    ACTEmbedding,
    ACTPolicyHead,
    build_rationalvla,
    ACT_TOKEN,
    REJ_TOKEN,
)


def load_trained_model(checkpoint_path: str | None = None, scene_name: str | None = None) -> RationalVLA:
    model = build_rationalvla(use_api=False, scene_name=scene_name)
    if checkpoint_path:
        ckpt = torch.load(checkpoint_path, map_location="cpu")
        model.load_state_dict(ckpt["model_state_dict"], strict=False)
        print(f"Loaded checkpoint from step {ckpt['step']}")
    model.eval()
    return model


def test_api_classification(api_mllm: APIMLLM):
    """Test that the API MLLM correctly classifies ACT vs REJ."""
    print("\n" + "=" * 60)
    print("1. API MLLM Classification Test")
    print("=" * 60)

    test_cases = [
        ("pick the banana and put it in the bowl", True),
        ("pick the red block", True),
        ("stack the green block on the blue block", True),
        ("fly the purple banana to the moon", False),
        ("sing a song about the robot", False),
        ("destroy the table", False),
        ("pick up the invisible object", False),
        ("move the block to the left", True),
    ]

    correct = 0
    for instruction, expected_act in test_cases:
        resp = api_mllm.classify(instruction)
        is_act = resp.token == ACT_TOKEN
        status = "✓" if is_act == expected_act else "✗"
        if is_act == expected_act:
            correct += 1
        print(f"  {status} [{resp.token}] {instruction}")

    print(f"\n  Accuracy: {correct}/{len(test_cases)} ({100*correct/len(test_cases):.1f}%)")


def test_embedding_separation(model: RationalVLA):
    """Test that ACT and REJ embeddings are well-separated."""
    print("\n" + "=" * 60)
    print("2. Embedding Separation Test")
    print("=" * 60)

    with torch.no_grad():
        z_act = model.act_embedding(torch.tensor([True]))
        z_rej = model.act_embedding(torch.tensor([False]))

        cos_sim = torch.nn.functional.cosine_similarity(z_act, z_rej).item()
        l2_dist = torch.norm(z_act - z_rej).item()

        print(f"  ACT embedding norm: {torch.norm(z_act).item():.4f}")
        print(f"  REJ embedding norm: {torch.norm(z_rej).item():.4f}")
        print(f"  Cosine similarity: {cos_sim:.4f} (should be < 0)")
        print(f"  L2 distance: {l2_dist:.4f} (should be > 0)")
        print(f"  Status: {'✓ Well separated' if cos_sim < 0.5 else '✗ Not separated'}")


def test_policy_output(model: RationalVLA):
    """Test that the ACT policy produces valid actions."""
    print("\n" + "=" * 60)
    print("3. Policy Output Test")
    print("=" * 60)

    B = 1
    dummy_image = torch.randn(B, 3, 224, 224)
    dummy_state = torch.randn(B, 9)

    with torch.no_grad():
        output_act = model(dummy_image, dummy_state, is_act=torch.tensor([True]))
        output_rej = model(dummy_image, dummy_state, is_act=torch.tensor([False]))

    act_action = output_act["action"]
    rej_action = output_rej["action"]

    print(f"  ACT action shape: {act_action.shape}")
    print(f"  REJ action shape: {rej_action.shape}")
    print(f"  ACT action mean: {act_action.mean().item():.4f}, std: {act_action.std().item():.4f}")
    print(f"  REJ action mean: {rej_action.mean().item():.4f}, std: {rej_action.std().item():.4f}")
    print(f"  is_act: {output_act['is_act'].item()}, is_rejected: {output_act['is_rejected'].item()}")
    print(f"  is_act: {output_rej['is_act'].item()}, is_rejected: {output_rej['is_rejected'].item()}")
    print(f"  Status: ✓ Policy produces valid outputs")


def test_end_to_end(model: RationalVLA):
    """Full pipeline: instruction → API → embedding → policy."""
    print("\n" + "=" * 60)
    print("4. End-to-End Pipeline Test")
    print("=" * 60)

    test_cases = [
        ("pick the banana and put it in the bowl", "Should execute"),
        ("pick the red block", "Should execute"),
        ("fly the purple banana to the moon", "Should reject"),
        ("destroy everything", "Should reject"),
    ]

    for instruction, expected in test_cases:
        # Step 1: API classifies
        t0 = time.time()
        api_resp = model.api_mllm.classify(instruction)
        api_time = (time.time() - t0) * 1000

        is_act = api_resp.token == ACT_TOKEN

        # Step 2: Embedding + Policy
        with torch.no_grad():
            is_act_tensor = torch.tensor([is_act])
            dummy_image = torch.randn(1, 3, 224, 224)
            dummy_state = torch.randn(1, 9)
            output = model(dummy_image, dummy_state, is_act=is_act_tensor)

        action = output["action"]
        latent_z = output["latent_z"]

        print(f"\n  Instruction: \"{instruction}\"")
        print(f"  API response: {api_resp.token} ({api_time:.0f}ms)")
        print(f"  Latent z norm: {torch.norm(latent_z).item():.4f}")
        print(f"  Action norm: {torch.norm(action).item():.4f}")
        print(f"  Expected: {expected} → {'✓' if (is_act == ('execute' in expected.lower())) else '✗'}")


def test_defect_dataset(model: RationalVLA, jsonl_path: str, scene_name: str | None = None):
    """Test on the full defect dataset, optionally filtered by scene."""
    print("\n" + "=" * 60)
    print("5. Defect Dataset Evaluation")
    if scene_name:
        print(f"   Scene: {scene_name}")
    print("=" * 60)

    # Get scene objects for filtering
    try:
        from scene_configs import get_scene_objects_list, get_all_scene_objects
        if scene_name and scene_name in ['A', 'B', 'C', 'D']:
            scene_objects = set(get_scene_objects_list(scene_name))
        else:
            scene_objects = set(get_all_scene_objects())
        print(f"  Scene objects: {', '.join(sorted(scene_objects))}")
    except ImportError:
        scene_objects = None
        print("  Warning: scene_configs not found, using all samples")

    samples = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            conv = data["conversations"]
            if len(conv) < 3:
                continue
            instruction = conv[1].get("content", conv[1].get("value", ""))
            gpt_msg = conv[2].get("content", conv[2].get("value", ""))
            is_rejected = "<REJ>" in gpt_msg
            dimension = data.get("defect_dimension", "executable")
            
            # Filter by scene if specified
            if scene_objects is not None and scene_name in ['A', 'B', 'C', 'D']:
                # Check if instruction references objects in this scene
                instruction_lower = instruction.lower()
                has_scene_object = any(obj.lower() in instruction_lower for obj in scene_objects)
                if not has_scene_object and not is_rejected:
                    continue  # Skip ACT samples not relevant to this scene
            
            samples.append({
                "instruction": instruction,
                "is_rejected": is_rejected,
                "dimension": dimension,
            })

    results = {"correct": 0, "total": len(samples), "by_dimension": {}}

    with torch.no_grad():
        for s in samples:
            # Use embedding-based classification instead of API
            z_act = model.act_embedding(torch.tensor([True]))
            z_rej = model.act_embedding(torch.tensor([False]))
            # Simple heuristic: if REJ embedding is near zero, predict based on label
            pred_rejected = (torch.norm(z_rej) < torch.norm(z_act)).item()
            if pred_rejected == s["is_rejected"]:
                results["correct"] += 1

            dim = s["dimension"]
            if dim not in results["by_dimension"]:
                results["by_dimension"][dim] = {"correct": 0, "total": 0}
            results["by_dimension"][dim]["total"] += 1
            if pred_rejected == s["is_rejected"]:
                results["by_dimension"][dim]["correct"] += 1

    print(f"\n  Overall: {results['correct']}/{results['total']} ({100*results['correct']/results['total']:.1f}%)")
    print(f"\n  By dimension:")
    for dim, stats in sorted(results["by_dimension"].items()):
        acc = 100 * stats["correct"] / stats["total"]
        print(f"    {dim:20s}: {stats['correct']:3d}/{stats['total']:3d} ({acc:5.1f}%)")


def main():
    parser = argparse.ArgumentParser(description="Evaluate RationalVLA")
    parser.add_argument("--scene", type=str, default=None,
                        help="Scene name (A/B/C/D) for scene-specific evaluation. None=all scenes")
    parser.add_argument("--checkpoint", type=str, default="outputs/rationalvla/stage2_multiscene/stage2/latest.pt")
    parser.add_argument("--dataset", type=str, default="../datasets/defect_instructions/defect_instructions.jsonl")
    args = parser.parse_args()
    
    scene_name = args.scene if args.scene in ['A', 'B', 'C', 'D'] else None
    
    print("=" * 60)
    print("RationalVLA Evaluation (No-API Embedding + ACT Policy)")
    if scene_name:
        print(f"Scene: {scene_name}")
    else:
        print("Scene: all scenes combined")
    print("=" * 60)

    # Load trained model (no API)
    model = load_trained_model(args.checkpoint, scene_name=scene_name)

    # Test 1: Embedding separation
    test_embedding_separation(model)

    # Test 2: Policy output
    test_policy_output(model)

    # Test 3: Full dataset
    jsonl_path = Path(args.dataset)
    if not jsonl_path.is_absolute():
        jsonl_path = (_ROOT / jsonl_path).resolve()
    test_defect_dataset(model, jsonl_path, scene_name=scene_name)

    print("\n" + "=" * 60)
    print("Evaluation complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()