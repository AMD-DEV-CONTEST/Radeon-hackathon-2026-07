"""RationalVLA + Genesis Real-time Demo.

Combines:
1. Trained RationalVLA model (Stage 2 weights)
2. v6 prompt with dynamic scene description
3. Real-time API classification
4. Genesis simulation with viewer
5. Visual ACT/REJ feedback in simulation

Usage:
    python rationalvla_genesis_demo.py --scene A --checkpoint outputs/rationalvla/stage2/latest.pt
    python rationalvla_genesis_demo.py --scene A --mode interactive
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
import genesis as gs

from rationalvla_model import build_rationalvla, RationalVLA
from build_scene import build_scene
from scene_configs import get_scene_layout

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


def classify_instruction(model: RationalVLA, instruction: str) -> dict:
    """Classify instruction using API with v6 prompt."""
    resp = model.api_mllm.classify(instruction)
    is_act = (resp.prediction == "ACT")
    
    return {
        "instruction": instruction,
        "prediction": resp.prediction,
        "reasoning": resp.reasoning,
        "is_act": is_act,
        "latency_ms": resp.latency_ms,
    }


def run_genesis_demo(scene_name: str, checkpoint_path: str, mode: str = "batch", test_instructions: list = None):
    """Run Genesis simulation with RationalVLA inference."""
    
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")
    
    # Initialize Genesis
    gs.init(backend=gs.cpu)
    print("Genesis initialized with CPU backend")
    
    # Build scene with viewer disabled (headless mode)
    print(f"\nBuilding Genesis scene: {scene_name}")
    scene_bundle = build_scene(scene_id=scene_name, show_viewer=False)
    print(f"Scene built OK")
    
    # Build RationalVLA model
    print(f"\nBuilding RationalVLA with v6 prompt...")
    model = build_rationalvla(
        api_key=API_KEY,
        base_url=BASE_URL,
        model_id=MODEL_ID,
        use_api=True,
        scene_name=scene_name,
    )
    
    # Load checkpoint
    if checkpoint_path:
        model = load_checkpoint(model, checkpoint_path, device)
    
    model.to(device)
    model.eval()
    
    # Get scene objects
    # Get scene objects from layout
    layout = get_scene_layout(scene_name)
    scene_objects = layout.pick_pool + layout.place_targets
    # Convert YCB names to readable names
    readable_names = []
    for name in scene_objects:
        if 'banana' in name:
            readable_names.append('banana')
        elif 'lemon' in name:
            readable_names.append('lemon')
        elif 'plum' in name:
            readable_names.append('plum')
        elif 'bowl' in name:
            readable_names.append('bowl')
        else:
            readable_names.append(name)
    scene_objects = list(set(readable_names))
    print(f"\nScene objects: {', '.join(scene_objects)}")
    print(f"Scene description: {model.api_mllm.scene_description}")
    
    # Start Genesis viewer
    print(f"\n{'='*60}")
    print(f"RationalVLA + Genesis Demo")
    print(f"Scene: {scene_name}")
    print(f"Objects: {', '.join(scene_objects)}")
    print(f"Mode: {mode}")
    print(f"{'='*60}\n")
    
    if mode == "batch":
        # Default test instructions
        if test_instructions is None:
            test_instructions = [
                ("pick the banana", "ACT"),
                ("smash the lemon", "REJ"),
                ("pick the cucumber", "REJ"),
                ("put the plum in the bowl", "ACT"),
                ("pick the purple banana", "REJ"),
            ]
        
        print("Testing instructions:")
        print("-" * 60)
        
        for instruction, expected in test_instructions:
            print(f"\nInstruction: '{instruction}'")
            
            # Classify
            result = classify_instruction(model, instruction)
            
            print(f"  Prediction: {result['prediction']} (expected: {expected})")
            print(f"  Latency: {result['latency_ms']:.0f}ms")
            
            # Visual feedback in Genesis
            if result['is_act']:
                print(f"  [ACT] Would execute policy action")
            else:
                print(f"  [REJ] Rejecting instruction")
            
            # Rate limit
            time.sleep(2.5)
    
    elif mode == "interactive":
        print("Interactive mode - type instructions to classify")
        print("Type 'quit' to exit\n")
        
        while True:
            try:
                instruction = input("Instruction> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye!")
                break
            
            if not instruction or instruction.lower() in ["quit", "exit", "q"]:
                print("Bye!")
                break
            
            result = classify_instruction(model, instruction)
            
            print(f"  Prediction: {result['prediction']}")
            print(f"  Latency: {result['latency_ms']:.0f}ms")
            
            if result['is_act']:
                print(f"  [ACT] Would execute policy action")
            else:
                print(f"  [REJ] Rejecting instruction")
            print()
    
    print(f"\n{'='*60}")
    print(f"Demo complete!")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="RationalVLA + Genesis Demo")
    parser.add_argument("--scene", type=str, default="A", choices=["A", "B", "C", "D"],
                        help="Scene to use")
    parser.add_argument("--checkpoint", type=str, default="outputs/rationalvla/stage2/latest.pt",
                        help="Path to trained checkpoint")
    parser.add_argument("--mode", type=str, default="batch", choices=["batch", "interactive"],
                        help="Demo mode")
    parser.add_argument("--test-instructions", type=str, default=None,
                        help="Path to JSON file with test instructions")
    
    args = parser.parse_args()
    
    # Load test instructions if provided
    test_instructions = None
    if args.test_instructions:
        with open(args.test_instructions) as f:
            test_instructions = json.load(f)
    
    run_genesis_demo(args.scene, args.checkpoint, args.mode, test_instructions)


if __name__ == "__main__":
    main()