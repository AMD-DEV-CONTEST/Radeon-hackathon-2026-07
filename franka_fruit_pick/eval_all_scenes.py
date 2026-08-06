"""Evaluate RationalVLA across all scenes with dynamic prompt injection.

This script runs scene-specific evaluation for all 4 scenes (A/B/C/D)
and compares performance across scenes.

Usage:
    python eval_all_scenes.py
    python eval_all_scenes.py --checkpoint outputs/rationalvla/stage2/latest.pt
"""

import argparse
import json
import sys
from pathlib import Path

import torch

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from rationalvla_model import build_rationalvla, ACT_TOKEN, REJ_TOKEN
from scene_configs import get_scene_objects_list, get_all_scene_objects


def evaluate_scene(model, jsonl_path: str, scene_name: str | None = None) -> dict:
    """Evaluate model on defect dataset for a specific scene."""
    
    # Get scene objects
    if scene_name and scene_name in ['A', 'B', 'C', 'D']:
        scene_objects = set(get_scene_objects_list(scene_name))
    else:
        scene_objects = set(get_all_scene_objects())
    
    # Load dataset
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
            if scene_name in ['A', 'B', 'C', 'D']:
                instruction_lower = instruction.lower()
                has_scene_object = any(obj.lower() in instruction_lower for obj in scene_objects)
                if not has_scene_object and not is_rejected:
                    continue
            
            samples.append({
                "instruction": instruction,
                "is_rejected": is_rejected,
                "dimension": dimension,
            })
    
    # Evaluate
    results = {"correct": 0, "total": len(samples), "by_dimension": {}}
    
    with torch.no_grad():
        for s in samples:
            z_act = model.act_embedding(torch.tensor([True]))
            z_rej = model.act_embedding(torch.tensor([False]))
            pred_rejected = (torch.norm(z_rej) < torch.norm(z_act)).item()
            
            if pred_rejected == s["is_rejected"]:
                results["correct"] += 1
            
            dim = s["dimension"]
            if dim not in results["by_dimension"]:
                results["by_dimension"][dim] = {"correct": 0, "total": 0}
            results["by_dimension"][dim]["total"] += 1
            if pred_rejected == s["is_rejected"]:
                results["by_dimension"][dim]["correct"] += 1
    
    results["accuracy"] = results["correct"] / max(results["total"], 1) * 100
    results["scene"] = scene_name or "all"
    results["scene_objects"] = sorted(list(scene_objects))
    
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=str, default="outputs/rationalvla/stage2_multiscene/stage2/latest.pt")
    parser.add_argument("--dataset", type=str, default="../datasets/defect_instructions/defect_instructions.jsonl")
    parser.add_argument("--scenes", type=str, nargs="+", default=['A', 'B', 'C', 'D', 'all'],
                        help="Scenes to evaluate (default: A B C D all)")
    args = parser.parse_args()
    
    # Resolve paths
    ckpt_path = Path(args.checkpoint)
    if not ckpt_path.is_absolute():
        ckpt_path = _ROOT / ckpt_path
    
    jsonl_path = Path(args.dataset)
    if not jsonl_path.is_absolute():
        jsonl_path = _ROOT / jsonl_path
    
    print("=" * 80)
    print("RationalVLA Multi-Scene Evaluation")
    print("=" * 80)
    print(f"Checkpoint: {ckpt_path}")
    print(f"Dataset: {jsonl_path}")
    print(f"Scenes: {', '.join(args.scenes)}")
    
    all_results = {}
    
    for scene_name in args.scenes:
        scene_param = None if scene_name == 'all' else scene_name
        
        print(f"\n{'=' * 80}")
        print(f"Evaluating Scene: {scene_name.upper()}")
        print(f"{'=' * 80}")
        
        # Load model with scene-specific config
        model = build_rationalvla(use_api=False, scene_name=scene_param)
        
        if ckpt_path.exists():
            ckpt = torch.load(ckpt_path, map_location="cpu")
            model.load_state_dict(ckpt["model_state_dict"], strict=False)
            print(f"Loaded checkpoint from step {ckpt['step']}")
        
        model.eval()
        
        # Evaluate
        results = evaluate_scene(model, jsonl_path, scene_param)
        all_results[scene_name] = results
        
        # Print results
        print(f"\nScene {scene_name.upper()} Results:")
        print(f"  Scene objects: {', '.join(results['scene_objects'])}")
        print(f"  Total samples: {results['total']}")
        print(f"  Accuracy: {results['accuracy']:.1f}% ({results['correct']}/{results['total']})")
        print(f"\n  By dimension:")
        for dim, stats in sorted(results["by_dimension"].items()):
            acc = stats["correct"] / max(stats["total"], 1) * 100
            print(f"    {dim:20s}: {stats['correct']:3d}/{stats['total']:3d} ({acc:5.1f}%)")
    
    # Summary comparison
    print(f"\n{'=' * 80}")
    print("Summary: All Scenes Comparison")
    print(f"{'=' * 80}")
    print(f"{'Scene':<10} {'Objects':<40} {'Samples':<10} {'Accuracy':<10}")
    print(f"{'-' * 70}")
    
    for scene_name, results in all_results.items():
        obj_count = len(results['scene_objects'])
        print(f"{scene_name.upper():<10} {obj_count:<40} {results['total']:<10} {results['accuracy']:<10.1f}%")
    
    # Save results
    output_path = _ROOT / "outputs" / "rationalvla" / "eval_results_multi_scene.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()