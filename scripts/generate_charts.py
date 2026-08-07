"""Generate report-quality charts matching Visvesvaraya Technological University (VTU) report.

Produces Figure 6.1, 6.2, and 6.3 exactly as they appear in the Phase 1 project report:
- Figure 6.1: Overall evaluation metrics at k = 10 (overall_metrics.png)
- Figure 6.2: Distribution of rank positions where the first relevant file is retrieved (rank_distribution.png)
- Figure 6.3: Precision@K variation across queries (precision_variation.png)
- Scalability Chart: Timing per stage at different scales (scalability_chart.png)
"""

import csv
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Adjust font and plotting styles for professional publication quality
plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.titleweight": "bold",
    "figure.facecolor": "white",
})

RESULTS_PATH = Path(__file__).parent.parent / "data" / "benchmarks" / "iTrust" / "eval_results_itrust.json"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "benchmarks" / "iTrust" / "charts"


def load_results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


def chart_overall_performance(data, out_dir):
    """Figure 6.1: Overall evaluation metrics at k = 10."""
    if not data.get("requirements_with_gold", 0):
        print("  ! skipping overall_metrics.png (no data in JSON)")
        return
    metrics = [
        ("Precision@10", data["precision_at_k"]),
        ("Recall@10", data["recall_at_k"]),
        ("F1@10", data["f1_at_k"]),
        ("Hit@10", data["hit_at_k"] / 100.0)  # Convert percentage to fraction (0.0 to 1.0)
    ]
    labels = [m[0] for m in metrics]
    values = [m[1] for m in metrics]
    
    fig, ax = plt.subplots(figsize=(6.5, 5))
    bars = ax.bar(labels, values, color="#1b365d", edgecolor="#000000", linewidth=0.8, width=0.45, zorder=3)
    
    # Add labels on top of the bars
    for bar, val in zip(bars, values):
        x = bar.get_x() + bar.get_width() / 2
        ax.text(x, bar.get_height() + 0.015, f"{val:.3f}",
                ha="center", va="bottom", fontsize=10, fontweight="bold")
                
    ax.set_ylim(0, 1.0)
    ax.set_ylabel("Score", fontsize=11)
    ax.set_title("Overall evaluation metrics at k = 10", fontsize=12, fontweight="bold", pad=15)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", linestyle="--", alpha=0.3, zorder=0)
    fig.tight_layout()
    fig.savefig(out_dir / "overall_metrics.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ overall_metrics.png (Figure 6.1)")


def chart_rank_distribution(data, out_dir):
    """Figure 6.2: Distribution of rank positions where the first relevant file is retrieved."""
    if not data.get("per_requirement"):
        print("  ! skipping rank_distribution.png (no data in JSON)")
        return
    counts = {"Rank 1": 0, "Rank 2": 0, "Rank 3": 0, "Not Found": 0}
    
    for req in data.get("per_requirement", []):
        if req.get("gold_count", 0) == 0:
            continue
        if not req.get("has_correct_link", False) or req.get("reciprocal_rank", 0) == 0:
            counts["Not Found"] += 1
        else:
            rank = int(round(1.0 / req["reciprocal_rank"]))
            if rank == 1:
                counts["Rank 1"] += 1
            elif rank == 2:
                counts["Rank 2"] += 1
            elif rank == 3:
                counts["Rank 3"] += 1
            else:
                counts["Not Found"] += 1
                
    labels = ["Rank 1", "Rank 2", "Rank 3", "Not Found"]
    values = [counts[l] for l in labels]
    
    fig, ax = plt.subplots(figsize=(6.5, 5))
    bars = ax.bar(labels, values, color="#1b365d", edgecolor="#000000", linewidth=0.8, width=0.45, zorder=3)
    
    # Add integer value labels on top of the bars
    for bar, val in zip(bars, values):
        x = bar.get_x() + bar.get_width() / 2
        ax.text(x, bar.get_height() + 0.6, str(val),
                ha="center", va="bottom", fontsize=10, fontweight="bold")
                
    ax.set_ylabel("Number of Requirements", fontsize=11)
    ax.set_xlabel("Rank Position of First Relevant Result", fontsize=11)
    ax.set_title("Distribution of rank positions where the first relevant file is retrieved", fontsize=11, fontweight="bold", pad=15)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", linestyle="--", alpha=0.3, zorder=0)
    fig.tight_layout()
    fig.savefig(out_dir / "rank_distribution.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ rank_distribution.png (Figure 6.2)")


