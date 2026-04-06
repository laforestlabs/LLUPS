#!/usr/bin/env python3
"""Plot experiment loop results from experiments.jsonl.

Usage:
    python3 plot_experiments.py [experiments.jsonl] [output.png]
"""
import json
import os
import sys

import matplotlib.pyplot as plt
import numpy as np


def load_experiments(path):
    experiments = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                experiments.append(json.loads(line))
    return experiments


def plot_experiments(experiments, output_path):
    rounds = [e["round_num"] for e in experiments]
    scores = [e["score"] for e in experiments]
    modes = [e["mode"] for e in experiments]
    kept = [e["kept"] for e in experiments]

    # Running best
    best = []
    cur_best = 0
    for s, k in zip(scores, kept):
        if k:
            cur_best = s
        best.append(cur_best)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7),
                                    gridspec_kw={"hspace": 0.3})

    # Panel 1: Score per round with best line
    for i, (r, s, m, k) in enumerate(zip(rounds, scores, modes, kept)):
        color = "#2ecc71" if k else ("#e74c3c" if m == "major" else "#95a5a6")
        marker = "D" if m == "major" else "o"
        ax1.scatter(r, s, c=color, marker=marker, s=60, zorder=5,
                    edgecolors="black" if k else "none", linewidths=1.5 if k else 0)

    # Best-so-far starts at 0 before first kept — clip to actual scores for display
    first_kept_idx = next((i for i, b in enumerate(best) if b > 0), 0)
    best_display = best[first_kept_idx:]
    rounds_display = rounds[first_kept_idx:]
    ax1.plot(rounds_display, best_display, "k-", linewidth=2, alpha=0.7, label="Best so far")

    # Zoom y-axis to the data range with some padding
    all_scores_nonzero = [s for s in scores if s > 0]
    if all_scores_nonzero:
        y_min = min(all_scores_nonzero) - 1
        y_max = max(all_scores_nonzero) + 1
        ax1.set_ylim(y_min, y_max)

    ax1.set_ylabel("Experiment Score", fontsize=11)
    ax1.set_title("Autoexperiment: PCB Layout Optimization", fontsize=14, fontweight="bold")
    ax1.legend(loc="lower right", fontsize=9)
    ax1.grid(True, alpha=0.3)

    # Custom legend
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], marker='o', color='w', markerfacecolor='#2ecc71',
               markeredgecolor='black', markersize=8, label='Kept (minor)'),
        Line2D([0], [0], marker='D', color='w', markerfacecolor='#2ecc71',
               markeredgecolor='black', markersize=8, label='Kept (major)'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor='#95a5a6',
               markersize=8, label='Discarded (minor)'),
        Line2D([0], [0], marker='D', color='w', markerfacecolor='#e74c3c',
               markersize=8, label='Discarded (major)'),
        Line2D([0], [0], color='black', linewidth=2, label='Best so far'),
    ]
    ax1.legend(handles=legend_elements, loc="lower right", fontsize=7, ncol=3)

    # Panel 2: Config delta heatmap — which params changed in kept experiments
    kept_exps = [e for e in experiments if e["kept"]]
    if kept_exps:
        all_keys = set()
        for e in kept_exps:
            all_keys.update(e.get("config_delta", {}).keys())
        all_keys = sorted(all_keys)

        if all_keys:
            data = []
            labels = []
            for e in kept_exps:
                row = [e["config_delta"].get(k, 0) for k in all_keys]
                data.append(row)
                labels.append(f"R{e['round_num']}")

            ax2.set_title("Config Values (Kept Experiments) — per-param normalized", fontsize=11)
            if len(data) > 0 and len(data[0]) > 0:
                arr = np.array(data).T  # shape: (params, experiments)
                # Normalize each param row to 0-1 so different scales don't blow out
                for row_i in range(arr.shape[0]):
                    row_min, row_max = arr[row_i].min(), arr[row_i].max()
                    if row_max - row_min > 1e-9:
                        arr[row_i] = (arr[row_i] - row_min) / (row_max - row_min)
                    else:
                        arr[row_i] = 0.5
                im = ax2.imshow(arr, aspect="auto", cmap="RdYlGn", vmin=0, vmax=1)
                ax2.set_xticks(range(len(labels)))
                ax2.set_xticklabels(labels, fontsize=8)
                ax2.set_yticks(range(len(all_keys)))
                # Show actual value range in label
                raw = np.array(data).T
                ylabels = []
                for ki, k in enumerate(all_keys):
                    lo, hi = raw[ki].min(), raw[ki].max()
                    ylabels.append(f"{k.replace('_', ' ')}\n[{lo:.3g}–{hi:.3g}]")
                ax2.set_yticklabels(ylabels, fontsize=7)
                cbar = plt.colorbar(im, ax=ax2, shrink=0.8)
                cbar.set_label("Normalized (0=min, 1=max)", fontsize=8)
            else:
                ax2.text(0.5, 0.5, "No param changes in kept experiments",
                         ha="center", va="center", transform=ax2.transAxes)
        else:
            ax2.text(0.5, 0.5, "No param changes in kept experiments",
                     ha="center", va="center", transform=ax2.transAxes)
    else:
        ax2.text(0.5, 0.5, "No experiments kept (baseline was best)",
                 ha="center", va="center", transform=ax2.transAxes)

    ax2.set_xlabel("Experiment Round", fontsize=11)

    plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
    print(f"Saved: {output_path}")


def main():
    default_log = os.path.join(os.path.dirname(__file__),
                               ".experiments", "experiments.jsonl")
    log_path = sys.argv[1] if len(sys.argv) > 1 else default_log
    output = sys.argv[2] if len(sys.argv) > 2 else log_path.replace(".jsonl", ".png")

    experiments = load_experiments(log_path)
    print(f"Loaded {len(experiments)} experiments")
    plot_experiments(experiments, output)


if __name__ == "__main__":
    main()
