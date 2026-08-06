"""Analyze v6 API cache results."""

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent

def main():
    cache_file = _ROOT / "outputs" / "rationalvla" / "api_cache_v3.json"
    if not cache_file.exists():
        print("No cache file found")
        return
    
    with open(cache_file) as f:
        cache = json.load(f)
    
    print(f"Total cached API calls: {len(cache)}")
    print("=" * 70)
    
    # Analyze tokens
    tokens = [v['token'] for v in cache.values()]
    act_count = tokens.count('ACT')
    rej_count = tokens.count('REJ')
    error_count = tokens.count('ERROR')
    
    print(f"\nToken distribution:")
    print(f"  ACT:   {act_count} ({act_count/len(tokens)*100:.1f}%)")
    print(f"  REJ:   {rej_count} ({rej_count/len(tokens)*100:.1f}%)")
    print(f"  ERROR: {error_count} ({error_count/len(tokens)*100:.1f}%)")
    
    # Show all results
    print(f"\nAll cached results:")
    for i, (key, val) in enumerate(cache.items()):
        instruction = key.split("|||")[-1]
        token = val['token']
        reasoning = val.get('reasoning', '')[:80]
        print(f"{i+1:2d}. [{token:4s}] {instruction[:70]}")
        if reasoning:
            print(f"      → {reasoning}")
    
    # Calculate average latency
    latencies = [v['latency_ms'] for v in cache.values() if v['latency_ms'] > 0]
    if latencies:
        avg_latency = sum(latencies) / len(latencies)
        print(f"\nAverage latency: {avg_latency:.0f}ms")
        print(f"Min latency: {min(latencies):.0f}ms")
        print(f"Max latency: {max(latencies):.0f}ms")

if __name__ == "__main__":
    main()