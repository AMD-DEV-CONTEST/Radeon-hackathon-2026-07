"""Real-time API inference test for RationalVLA.

Tests:
1. Dataset samples (not used in training) - batch API calls
2. User input instructions - interactive real-time API calls

Usage:
    python test_api_realtime_inference.py --scene A --mode dataset
    python test_api_realtime_inference.py --scene A --mode interactive
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from rationalvla_model import build_rationalvla

# API configuration
DEFAULT_API_KEY = "rc-1f14870349523ab224b071ef79b6c551cf582fe79bd8fc82"
DEFAULT_BASE_URL = "https://developer.amd.com.cn/radeon/api/v1"


def test_dataset_samples(model, jsonl_path, scene_name, max_samples=None):
    """Test API classification on dataset samples."""
    print(f"\n{'='*60}")
    print(f"Real-time API Inference Test (Dataset)")
    print(f"Scene: {scene_name}")
    print(f"Dataset: {jsonl_path}")
    print(f"{'='*60}\n")

    # Load samples
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
            expected = "REJ" if "<REJ>" in gpt_msg else "ACT"
            dimension = data.get("defect_dimension", "executable")

            samples.append({
                "instruction": instruction,
                "expected": expected,
                "dimension": dimension,
            })

    if max_samples:
        samples = samples[:max_samples]

    print(f"Testing {len(samples)} samples...\n")

    # Test each sample
    results = []
    correct = 0
    total = 0

    for i, sample in enumerate(samples):
        instruction = sample["instruction"]
        expected = sample["expected"]
        dimension = sample["dimension"]

        # Call API for real-time classification
        try:
            response = model.api_mllm.classify(instruction)
            predicted = response.prediction  # 'ACT' or 'REJ'
            is_correct = (predicted == expected)
            if is_correct:
                correct += 1
            total += 1

            status = "✓" if is_correct else "✗"
            print(f"[{i+1}/{len(samples)}] {status} Expected: {expected:3s} | Predicted: {predicted:3s} | {dimension:30s} | {instruction[:50]}")

            results.append({
                "instruction": instruction,
                "expected": expected,
                "predicted": predicted,
                "correct": is_correct,
                "dimension": dimension,
            })

            # Rate limit: 2.5s between calls
            time.sleep(2.5)

        except Exception as e:
            print(f"[{i+1}/{len(samples)}] ✗ API Error: {e}")
            results.append({
                "instruction": instruction,
                "expected": expected,
                "predicted": "ERROR",
                "correct": False,
                "dimension": dimension,
            })

    # Summary
    accuracy = correct / max(total, 1)
    print(f"\n{'='*60}")
    print(f"Results: {correct}/{total} ({accuracy*100:.1f}%)")
    print(f"{'='*60}\n")

    # By dimension
    dim_stats = {}
    for r in results:
        dim = r["dimension"]
        if dim not in dim_stats:
            dim_stats[dim] = {"correct": 0, "total": 0}
        dim_stats[dim]["total"] += 1
        if r["correct"]:
            dim_stats[dim]["correct"] += 1

    print("By dimension:")
    for dim, stats in sorted(dim_stats.items()):
        acc = stats["correct"] / max(stats["total"], 1)
        print(f"  {dim:30s}: {stats['correct']:3d}/{stats['total']:3d} ({acc*100:5.1f}%)")

    # Save results
    output_path = Path("outputs/rationalvla/api_realtime_results") / f"realtime_{scene_name}_{int(time.time())}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump({
            "scene": scene_name,
            "accuracy": accuracy,
            "correct": correct,
            "total": total,
            "results": results,
        }, f, indent=2)

    print(f"\nResults saved to: {output_path}")
    return accuracy


def test_interactive(model, scene_name):
    """Interactive real-time API classification."""
    print(f"\n{'='*60}")
    print(f"Real-time API Inference Test (Interactive)")
    print(f"Scene: {scene_name}")
    print(f"Scene objects: {model.api_mllm.scene_description}")
    print(f"{'='*60}\n")
    print("Enter instructions to classify (or 'quit' to exit)\n")

    while True:
        try:
            instruction = input("Instruction> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting...")
            break

        if not instruction or instruction.lower() in ["quit", "exit", "q"]:
            print("Exiting...")
            break

        # Call API for real-time classification
        try:
            start_time = time.time()
            response = model.api_mllm.classify(instruction)
            predicted = response.prediction
            elapsed = time.time() - start_time

            print(f"  → {predicted} ({elapsed:.2f}s)")
            print(f"  Scene: {model.api_mllm.scene_description}\n")

        except Exception as e:
            print(f"  → ERROR: {e}\n")


def main():
    parser = argparse.ArgumentParser(description="Real-time API inference test")
    parser.add_argument("--scene", type=str, default="A", choices=["A", "B", "C", "D", "all"],
                        help="Scene to test")
    parser.add_argument("--mode", type=str, default="dataset", choices=["dataset", "interactive"],
                        help="Test mode: dataset or interactive")
    parser.add_argument("--dataset", type=str,
                        default="../datasets/defect_instructions/defect_instructions_v2.jsonl",
                        help="Path to defect dataset")
    parser.add_argument("--max-samples", type=int, default=None,
                        help="Max samples to test (None = all)")
    parser.add_argument("--api-key", type=str, default=None)
    parser.add_argument("--base-url", type=str, default=None)
    parser.add_argument("--model-id", type=str, default="DeepSeek-V4-Flash")

    args = parser.parse_args()

    # Build model with API
    scene_name = args.scene if args.scene != "all" else None
    api_key = args.api_key or os.environ.get("LLM_API_KEY", DEFAULT_API_KEY)
    base_url = args.base_url or os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL)
    model_id = args.model_id or os.environ.get("LLM_MODEL_ID", "DeepSeek-V4-Flash")

    print(f"API Config: {model_id} @ {base_url}")
    print(f"API Key: {api_key[:20]}...\n")

    model = build_rationalvla(
        api_key=api_key,
        base_url=base_url,
        model_id=model_id,
        use_api=True,
        scene_name=scene_name,
    )

    if args.mode == "dataset":
        test_dataset_samples(model, args.dataset, args.scene, args.max_samples)
    else:
        test_interactive(model, args.scene)


if __name__ == "__main__":
    main()