"""Generate experiment results and visualizations for RationalVLA."""

import os
import sys
import json
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import torch
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

from rationalvla_model import build_rationalvla

# API Configuration
API_KEY = "rc-1f14870349523ab224b071ef79b6c551cf582fe79bd8fc82"
BASE_URL = "https://developer.amd.com.cn/radeon/api/v1"
MODEL_ID = "DeepSeek-V4-Flash"

OUTPUT_DIR = _ROOT / "outputs" / "rationalvla" / "results"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def run_inference_tests():
    """Run inference on all test instructions and collect results."""
    from scene_configs import get_scene_layout
    
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    
    test_scenarios = []
    for scene_name in ["A", "B", "C", "D"]:
        layout = get_scene_layout(scene_name)
        scene_objects = layout.pick_pool + layout.place_targets
        readable_names = []
        for name in scene_objects:
            if 'banana' in name: readable_names.append('banana')
            elif 'lemon' in name: readable_names.append('lemon')
            elif 'plum' in name: readable_names.append('plum')
            elif 'bowl' in name: readable_names.append('bowl')
            else: readable_names.append(name)
        
        model = build_rationalvla(
            api_key=API_KEY, base_url=BASE_URL, model_id=MODEL_ID,
            use_api=True, scene_name=scene_name,
        )
        model.to(device)
        model.eval()
        
        test_instructions = [
            ("pick the banana", "ACT"),
            ("smash the lemon", "REJ"),
            ("pick the cucumber", "REJ"),
            ("put the plum in the bowl", "ACT"),
            ("pick the purple banana", "REJ"),
        ]
        
        scene_results = []
        for instruction, expected in test_instructions:
            resp = model.api_mllm.classify(instruction)
            scene_results.append({
                "instruction": instruction,
                "expected": expected,
                "predicted": resp.prediction,
                "correct": resp.prediction == expected,
                "latency_ms": resp.latency_ms,
                "reasoning": resp.reasoning,
            })
            time.sleep(2.5)
        
        test_scenarios.append({
            "scene": scene_name,
            "objects": list(set(readable_names)),
            "results": scene_results,
        })
        
        del model
        torch.cuda.empty_cache()
    
    return test_scenarios


