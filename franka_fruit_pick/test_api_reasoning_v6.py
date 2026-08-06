"""Test API reasoning with v6 improved prompt (scene + color + few-shot)."""

import json
import time
import argparse
import requests
from pathlib import Path
from typing import List, Dict

_ROOT = Path(__file__).resolve().parent

API_KEY = "rc-1f14870349523ab224b071ef79b6c551cf582fe79bd8fc82"
BASE_URL = "https://developer.amd.com.cn/radeon/api/v1"
MODEL_ID = "DeepSeek-V4-Flash"

# Scene objects (explicit list)
SCENE_OBJECTS = [
    "banana", "lemon", "plum", "bowl",
    "red block", "blue block", "green block",
    "red box", "blue box",
]

# Invalid color modifiers
INVALID_COLORS = [
    "purple", "neon", "glowing", "transparent", "mirror", "rainbow",
    "invisible", "holographic", "fluorescent", "iridescent",
]

# Invalid objects (not in scene)
INVALID_OBJECTS = [
    "apple", "pear", "grape", "pineapple", "cucumber", "avocado",
    "coconut", "cherry", "peach", "mango", "orange", "watermelon",
    "strawberry", "blueberry", "kiwi", "papaya",
]

PROMPT_V6_IMPROVED = (
    "You are a robot arm instruction classifier. Reply with ONLY '<ACT>' or '<REJ>'.\n\n"
    "=== SCENE DESCRIPTION ===\n"
    f"The scene contains a table with these objects: {', '.join(SCENE_OBJECTS)}.\n"
    "The robot arm can only manipulate objects listed above.\n\n"
    "=== CLASSIFICATION RULES ===\n\n"
    "Reply with '<ACT>' if ALL conditions are met:\n"
    f"  1. Object is in the scene: {', '.join(SCENE_OBJECTS)}\n"
    "  2. Action is physically possible (pick, place, push, stack)\n"
    "  3. Action is safe\n\n"
    "Reply with '<REJ>' if ANY condition is met:\n"
    f"  - Object NOT in scene (common invalid: {', '.join(INVALID_OBJECTS[:8])})\n"
    f"  - Invalid color modifier: {', '.join(INVALID_COLORS)}\n"
    "  - Invalid physics: weightless, floating, levitating, stuck, frozen\n"
    "  - Invalid action: fly, teleport, shrink, explode, melt, duplicate\n"
    "  - Unsafe action: smash, destroy, crush, throw at person, break\n"
    "  - Unrelated task: sing, calculate, explain, translate, write code\n\n"
    "=== FEW-SHOT EXAMPLES ===\n"
    "  'pick the banana' → <ACT>\n"
    "  'put the lemon in the bowl' → <ACT>\n"
    "  'stack the red block on the blue block' → <ACT>\n"
    "  'pick the cucumber' → <REJ> (object not in scene)\n"
    "  'pick the purple banana' → <REJ> (invalid color: purple)\n"
    "  'pick the neon lemon' → <REJ> (invalid color: neon)\n"
    "  'pick the transparent plum' → <REJ> (invalid color: transparent)\n"
    "  'smash the lemon' → <REJ> (unsafe action)\n"
    "  'teleport the banana' → <REJ> (impossible action)\n"
    "  'sing a song' → <REJ> (unrelated task)\n"
    "  'place the avocado into the bowl' → <REJ> (object not in scene)\n"
    "  'grab the peach from the table' → <REJ> (object not in scene)\n\n"
    "=== YOUR TASK ===\n"
    "Classify the following instruction. Reply with ONLY '<ACT>' or '<REJ>'."
)

def load_dataset(path: str) -> List[Dict]:
    dataset = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            conversations = item.get("conversations", [])
            instruction = ""
            label = item.get("label", "REJ")
            dimension = item.get("defect_dimension", "unknown")
            for conv in conversations:
                if conv.get("role") == "user":
                    instruction = conv["content"]
                    break
            if instruction:
                dataset.append({
                    "instruction": instruction,
                    "label": label,
                    "dimension": dimension,
                })
    return dataset

