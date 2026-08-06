"""RationalVLA Inference with v6 Prompt + Scene Injection.

This is the actual inference script that combines:
1. Trained model weights (Stage 2)
2. v6 prompt with dynamic scene description
3. Real-time API classification
4. ACT policy for action generation

Usage:
    python rationalvla_inference.py --scene A --checkpoint ../weights/stage2.pt
    python rationalvla_inference.py --scene A --mode interactive
    python rationalvla_inference.py --scene A --mode batch --dataset ../datasets/defect_instructions/defect_instructions_v2.jsonl
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

import torch
import numpy as np
from rationalvla_model import build_rationalvla, RationalVLA

# API Configuration
API_KEY = "rc-1f14870349523ab224b071ef79b6c551cf582fe79bd8fc82"
BASE_URL = "https://developer.amd.com.cn/radeon/api/v1"
MODEL_ID = "DeepSeek-V4-Flash"


def load_checkpoint(model: RationalVLA, checkpoint_path: str, device: torch.device) -> RationalVLA:
    """Load trained weights into model."""
    if not Path(checkpoint_path).exists():
        print(f"Warning: Checkpoint not found at {checkpoint_path}, using untrained model")
        return model
    
    ckpt = torch.load(checkpoint_path, map_location=device, weights_only=False)
    model.load_state_dict(ckpt.get("model_state_dict", ckpt), strict=False)
    print(f"Loaded checkpoint from {checkpoint_path}")
    if "step" in ckpt:
        print(f"  Step: {ckpt['step']}")
    return model


def inference_single(model: RationalVLA, instruction: str, scene_name: str, device: torch.device) -> dict:
    """Run full inference on a single instruction.
    
    Returns:
        dict with classification result and action (if ACT)
    """
    # Step 1: API classification (v6 prompt with scene injection)
    resp = model.api_mllm.classify(instruction)
    is_act = (resp.prediction == "ACT")
    
    result = {
        "instruction": instruction,
        "scene": scene_name,
        "prediction": resp.prediction,
        "reasoning": resp.reasoning,
        "latency_ms": resp.latency_ms,
        "is_act": is_act,
    }
    
    # Step 2: If ACT, generate action via policy
    if is_act:
        with torch.no_grad():
            # Create dummy inputs (in real usage, these come from cameras/sensors)
            dummy_image = torch.randn(1, 3, 224, 224, device=device)
            dummy_state = torch.randn(1, 9, device=device)
            is_act_tensor = torch.tensor([True], dtype=torch.bool, device=device)
            
            output = model(dummy_image, dummy_state, is_act=is_act_tensor)
            action = output["action"].cpu().numpy()
            
            result["action"] = action.tolist()
            result["action_shape"] = list(action.shape)
    
    return result


def run_interactive(model: RationalVLA, scene_name: str, device: torch.device):
    """Interactive mode: user types instructions, model responds."""
    print(f"\n{'='*60}")
    print(f"RationalVLA Inference (v6 Prompt + Scene Injection)")
    print(f"Scene: {scene_name}")
    print(f"Objects: {model.api_mllm.scene_description}")
    print(f"{'='*60}\n")
    print("Type instructions to classify. 'quit' to exit.\n")
    
    count = 0
    while True:
        try:
            instruction = input("Instruction> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
        
        if not instruction or instruction.lower() in ["quit", "exit", "q"]:
            print("Bye!")
            break
        
        count += 1
        result = inference_single(model, instruction, scene_name, device)
        
        print(f"  [{count}] Prediction: {result['prediction']}")
        print(f"      Reasoning: {result['reasoning'][:80]}...")
        print(f"      Latency: {result['latency_ms']:.0f}ms")
        if result['is_act']:
            print(f"      Action: {result['action_shape']}")
        print()


def run_batch(model: RationalVLA, scene_name: str, dataset_path: str, device: torch.device, max_samples: int = None):
    """Batch mode: evaluate on dataset."""
    print(f"\n{'='*60}")
    print(f"RationalVLA Batch Inference")
    print(f"Scene: {scene_name}")
    print(f"Dataset: {dataset_path}")
    print(f"{'='*60}\n")
    
    # Load dataset
    samples = []
    with open(dataset_path) as f:
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
            dimension = data.get("defect_dimension", "unknown")
            
            samples.append({
                "instruction": instruction,
                "expected": expected,
                "dimension": dimension,
            })
    
    if max_samples:
        samples = samples[:max_samples]
    
    print(f"Testing {len(samples)} samples...\n")
    
    # Run inference
    results = []
    correct = 0
    total = 0
    
    for i, sample in enumerate(samples):
        result = inference_single(model, sample["instruction"], scene_name, device)
        result["expected"] = sample["expected"]
        result["dimension"] = sample["dimension"]
        result["correct"] = (result["prediction"] == sample["expected"])
        
        if result["correct"]:
            correct += 1
        total += 1
        
        status = "✓" if result["correct"] else "✗"
        print(f"[{i+1}/{len(samples)}] {status} Expected: {sample['expected']:3s} | Predicted: {result['prediction']:3s} | {sample['dimension']:30s} | {sample['instruction'][:50]}")
        
        results.append(result)
        
        # Rate limit
        time.sleep(2.5)
    
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
    output_path = Path("outputs/rationalvla/inference_results") / f"inference_{scene_name}_{int(time.time())}.json"
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


def main():
    parser = argparse.ArgumentParser(description="RationalVLA Inference with v6 Prompt")
    parser.add_argument("--scene", type=str, default="A", choices=["A", "B", "C", "D"],
                        help="Scene to use")
    parser.add_argument("--mode", type=str, default="interactive", choices=["interactive", "batch"],
                        help="Inference mode")
    parser.add_argument("--checkpoint", type=str, default=None,
                        help="Path to trained checkpoint")
    parser.add_argument("--dataset", type=str,
                        default="../datasets/defect_instructions/defect_instructions_v2.jsonl",
                        help="Path to dataset (for batch mode)")
    parser.add_argument("--max-samples", type=int, default=None,
                        help="Max samples to test (for batch mode)")
    
    args = parser.parse_args()
    
    # Device
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")
    
    # Build model with v6 prompt + scene injection
    print(f"\nBuilding RationalVLA with v6 prompt...")
    model = build_rationalvla(
        api_key=API_KEY,
        base_url=BASE_URL,
        model_id=MODEL_ID,
        use_api=True,
        scene_name=args.scene,
    )
    
    # Load checkpoint if provided
    if args.checkpoint:
        model = load_checkpoint(model, args.checkpoint, device)
    
    model.to(device)
    
    # Run inference
    if args.mode == "interactive":
        run_interactive(model, args.scene, device)
    else:
        run_batch(model, args.scene, args.dataset, device, args.max_samples)


if __name__ == "__main__":
    main()