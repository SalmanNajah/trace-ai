"""Generate report-quality charts from iTrust benchmark results.

Produces annotated, publication-ready charts with clear subtitles
explaining each metric for inclusion in academic reports.
"""

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 11,
    "axes.titlesize": 14,
    "axes.titleweight": "bold",
    "figure.facecolor": "white",
})

RESULTS_PATH = Path(__file__).parent.parent / "data" / "benchmarks" / "iTrust" / "eval_results_itrust.json"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "benchmarks" / "iTrust" / "charts"

PALETTE = {
    "blue": "#6366f1",
    "green": "#22c55e",
    "amber": "#f59e0b",
    "red": "#ef4444",
    "teal": "#14b8a6",
    "purple": "#a855f7",
    "slate": "#64748b",
}


def load_results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


def _add_subtitle(fig, text):
    fig.text(0.5, 0.92, text, ha="center", fontsize=9, color="#64748b", style="italic")


def chart_aggregate_metrics(data, out_dir):
    """Bar chart of aggregate metrics — auto-filters zero-value entries."""
    all_items = [
        ("Precision@10", data["precision_at_k"], "Correct in\ntop 10", PALETTE["blue"]),
        ("Recall@10", data["recall_at_k"], "Found of all\ncorrect", PALETTE["teal"]),
        ("F1@10", data["f1_at_k"], "Balanced\nP/R score", PALETTE["purple"]),
        ("nDCG@10", data.get("ndcg_at_k", 0), "Ranking\nquality", PALETTE["green"]),
        ("Hit@10", data.get("hit_at_k", data.get("coverage_pct", 0)) / 100.0, "Has \u22651\ncorrect", PALETTE["amber"]),
        ("MRR", data["mrr"], "Avg rank of\n1st correct", "#818cf8"),
        ("MAP", data["map_score"], "Overall\nranking", "#f472b6"),
    ]
    items = [(l, v, d, c) for l, v, d, c in all_items if v > 0.001]
    labels = [i[0] for i in items]
    values = [i[1] for i in items]
    descriptions = [i[2] for i in items]
    colors = [i[3] for i in items]

    fig, ax = plt.subplots(figsize=(max(8, len(items) * 1.6), 5.5))
    bars = ax.bar(labels, values, color=colors, width=0.5, edgecolor="none", zorder=3)

    for bar, val, desc in zip(bars, values, descriptions):
        x = bar.get_x() + bar.get_width() / 2
        ax.text(x, bar.get_height() + 0.012, f"{val:.3f}",
                ha="center", va="bottom", fontsize=11, fontweight="bold")
        ax.text(x, -0.045, desc, ha="center", va="top", fontsize=7.5, color="#64748b")

    ax.set_ylim(0, max(values) * 1.25)
    ax.set_ylabel("Score (0–1 scale)", fontsize=11)
    fig.suptitle("TraceAI — Retrieval Performance on iTrust Benchmark (k=10)",
                 fontsize=14, fontweight="bold", y=0.98)
    _add_subtitle(fig, "Higher is better · 105 requirements with human-verified gold links")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.2, zorder=0)
    ax.tick_params(bottom=False)
    fig.tight_layout(rect=[0, 0.06, 1, 0.90])
    fig.savefig(out_dir / "aggregate_metrics.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ aggregate_metrics.png")


def chart_per_requirement_f1(data, out_dir):
    """Horizontal bar chart of per-requirement F1 scores (top 25)."""
    reqs = sorted(data["per_requirement"], key=lambda r: r["f1_at_k"], reverse=True)
    top = reqs[:25]
    fig, ax = plt.subplots(figsize=(8, 7))
    names = [r["req_key"] for r in top][::-1]
    f1s = [r["f1_at_k"] for r in top][::-1]
    colors = [PALETTE["green"] if f > 0.4 else PALETTE["amber"] if f > 0.15 else PALETTE["red"] for f in f1s]
    ax.barh(names, f1s, color=colors, height=0.65, zorder=3)
    ax.set_xlabel("F1@10 Score", fontsize=11)
    ax.set_title("Best-Performing Requirements (Top 25 by F1)")
    _add_subtitle(fig, "F1 = harmonic mean of Precision and Recall · Green ≥0.4, Amber ≥0.15, Red <0.15")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_xlim(0, 1)
    ax.grid(axis="x", alpha=0.2, zorder=0)
    ax.tick_params(left=False)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(out_dir / "per_requirement_f1.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ per_requirement_f1.png")


def chart_hit_miss(data, out_dir):
    """Donut chart: requirements with ≥1 correct link vs missed."""
    hits = sum(1 for r in data["per_requirement"] if r["has_correct_link"])
    total = len(data["per_requirement"])
    misses = total - hits

    fig, ax = plt.subplots(figsize=(6, 6))
    colors = [PALETTE["green"], PALETTE["red"]]
    wedges, texts, autotexts = ax.pie(
        [hits, misses],
        labels=[f"Found ≥1 correct\n({hits} reqs)", f"No correct link\n({misses} reqs)"],
        colors=colors, autopct="%1.1f%%", startangle=90,
        textprops={"fontsize": 10}, pctdistance=0.78,
        wedgeprops=dict(width=0.4)
    )
    for t in autotexts:
        t.set_fontweight("bold")
        t.set_fontsize(11)
    ax.set_title("Requirement Coverage")
    _add_subtitle(fig, f"Does each requirement have at least 1 correct code link in top 10? · {hits}/{total}")
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(out_dir / "hit_miss_pie.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ hit_miss_pie.png")