def chart_precision_variation(data, out_dir):
    """Figure 6.3: Precision@K variation across queries."""
    # Sort requirements alphabetically to make the plot clean and consistent
    reqs = sorted([r for r in data.get("per_requirement", []) if r.get("gold_count", 0) > 0], key=lambda x: x["req_key"])
    if not reqs:
        print("  ! skipping precision_variation.png (no data in JSON)")
        return
    
    keys = [r["req_key"] for r in reqs]
    precisions = [r["precision_at_k"] for r in reqs]
    
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(keys, precisions, marker="o", color="#1b365d", linestyle="-", linewidth=1.2, markersize=3, zorder=3)
    
    ax.set_ylabel("Precision", fontsize=11)
    ax.set_xlabel("Requirements", fontsize=11)
    ax.set_ylim(-0.02, 0.62)
    ax.set_title("Precision@K variation across queries", fontsize=12, fontweight="bold", pad=15)
    
    # Custom x-ticks to display only a clean, non-overlapping subset of requirements
    # matches the report labels nicely: UC10E1, UC13E1, UC17S3, UC1E1, UC22S2, UC76E1, UC2E2
    vtu_subset = ["UC10E1", "UC13E1", "UC17S3", "UC1E1", "UC22S2", "UC76E1", "UC2E2"]
    
    tick_indices = []
    tick_labels = []
    
    for label in vtu_subset:
        if label in keys:
            tick_indices.append(keys.index(label))
            tick_labels.append(label)
            
    # Add fallback evenly spaced labels if subset not found or too small
    if len(tick_indices) < 3:
        step = max(1, len(keys) // 10)
        tick_indices = list(range(0, len(keys), step))
        if len(keys) - 1 not in tick_indices:
            tick_indices.append(len(keys) - 1)
        tick_labels = [keys[i] for i in tick_indices]
        
    ax.set_xticks(tick_indices)
    ax.set_xticklabels(tick_labels, rotation=45, ha="right", fontsize=9)
    
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="both", linestyle="--", alpha=0.3, zorder=0)
    fig.tight_layout()
    fig.savefig(out_dir / "precision_variation.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ precision_variation.png (Figure 6.3)")


def chart_scalability(out_dir):
    """Performance Scalability Chart (timing per stage across scales)."""
    csv_path = Path(__file__).parent.parent / "data" / "benchmarks" / "iTrust" / "perf_results.csv"
    if not csv_path.exists():
        print(f"Skipping scalability chart: {csv_path} not found.")
        return
        
    scales = []
    embed_req = []
    embed_code = []
    trace_gen = []
    
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            scales.append(row["scale"].capitalize())
            embed_req.append(float(row["embed_req_sec"]))
            embed_code.append(float(row["embed_code_sec"]))
            trace_gen.append(float(row["trace_gen_sec"]))
            
    x = np.arange(len(scales))
    width = 0.25
    
    fig, ax = plt.subplots(figsize=(7.5, 5))
    
    # Using IEEE corporate palette colors with custom edge colors and distinct grayscale-friendly hatches
    rects1 = ax.bar(x - width, embed_req, width, label="Embed Reqs", color="#1b365d", edgecolor="#000000", linewidth=0.8, hatch="//", zorder=3)
    rects2 = ax.bar(x, embed_code, width, label="Embed Code", color="#5c768d", edgecolor="#000000", linewidth=0.8, hatch="\\\\", zorder=3)
    rects3 = ax.bar(x + width, trace_gen, width, label="Trace Link Gen", color="#b9c5cf", edgecolor="#000000", linewidth=0.8, hatch="..", zorder=3)
    
    ax.set_yscale('log')
    ax.set_ylabel("Time (seconds, log scale)", fontsize=11)
    ax.set_title("Performance & Scalability by Dataset Scale", fontsize=12, fontweight="bold", pad=15)
    ax.set_xticks(x)
    ax.set_xticklabels(scales, fontsize=10)
    ax.legend(fontsize=10, loc="upper left")
    
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", linestyle="--", alpha=0.3, which="both", zorder=0)
    
    # Auto-label bar heights
    def autolabel(rects):
        for rect in rects:
            height = rect.get_height()
            label_text = f"{height:.2f}s" if height < 1.0 else f"{height:.1f}s"
            ax.annotate(label_text,
                        xy=(rect.get_x() + rect.get_width() / 2, height),
                        xytext=(0, 3),
                        textcoords="offset points",
                        ha="center", va="bottom", fontsize=8, fontweight="bold")
                        
    autolabel(rects1)
    autolabel(rects2)
    autolabel(rects3)
    
    ax.set_ylim(0.01, 300)
    
    fig.tight_layout()
    fig.savefig(out_dir / "scalability_chart.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ scalability_chart.png (Feature 8)")



def main():
    if not RESULTS_PATH.exists():
        print(f"Error: {RESULTS_PATH} not found. Run benchmark first.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = load_results()

    print(f"\nGenerating publication-quality report charts from: {RESULTS_PATH}")
    print(f"Output: {OUTPUT_DIR}\n")

    chart_overall_performance(data, OUTPUT_DIR)
    chart_rank_distribution(data, OUTPUT_DIR)
    chart_precision_variation(data, OUTPUT_DIR)
    chart_scalability(OUTPUT_DIR)

    print(f"\n✅ Charts saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
