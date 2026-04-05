#!/usr/bin/env python3
"""Plot scoring history from JSON result files."""
import glob
import json
import os
import sys

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime


def load_results(results_dir):
    files = sorted(glob.glob(os.path.join(results_dir, "score_*.json")))
    runs = []
    for f in files:
        with open(f) as fh:
            data = json.load(fh)
        ts = datetime.fromisoformat(data["timestamp"])
        entry = {"timestamp": ts, "overall": data["overall_score"], "file": os.path.basename(f)}
        tu = data.get("token_usage", {})
        entry["tokens"] = tu.get("total_tokens", 0)
        for cat_name, cat_data in data["categories"].items():
            if cat_data["weight"] > 0:
                entry[cat_name] = cat_data["score"]
        runs.append(entry)
    return runs


def plot(runs, output_path):
    if len(runs) < 2:
        print("Need at least 2 runs to plot.")
        return

    cats = [k for k in runs[0] if k not in ("timestamp", "overall", "file")]
    times = [r["timestamp"] for r in runs]
    indices = list(range(len(runs)))

    has_tokens = any(r.get("tokens", 0) > 0 for r in runs)
    nrows = 3 if has_tokens else 2
    fig, axes = plt.subplots(nrows, 1, figsize=(12, 4 * nrows), sharex=True)
    ax1, ax2 = axes[0], axes[1]

    # Overall score
    overall = [r["overall"] for r in runs]
    ax1.plot(indices, overall, "k-o", linewidth=2.5, markersize=8, label="Overall")
    ax1.fill_between(indices, overall, alpha=0.1, color="black")
    ax1.set_ylabel("Score (0-100)")
    ax1.set_title("PCB Layout Score Over Iterations")
    ax1.legend(loc="lower right")
    ax1.set_ylim(0, 105)
    ax1.grid(True, alpha=0.3)
    for i, v in enumerate(overall):
        ax1.annotate(f"{v:.0f}", (i, v), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=9)

    # Per-category breakdown
    colors = {"trace_widths": "#e74c3c", "drc_markers": "#e67e22", "connectivity": "#2ecc71",
              "placement": "#3498db", "vias": "#9b59b6", "geometry": "#1abc9c"}
    for cat in cats:
        vals = [r.get(cat, 0) for r in runs]
        c = colors.get(cat, "#666")
        ax2.plot(indices, vals, "-o", color=c, linewidth=1.5, markersize=5, label=cat.replace("_", " ").title())

    ax2.set_ylabel("Score (0-100)")
    ax2.legend(loc="lower right", ncol=2, fontsize=8)
    ax2.set_ylim(0, 105)
    ax2.grid(True, alpha=0.3)
    # Token usage (third panel)
    if has_tokens:
        ax3 = axes[2]
        tokens = [r.get("tokens", 0) for r in runs]
        ax3.bar(indices, tokens, color="#e74c3c", alpha=0.7, width=0.6)
        ax3.set_ylabel("Tokens per Run")
        ax3.set_xlabel("Iteration")
        ax3.grid(True, alpha=0.3)
        cumulative = []
        total = 0
        for t in tokens:
            total += t
            cumulative.append(total)
        ax3_twin = ax3.twinx()
        ax3_twin.plot(indices, cumulative, "k--o", markersize=4, linewidth=1.5, label="Cumulative")
        ax3_twin.set_ylabel("Cumulative Tokens")
        ax3_twin.legend(loc="upper left", fontsize=8)
        for i, v in enumerate(tokens):
            if v > 0:
                ax3.annotate(f"{v:,}", (i, v), textcoords="offset points", xytext=(0, 5), ha="center", fontsize=8)

    last_ax = axes[-1]
    last_ax.set_xticks(indices)
    last_ax.set_xticklabels([f"#{i+1}\n{r['timestamp'].strftime('%H:%M')}" for i, r in enumerate(runs)], fontsize=8)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"Plot saved to: {output_path}")


def main():
    results_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "results")
    output = sys.argv[2] if len(sys.argv) > 2 else os.path.join(results_dir, "progress.png")
    runs = load_results(results_dir)
    print(f"Loaded {len(runs)} scoring runs")
    plot(runs, output)


if __name__ == "__main__":
    main()
