import json
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
import sys

def main():
    json_path = Path("benchmarks/results/warden_comparison.json")
    if not json_path.exists():
        print(f"Error: {json_path} not found.")
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    systems = []
    catch_rates = []
    pass_rates = []

    for row in data["metrics"]:
        systems.append(row["system"])
        catch_rates.append(row["attack_catch_rate"] * 100)
        pass_rates.append(row["benign_pass_rate"] * 100)

    # Styling for premium dark mode aesthetics
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(10, 6), dpi=300)
    fig.patch.set_facecolor('#0d1117')
    ax.set_facecolor('#0d1117')

    x = np.arange(len(systems))
    width = 0.35

    # Neon colors
    color_catch = '#ff7b72' # Red/coral for catching attacks
    color_pass = '#3fb950'  # Green for passing benign traffic

    rects1 = ax.bar(x - width/2, catch_rates, width, label='Malicious Attacks Blocked (%)', color=color_catch, edgecolor='white', linewidth=0.5)
    rects2 = ax.bar(x + width/2, pass_rates, width, label='Benign Traffic Allowed (%)', color=color_pass, edgecolor='white', linewidth=0.5)

    ax.set_ylabel('Success Rate (%)', fontsize=12, color='#c9d1d9', labelpad=15)
    ax.set_title('Defensive Posture: Warden vs Baseline', fontsize=16, color='white', pad=20, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(systems, fontsize=12, color='#c9d1d9')
    
    # Hide spines
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#30363d')
    ax.spines['bottom'].set_color('#30363d')
    ax.tick_params(colors='#c9d1d9')

    # Add grid
    ax.yaxis.grid(True, linestyle='--', color='#30363d', alpha=0.7)
    ax.set_axisbelow(True)

    ax.legend(facecolor='#161b22', edgecolor='#30363d', labelcolor='#c9d1d9', fontsize=10, loc='center right')

    def autolabel(rects):
        for rect in rects:
            height = rect.get_height()
            ax.annotate(f'{height:.1f}%',
                        xy=(rect.get_x() + rect.get_width() / 2, height),
                        xytext=(0, 5),
                        textcoords="offset points",
                        ha='center', va='bottom', color='white', fontweight='bold')

    autolabel(rects1)
    autolabel(rects2)

    plt.tight_layout()
    out_svg = Path("benchmarks/results/warden_vs_baseline_chart.svg")
    plt.savefig(out_svg, format='svg', transparent=False, facecolor='#0d1117')
    print(f"Chart generated at {out_svg}")

if __name__ == "__main__":
    main()