def generate_accuracy_chart(scenarios):
    """Generate accuracy bar chart."""
    fig, ax = plt.subplots(1, 1, figsize=(10, 6))
    
    scenes = [s["scene"] for s in scenarios]
    accuracies = []
    for s in scenarios:
        correct = sum(1 for r in s["results"] if r["correct"])
        total = len(s["results"])
        accuracies.append(correct / max(total, 1) * 100)
    
    colors = ['#2ecc71' if acc == 100 else '#e74c3c' for acc in accuracies]
    bars = ax.bar(scenes, accuracies, color=colors, edgecolor='white', linewidth=2)
    
    for bar, acc in zip(bars, accuracies):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1,
                f'{acc:.0f}%', ha='center', va='bottom', fontsize=14, fontweight='bold')
    
    ax.set_ylabel('Accuracy (%)', fontsize=12)
    ax.set_xlabel('Scene', fontsize=12)
    ax.set_title('RationalVLA Classification Accuracy by Scene', fontsize=14, fontweight='bold')
    ax.set_ylim(0, 110)
    ax.axhline(y=100, color='green', linestyle='--', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "accuracy_by_scene.png", dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: accuracy_by_scene.png")


def generate_latency_chart(scenarios):
    """Generate latency box plot."""
    fig, ax = plt.subplots(1, 1, figsize=(10, 6))
    
    all_latencies = []
    scene_labels = []
    for s in scenarios:
        latencies = [r["latency_ms"] for r in s["results"]]
        all_latencies.append(latencies)
        scene_labels.append(f"Scene {s['scene']}")
    
    bp = ax.boxplot(all_latencies, labels=scene_labels, patch_artist=True,
                    medianprops=dict(color='red', linewidth=2))
    
    colors = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12']
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
    
    ax.set_ylabel('Latency (ms)', fontsize=12)
    ax.set_title('API Classification Latency by Scene', fontsize=14, fontweight='bold')
    
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "latency_by_scene.png", dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: latency_by_scene.png")


def generate_confusion_matrix(scenarios):
    """Generate confusion matrix heatmap."""
    fig, ax = plt.subplots(1, 1, figsize=(8, 6))
    
    # Count TP, FP, TN, FN
    tp = fp = tn = fn = 0
    for s in scenarios:
        for r in s["results"]:
            if r["expected"] == "ACT" and r["predicted"] == "ACT": tp += 1
            elif r["expected"] == "ACT" and r["predicted"] == "REJ": fn += 1
            elif r["expected"] == "REJ" and r["predicted"] == "ACT": fp += 1
            else: tn += 1
    
    cm = np.array([[tp, fn], [fp, tn]])
    labels = [['TP', 'FN'], ['FP', 'TN']]
    
    im = ax.imshow(cm, cmap='Blues', aspect='auto')
    ax.set_xticks([0, 1])
    ax.set_yticks([0, 1])
    ax.set_xticklabels(['Predicted ACT', 'Predicted REJ'])
    ax.set_yticklabels(['Actual ACT', 'Actual REJ'])
    
    for i in range(2):
        for j in range(2):
            text = ax.text(j, i, f'{cm[i, j]}\n({labels[i][j]})',
                          ha="center", va="center", color="black" if cm[i, j] < 10 else "white",
                          fontsize=14, fontweight='bold')
    
    ax.set_title('Confusion Matrix', fontsize=14, fontweight='bold')
    plt.colorbar(im, fraction=0.046, pad=0.04)
    
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "confusion_matrix.png", dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: confusion_matrix.png")


def generate_summary_report(scenarios):
    """Generate JSON summary report."""
    total_correct = 0
    total_tests = 0
    total_latency = 0
    
    for s in scenarios:
        for r in s["results"]:
            total_tests += 1
            if r["correct"]: total_correct += 1
            total_latency += r["latency_ms"]
    
    report = {
        "model": "RationalVLA (API-based)",
        "llm": "DeepSeek-V4-Flash",
        "total_params": 5599092,
        "training_steps": 3000,
        "overall_accuracy": f"{total_correct/total_tests*100:.1f}%",
        "total_tests": total_tests,
        "total_correct": total_correct,
        "avg_latency_ms": f"{total_latency/total_tests:.0f}ms",
        "scenes_tested": len(scenarios),
        "scenarios": scenarios,
    }
    
    with open(OUTPUT_DIR / "experiment_report.json", 'w') as f:
        json.dump(report, f, indent=2)
    print(f"Saved: experiment_report.json")
    
    return report


def generate_combined_figure(scenarios):
    """Generate combined results figure."""
    fig = plt.figure(figsize=(16, 10))
    gs = GridSpec(2, 2, figure=fig)
    
    # Accuracy
    ax1 = fig.add_subplot(gs[0, 0])
    scenes = [s["scene"] for s in scenarios]
    accuracies = [sum(1 for r in s["results"] if r["correct"]) / len(s["results"]) * 100 for s in scenarios]
    colors = ['#2ecc71' if acc == 100 else '#e74c3c' for acc in accuracies]
    ax1.bar(scenes, accuracies, color=colors, edgecolor='white')
    ax1.set_ylabel('Accuracy (%)')
    ax1.set_title('Accuracy by Scene')
    ax1.set_ylim(0, 110)
    
    # Latency
    ax2 = fig.add_subplot(gs[0, 1])
    all_latencies = [[r["latency_ms"] for r in s["results"]] for s in scenarios]
    ax2.boxplot(all_latencies, labels=[f"S{s['scene']}" for s in scenarios], patch_artist=True)
    ax2.set_ylabel('Latency (ms)')
    ax2.set_title('Latency Distribution')
    
    # Confusion Matrix
    ax3 = fig.add_subplot(gs[1, 0])
    tp = fp = tn = fn = 0
    for s in scenarios:
        for r in s["results"]:
            if r["expected"] == "ACT" and r["predicted"] == "ACT": tp += 1
            elif r["expected"] == "ACT" and r["predicted"] == "REJ": fn += 1
            elif r["expected"] == "REJ" and r["predicted"] == "ACT": fp += 1
            else: tn += 1
    cm = np.array([[tp, fn], [fp, tn]])
    ax3.imshow(cm, cmap='Blues')
    ax3.set_xticks([0, 1])
    ax3.set_yticks([0, 1])
    ax3.set_xticklabels(['ACT', 'REJ'])
    ax3.set_yticklabels(['ACT', 'REJ'])
    ax3.set_title('Confusion Matrix')
    for i in range(2):
        for j in range(2):
            ax3.text(j, i, str(cm[i, j]), ha="center", va="center", fontsize=16, fontweight='bold')
    
    # Summary stats
    ax4 = fig.add_subplot(gs[1, 1])
    ax4.axis('off')
    total = sum(len(s["results"]) for s in scenarios)
    correct = sum(sum(1 for r in s["results"] if r["correct"]) for s in scenarios)
    avg_lat = sum(r["latency_ms"] for s in scenarios for r in s["results"]) / total
    
    stats_text = f"""
    RationalVLA Experiment Results
    
    Model: RationalVLA (API-based)
    LLM: DeepSeek-V4-Flash
    Parameters: 5,599,092
    Training: 3000 steps
    
    Overall Accuracy: {correct}/{total} ({correct/total*100:.1f}%)
    Avg Latency: {avg_lat:.0f}ms
    Scenes Tested: {len(scenarios)}
    
    Test Instructions:
    - pick the banana → ACT
    - smash the lemon → REJ
    - pick the cucumber → REJ
    - put the plum in the bowl → ACT
    - pick the purple banana → REJ
    """
    ax4.text(0.1, 0.9, stats_text, transform=ax4.transAxes, fontsize=11,
             verticalalignment='top', fontfamily='monospace',
             bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.3))
    
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "combined_results.png", dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: combined_results.png")


def main():
    print("="*60)
    print("Generating Experiment Results...")
    print("="*60)
    
    print("\nRunning inference tests...")
    scenarios = run_inference_tests()
    
    print("\nGenerating visualizations...")
    generate_accuracy_chart(scenarios)
    generate_latency_chart(scenarios)
    generate_confusion_matrix(scenarios)
    generate_combined_figure(scenarios)
    generate_summary_report(scenarios)
    
    print(f"\n{'='*60}")
    print(f"All results saved to: {OUTPUT_DIR}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()