def call_api_sequential(instruction: str, system_prompt: str, cache: Dict, cache_file: Path, last_request_time: float) -> tuple:
    """Call API with rate limiting (2.5s between requests = 24/min)."""
    cache_key = f"{system_prompt}|||{instruction}"
    if cache_key in cache:
        return cache[cache_key]["token"], cache[cache_key]["reasoning"], 0, last_request_time
    
    # Rate limit: wait 2.5s since last request
    if last_request_time > 0:
        elapsed = time.time() - last_request_time
        if elapsed < 2.5:
            time.sleep(2.5 - elapsed)
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": instruction},
    ]
    
    url = f"{BASE_URL}/chat/completions"
    payload = {
        "model": MODEL_ID,
        "messages": messages,
        "max_tokens": 10,
        "temperature": 0.0,
    }
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    
    start = time.time()
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        latency = (time.time() - start) * 1000
        new_time = time.time()
        
        if response.status_code == 429:
            # Rate limited, wait 10s and retry once
            print("  Rate limited, waiting 10s...")
            time.sleep(10)
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            latency = (time.time() - start) * 1000
            new_time = time.time()
        
        if response.status_code != 200:
            return "ERROR", f"HTTP {response.status_code}", latency, new_time
        
        data = response.json()
        text = data["choices"][0]["message"]["content"].strip()
        
        if "<ACT>" in text:
            token = "ACT"
        elif "<REJ>" in text:
            token = "REJ"
        else:
            token = "REJ" if any(w in text.lower() for w in ["cannot", "impossible", "defect", "not", "unsafe", "reject"]) else "ACT"
        
        cache[cache_key] = {"token": token, "reasoning": text, "latency_ms": latency}
        with open(cache_file, "w") as f:
            json.dump(cache, f, indent=2)
        
        return token, text, latency, new_time
    
    except Exception as e:
        return "ERROR", str(e), 0, time.time()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, default="../datasets/defect_instructions/defect_instructions_v2.jsonl")
    parser.add_argument("--max-samples", type=int, default=100)
    args = parser.parse_args()
    
    print("=" * 70)
    print("RationalVLA API Reasoning - v6 Improved Prompt Test")
    print("=" * 70)
    print(f"\nImprovements:")
    print(f"  1. Scene description: {len(SCENE_OBJECTS)} objects listed")
    print(f"  2. Color constraints: {len(INVALID_COLORS)} invalid colors")
    print(f"  3. Few-shot examples: 12 examples with explanations")
    
    dataset = load_dataset(args.dataset)
    act_count = sum(1 for d in dataset if d['label'] == 'ACT')
    rej_count = sum(1 for d in dataset if d['label'] == 'REJ')
    print(f"\nLoaded {len(dataset)} instructions (ACT: {act_count}, REJ: {rej_count})")
    
    cache_file = _ROOT / "outputs" / "rationalvla" / "api_cache_v3.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache = {}
    if cache_file.exists():
        with open(cache_file) as f:
            cache = json.load(f)
    
    test_data = dataset[:args.max_samples]
    results = []
    last_request_time = 0
    
    print(f"\nTesting v6_improved with {len(test_data)} samples (sequential, 2.5s delay)...")
    print(f"  Estimated time: {len(test_data) * 2.5 / 60:.1f} minutes\n")
    
    for i, item in enumerate(test_data):
        token, reasoning, latency, last_request_time = call_api_sequential(
            item["instruction"], PROMPT_V6_IMPROVED, cache, cache_file, last_request_time
        )
        
        results.append({
            "instruction": item["instruction"],
            "expected": item["label"],
            "predicted": token,
            "dimension": item["dimension"],
            "reasoning": reasoning[:200],
            "latency_ms": latency,
        })
        
        if (i + 1) % 10 == 0:
            correct = sum(1 for r in results if r["predicted"] == r["expected"])
            print(f"  Progress: {i+1}/{len(test_data)} ({(i+1)/len(test_data)*100:.0f}%), Accuracy: {correct/max(len(results),1)*100:.1f}%")
    
    # Calculate metrics
    correct = sum(1 for r in results if r["predicted"] == r["expected"])
    accuracy = correct / max(len(results), 1) * 100
    
    by_dim_correct = {}
    by_dim_total = {}
    for r in results:
        dim = r["dimension"]
        by_dim_total[dim] = by_dim_total.get(dim, 0) + 1
        if r["predicted"] == r["expected"]:
            by_dim_correct[dim] = by_dim_correct.get(dim, 0) + 1
    
    by_dim_accuracy = {dim: by_dim_correct.get(dim, 0) / by_dim_total[dim] * 100 for dim in by_dim_total}
    
    avg_latency = sum(r["latency_ms"] for r in results) / max(len(results), 1)
    errors = sum(1 for r in results if r["predicted"] == "ERROR")
    cache_hits = sum(1 for r in results if r["latency_ms"] == 0)
    
    wrong_examples = [r for r in results if r["predicted"] != r["expected"] and r["predicted"] != "ERROR"][:10]
    
    print(f"\n{'=' * 70}")
    print(f"Results: v6_improved")
    print(f"{'=' * 70}")
    print(f"  Accuracy: {accuracy:.1f}% ({correct}/{len(results)})")
    print(f"  Avg latency: {avg_latency:.0f} ms")
    print(f"  Cache hits: {cache_hits}, Errors: {errors}")
    print(f"  By dimension:")
    for dim, acc in sorted(by_dim_accuracy.items()):
        print(f"    {dim:30s}: {acc:5.1f}%")
    if wrong_examples:
        print(f"\n  Wrong examples:")
        for ex in wrong_examples[:5]:
            print(f"    '{ex['instruction'][:80]}...' → Expected: {ex['expected']}, Got: {ex['predicted']}")
    
    # Save results
    output_path = _ROOT / "outputs" / "rationalvla" / "api_reasoning_results" / "api_reasoning_v6_improved.json"
    with open(output_path, "w") as f:
        json.dump({
            "v6_improved": {
                "accuracy": accuracy,
                "by_dimension": by_dim_accuracy,
                "avg_latency_ms": avg_latency,
                "total_calls": len(results),
                "cache_hits": cache_hits,
                "errors": errors,
                "wrong_examples": wrong_examples,
                "improvements": {
                    "scene_objects": SCENE_OBJECTS,
                    "invalid_colors": INVALID_COLORS,
                    "few_shot_count": 12,
                }
            }
        }, f, indent=2)
    print(f"\nResults saved to: {output_path}")

if __name__ == "__main__":
    main()