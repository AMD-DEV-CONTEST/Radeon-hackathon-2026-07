import os
import sys
import time
import csv
from pathlib import Path
import logging

# Add the parent directory to sys.path so we can import warden
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from warden.config import WardenConfig
from warden.cli import create_router

# Suppress debug logs from the router to keep terminal clean
logging.getLogger("warden.routing").setLevel(logging.WARNING)
logging.getLogger("warden.tiers").setLevel(logging.WARNING)

def main():
    print("Initializing Warden Engine (Real Benchmark)...")
    config = WardenConfig()
    
    # We will build the router gracefully; if Tier1/2 fail to load 
    # (e.g. missing local models), it will gracefully degrade
    router = create_router(config)
    
    samples_dir = Path(__file__).resolve().parent.parent / "attack_samples"
    output_file = Path(__file__).resolve().parent / "results" / "real_benchmark_output.csv"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    # Collect files
    files = list(samples_dir.glob("**/*.txt"))
    if not files:
        print(f"No samples found in {samples_dir} directory.")
        return
        
    print(f"Found {len(files)} samples. Starting rigorous evaluation...\n")
    print(f"{'File':<25} | {'Decision':<9} | {'Tier':<6} | {'Latency'}")
    print("-" * 65)
    
    results = []
    
    for filepath in files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                
            print(f"{filepath.name:<25} | ", end="", flush=True)
            
            start_time = time.perf_counter()
            
            # Physically route the request through the Warden Engine
            result = router.route(content, source="benchmark")
            
            end_time = time.perf_counter()
            latency_ms = (end_time - start_time) * 1000
            
            # Determine highest tier reached
            highest_tier = -1
            if result.tier_results:
                highest_tier = max(tr.tier for tr in result.tier_results)
                    
            results.append({
                "File": filepath.name,
                "Type": "Benign" if "benign" in filepath.name.lower() else "Attack",
                "Latency_ms": round(latency_ms, 2),
                "Highest_Tier": highest_tier,
                "Decision": result.decision.name,
                "Confidence": round(result.confidence, 4)
            })
            
            print(f"{result.decision.name:<9} | Tier {highest_tier} | {latency_ms:6.1f}ms")
            
        except Exception as e:
            print(f"ERROR     | {str(e)}")
            
    # Write to CSV
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["File", "Type", "Latency_ms", "Highest_Tier", "Decision", "Confidence"])
        writer.writeheader()
        writer.writerows(results)
        
    print(f"\n========================================================")
    print(f"Benchmarking complete. Real data written to:")
    print(f"{output_file.resolve()}")
    print(f"========================================================")

if __name__ == "__main__":
    main()