def chart_recall_distribution(data, out_dir):
    """Histogram showing how recall varies across requirements."""
    recalls = [r["recall_at_k"] for r in data["per_requirement"]]
    zero_count = sum(1 for r in recalls if r == 0)

    fig, ax = plt.subplots(figsize=(8, 5))
    bins = np.arange(0, 1.1, 0.1)
    n, _, patches = ax.hist(recalls, bins=bins, color=PALETTE["blue"], edgecolor="white",
                            alpha=0.85, zorder=3)
    # Color the zero bin red
    patches[0].set_facecolor(PALETTE["red"])

    mean_r = np.mean(recalls)
    ax.axvline(mean_r, color=PALETTE["amber"], linestyle="--", linewidth=2,
               label=f"Mean Recall: {mean_r:.3f}", zorder=4)
    ax.set_xlabel("Recall@10 (fraction of correct links found)", fontsize=11)
    ax.set_ylabel("Number of Requirements", fontsize=11)
    ax.set_title("Recall Distribution Across Requirements")
    _add_subtitle(fig, f"Red bar = {zero_count} requirements with zero correct links found")
    ax.legend(fontsize=10, loc="upper right")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.2, zorder=0)
    ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(out_dir / "recall_distribution.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ recall_distribution.png")


def chart_precision_recall_scatter(data, out_dir):
    """Scatter plot of Precision vs Recall per requirement."""
    reqs = data["per_requirement"]
    prec = [r["precision_at_k"] for r in reqs]
    rec = [r["recall_at_k"] for r in reqs]

    fig, ax = plt.subplots(figsize=(6.5, 6.5))
    ax.scatter(rec, prec, c=PALETTE["blue"], alpha=0.5, s=50,
               edgecolors=PALETTE["purple"], linewidth=0.5, zorder=3)
    ax.set_xlabel("Recall@10 (completeness — higher finds more correct links)", fontsize=10)
    ax.set_ylabel("Precision@10 (accuracy — higher means fewer false positives)", fontsize=10)
    ax.set_title("Precision vs Recall Trade-off")
    _add_subtitle(fig, "Each dot = one requirement · Top-right corner = ideal performance")
    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(-0.05, 1.05)

    # Add quadrant labels
    ax.text(0.75, 0.85, "Ideal", fontsize=9, color=PALETTE["green"], alpha=0.6, ha="center")
    ax.text(0.25, 0.85, "Precise but\nincomplete", fontsize=8, color=PALETTE["amber"], alpha=0.5, ha="center")
    ax.text(0.75, 0.15, "Complete but\nnoisy", fontsize=8, color=PALETTE["amber"], alpha=0.5, ha="center")
    ax.text(0.25, 0.15, "Poor", fontsize=9, color=PALETTE["red"], alpha=0.5, ha="center")

    ax.axhline(0.5, color="#e2e8f0", linestyle=":", linewidth=1, zorder=1)
    ax.axvline(0.5, color="#e2e8f0", linestyle=":", linewidth=1, zorder=1)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(alpha=0.15, zorder=0)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(out_dir / "precision_recall_scatter.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ precision_recall_scatter.png")


def chart_mrr_by_gold_count(data, out_dir):
    """Box plot: MRR grouped by requirement complexity (gold link count)."""
    from collections import defaultdict
    groups = defaultdict(list)
    for r in data["per_requirement"]:
        gc = r["gold_count"]
        bucket = f"{gc}" if gc <= 5 else "6+"
        groups[bucket].append(r["reciprocal_rank"])
    labels = sorted(groups.keys(), key=lambda x: int(x.replace("+", "")))
    values = [groups[l] for l in labels]
    counts = [len(v) for v in values]
    xlabels = [f"{l}\n(n={c})" for l, c in zip(labels, counts)]

    fig, ax = plt.subplots(figsize=(8, 5))
    bp = ax.boxplot(values, tick_labels=xlabels, patch_artist=True, widths=0.6)
    for patch in bp["boxes"]:
        patch.set_facecolor(PALETTE["blue"])
        patch.set_alpha(0.5)
    for median in bp["medians"]:
        median.set_color(PALETTE["amber"])
        median.set_linewidth(2)
    ax.set_xlabel("Number of Gold (Correct) Code Links per Requirement", fontsize=11)
    ax.set_ylabel("MRR (how high is the first correct result?)", fontsize=11)
    ax.set_title("Ranking Quality by Requirement Complexity")
    _add_subtitle(fig, "MRR=1.0 means correct code is ranked #1 · Lower gold count = simpler requirement")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.2, zorder=0)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(out_dir / "mrr_by_gold_count.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("  ✓ mrr_by_gold_count.png")


def main():
    if not RESULTS_PATH.exists():
        print(f"Error: {RESULTS_PATH} not found. Run benchmark first.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = load_results()

    print(f"\nGenerating report charts from: {RESULTS_PATH}")
    print(f"Output: {OUTPUT_DIR}\n")

    chart_aggregate_metrics(data, OUTPUT_DIR)
    chart_per_requirement_f1(data, OUTPUT_DIR)
    chart_hit_miss(data, OUTPUT_DIR)
    chart_recall_distribution(data, OUTPUT_DIR)
    chart_precision_recall_scatter(data, OUTPUT_DIR)
    chart_mrr_by_gold_count(data, OUTPUT_DIR)

    print(f"\n✅ 6 charts saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
