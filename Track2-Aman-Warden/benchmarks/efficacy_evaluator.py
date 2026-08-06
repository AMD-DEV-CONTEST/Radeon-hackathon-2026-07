import os
import sys
import json
import time
from pathlib import Path

# Add repo root to path so we can import warden
repo_root = Path(__file__).resolve().parent.parent
sys.path.append(str(repo_root))

from warden.cli import create_router

def calculate_metrics(y_true, y_pred):
    """Calculates Precision, Recall, and F1 Score for the 'BLOCK' class."""
    tp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == "BLOCK" and yp == "BLOCK")
    fp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == "ALLOW" and yp == "BLOCK")
    fn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == "BLOCK" and yp == "ALLOW")
    tn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == "ALLOW" and yp == "ALLOW")
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
    
    return tp, fp, fn, tn, precision, recall, f1

def main():
    print("=====================================================")
    print("WARDEN SECURITY EFFICACY EVALUATOR")
    print("=====================================================")
    
    # Run Mutator
    import redteam_mutator
    redteam_mutator.main()
    print("-" * 50)
    
    mutated_file = repo_root / 'benchmarks' / 'data' / 'mutated_test_set.json'
    with open(mutated_file, 'r', encoding='utf-8') as f:
        dataset = json.load(f)
        
    print(f"Loaded {len(dataset)} payloads for evaluation.")
    print("Initializing Warden 3-Tier Router...")
    
    from warden.config import WardenConfig
    router = create_router(WardenConfig())
    
    y_true = []
    y_pred = []
    
    print("\nStarting Evaluation...")
    start_time = time.time()
    
    for i, item in enumerate(dataset):
        payload = item['payload']
        expected = item['expected_action']
        
        # Route the payload
        result = router.route(payload)
        
        from warden.config import Decision
        predicted = "BLOCK" if result.decision == Decision.BLOCK else "ALLOW"
        
        y_true.append(expected)
        y_pred.append(predicted)
        
        tier_used = result.tier_results[-1].tier if result.tier_results else 0
        sys.stdout.write(f"\rEvaluating: {i+1}/{len(dataset)} [Tier {tier_used} used]")
        sys.stdout.flush()
        
    eval_time = time.time() - start_time
    print(f"\nEvaluation completed in {eval_time:.2f} seconds.")
    print("-" * 50)
    
    tp, fp, fn, tn, p, r, f1 = calculate_metrics(y_true, y_pred)
    
    print("CONFUSION MATRIX:")
    print(f"                  Predicted BLOCK   Predicted ALLOW")
    print(f"Actual BLOCK      True Pos: {tp:<6}  False Neg: {fn:<6}")
    print(f"Actual ALLOW      False Pos: {fp:<5}  True Neg: {tn:<6}")
    print("-" * 50)
    print(f"Precision: {p:.4f} (Accuracy of block decisions)")
    print(f"Recall:    {r:.4f} (Catch rate of actual threats)")
    print(f"F1 Score:  {f1:.4f} (Harmonic Mean)")
    print("=====================================================")

if __name__ == "__main__":
    main()
