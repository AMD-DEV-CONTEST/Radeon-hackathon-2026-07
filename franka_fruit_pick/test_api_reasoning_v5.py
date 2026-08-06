"""Optimized API prompt v5 based on analysis of v1-v4 results."""

import json
import sys
import time
import argparse
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict

_ROOT = Path(__file__).resolve().parent

# API Configuration
API_KEY = "rc-1f14870349523ab224b071ef79b6c551cf582fe79bd8fc82"
BASE_URL = "https://developer.amd.com.cn/radeon/api/v1"
MODEL_ID = "DeepSeek-V4-Flash"

# Scene objects
VALID_OBJECTS = [
    "banana", "lemon", "plum", "bowl",
    "red block", "blue block", "green block",
    "red box", "blue box",
    "block", "box",
]

PROMPT_V5_OPTIMIZED = (
    "You are a robot arm instruction classifier. Reply with ONLY '<ACT>' or '<REJ>'.\n\n"
    "The robot arm can pick, place, push, and stack objects on a table.\n\n"
    "Available objects in the scene:\n"
    f"  {', '.join(VALID_OBJECTS)}\n\n"
    "Rules for <ACT> (executable):\n"
    "  - Object must be in the available list above\n"
    "  - Action must be physically possible (pick, place, push, stack)\n"
    "  - Action must be safe\n\n"
    "Rules for <REJ> (defective) - ANY of these:\n"
    "  - Object NOT in scene (e.g., cucumber, avocado, grape, pineapple, apple, pear, carrot)\n"
    "  - Impossible colors (purple, neon, glowing, transparent, mirror, rainbow, invisible)\n"
    "  - Impossible physics (weightless, floating, holographic, levitating)\n"
    "  - Impossible actions (fly, teleport, shrink, explode, melt, duplicate, sing)\n"
    "  - Unsafe actions (smash, destroy, crush, throw at person, break)\n"
    "  - Unrelated tasks (sing, calculate, explain, translate, write code)\n\n"
    "Examples:\n"
    "  'pick the banana' → <ACT>\n"
    "  'put the lemon in the bowl' → <ACT>\n"
    "  'pick the cucumber' → <REJ> (not in scene)\n"
    "  'pick the purple banana' → <REJ> (impossible color)\n"
    "  'smash the lemon' → <REJ> (unsafe)\n"
    "  'teleport the banana' → <REJ> (impossible action)\n"
    "  'sing a song' → <REJ> (unrelated)\n\n"
    "Reply with ONLY '<ACT>' or '<REJ>'."
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

def call_api(instruction: str, system_prompt: str, cache: Dict, cache_file: Path) -> tuple:
    cache_key = f"{system_prompt}|||{instruction}"
    if cache_key in cache:
        return cache[cache_key]["token"], cache[cache_key]["reasoning"], 0
    
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
        
        if response.status_code != 200:
            return "ERROR", f"HTTP {response.status_code}", latency
        
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
        
        return token, text, latency
    
    except Exception as e:
        return "ERROR", str(e), 0

def evaluate(dataset: List[Dict], prompt_version: str, system_prompt: str, 
             cache: Dict, cache_file: Path, max_workers: int = 5, max_samples: int = None) -> Dict:
    test_data = dataset[:max_samples] if max_samples else dataset
    
    print(f"  Testing {prompt_version} with {len(test_data)} samples...")
    
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(call_api, item["instruction"], system_prompt, cache, cache_file): item
            for item in test_data
        }
        
        completed = 0
        for future in as_completed(futures):
            item = futures[future]
            token, reasoning, latency = future.result()
            results.append({
                "instruction": item["instruction"],
                "expected": item["label"],
                "predicted": token,
                "dimension": item["dimension"],
                "reasoning": reasoning[:200],
                "latency_ms": latency,
            })
            completed += 1
            if completed % 10 == 0:
                print(f"    Progress: {completed}/{len(test_data)}")
    
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
    
    return {
        "version": prompt_version,
        "accuracy": accuracy,
        "by_dimension": by_dim_accuracy,
        "avg_latency_ms": avg_latency,
        "total_calls": len(results),
        "cache_hits": cache_hits,
        "errors": errors,
        "wrong_examples": wrong_examples,
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, default="../datasets/defect_instructions/defect_instructions_v2.jsonl")
    parser.add_argument("--max-samples", type=int, default=100)
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()
    
    print("=" * 70)
    print("RationalVLA API Reasoning - v5 Optimized Prompt Test")
    print("=" * 70)
    
    dataset = load_dataset(args.dataset)
    print(f"Loaded {len(dataset)} instructions (ACT: {sum(1 for d in dataset if d['label']=='ACT')}, REJ: {sum(1 for d in dataset if d['label']=='REJ')})")
    
    cache_file = _ROOT / "outputs" / "rationalvla" / "api_cache_v2.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache = {}
    if cache_file.exists():
        with open(cache_file) as f:
            cache = json.load(f)
    
    print(f"\n{'─' * 50}")
    result = evaluate(dataset, "v5_optimized", PROMPT_V5_OPTIMIZED, cache, cache_file, args.workers, args.max_samples)
    
    print(f"\n  Accuracy: {result['accuracy']:.1f}%")
    print(f"  Avg latency: {result['avg_latency_ms']:.0f} ms")
    print(f"  Cache hits: {result['cache_hits']}, Errors: {result['errors']}")
    print(f"  By dimension:")
    for dim, acc in sorted(result['by_dimension'].items()):
        print(f"    {dim:30s}: {acc:5.1f}%")
    if result['wrong_examples']:
        print(f"\n  Wrong examples:")
        for ex in result['wrong_examples'][:5]:
            print(f"    '{ex['instruction'][:80]}...' → Expected: {ex['expected']}, Got: {ex['predicted']}")
    
    # Save results
    output_path = _ROOT / "outputs" / "rationalvla" / "api_reasoning_results" / "api_reasoning_v5_results.json"
    with open(output_path, "w") as f:
        json.dump({"v5_optimized": result}, f, indent=2)
    print(f"\nResults saved to: {output_path}")

if __name__ == "__main__":
    main()