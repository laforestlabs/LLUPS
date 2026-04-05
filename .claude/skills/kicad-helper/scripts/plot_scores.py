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

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

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
    ax2.set_xlabel("Iteration")
    ax2.legend(loc="lower right", ncol=2, fontsize=8)
    ax2.set_ylim(0, 105)
    ax2.grid(True, alpha=0.3)
    ax2.set_xticks(indices)
    ax2.set_xticklabels([f"#{i+1}\n{r['timestamp'].strftime('%H:%M')}" for i, r in enumerate(runs)], fontsize=8)

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
