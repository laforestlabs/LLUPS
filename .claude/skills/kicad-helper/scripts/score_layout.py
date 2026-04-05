#!/usr/bin/env python3
"""Score a KiCad PCB layout and record results for regression tracking."""
import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone

import pcbnew

from scoring import ALL_CHECKS

DEFAULT_CONFIG = {
    "power_nets": ["VBUS", "VBAT", "5V", "3V3", "3.3V", "+5V", "+3V3", "GND"],
    "power_trace_min_mm": 1.0,
    "signal_trace_min_mm": 0.2,
    "thermal_via_refs": ["U2", "U4"],
    "thermal_via_radius_mm": 3.0,
    "min_thermal_vias": 4,
    "target_utilization_range": [0.30, 0.70],
}


def load_config(path=None):
    config = dict(DEFAULT_CONFIG)
    if path:
        with open(path) as f:
            overrides = json.load(f)
        config.update(overrides)
    return config


def run_scoring(pcb_path, config):
    board = pcbnew.LoadBoard(pcb_path)
    results = {}
    total_weighted = 0
    total_weight = 0

    for check in ALL_CHECKS:
        result = check.run(board, config)
        w = config.get("weights", {}).get(check.name, check.weight)
        results[check.name] = {
            "display_name": check.display_name,
            "score": round(result.score, 1),
            "weight": w,
            "weighted_contribution": round(result.score * w, 2) if w > 0 else 0,
            "issue_count": {
                "error": sum(1 for i in result.issues if i.severity == "error"),
                "warning": sum(1 for i in result.issues if i.severity == "warning"),
                "info": sum(1 for i in result.issues if i.severity == "info"),
            },
            "issues": [asdict(i) for i in result.issues],
            "metrics": result.metrics,
            "summary": result.summary,
        }
        if w > 0:  # only scored checks contribute to overall
            total_weighted += result.score * w
            total_weight += w

    overall = round(total_weighted / total_weight, 1) if total_weight > 0 else 0

    # Strip internal config keys from output
    clean_config = {k: v for k, v in config.items() if not k.startswith("_")}

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pcb_file": os.path.basename(pcb_path),
        "overall_score": overall,
        "categories": results,
        "config_used": clean_config,
    }


def print_summary(report):
    print(f"\n{'=' * 60}")
    print(f"  PCB Layout Score: {report['overall_score']:.1f} / 100")
    print(f"  File: {report['pcb_file']}")
    print(f"  Time: {report['timestamp']}")
    print(f"{'=' * 60}\n")

    for name, cat in report["categories"].items():
        if cat["weight"] == 0:
            # Advisory check (e.g. visual) — no score bar
            print(f"  {cat['display_name']:<25} [advisory — not scored]")
            if cat["summary"]:
                print(f"    {cat['summary']}")
            render_paths = cat.get("metrics", {}).get("render_paths", {})
            for view, path in render_paths.items():
                print(f"    {view}: {path}")
            continue
        bar_len = int(cat["score"] / 2)
        bar = "#" * bar_len + "." * (50 - bar_len)
        ic = cat["issue_count"]
        issues_str = f"E:{ic['error']} W:{ic['warning']} I:{ic['info']}"
        print(f"  {cat['display_name']:<25} [{bar}] {cat['score']:5.1f}  {issues_str}")
        if cat["summary"]:
            print(f"    {cat['summary']}")
    print()


def print_comparison(current, previous):
    print(f"\n{'- ' * 30}")
    print(f"  Comparison with {previous['timestamp'][:19]}")
    print(f"{'- ' * 30}")

    delta_overall = current["overall_score"] - previous["overall_score"]
    arrow = "+" if delta_overall > 0 else ""
    print(f"  Overall: {previous['overall_score']:.1f} -> {current['overall_score']:.1f} ({arrow}{delta_overall:.1f})\n")

    for name in current["categories"]:
        cur = current["categories"][name]["score"]
        prev = previous["categories"].get(name, {}).get("score", 0)
        delta = cur - prev
        if delta != 0:
            arrow = "+" if delta > 0 else ""
            print(f"  {current['categories'][name]['display_name']:<25} {prev:.1f} -> {cur:.1f} ({arrow}{delta:.1f})")

    print()


def main():
    parser = argparse.ArgumentParser(description="Score a KiCad PCB layout")
    parser.add_argument("pcb", help="Path to .kicad_pcb file")
    parser.add_argument("--config", help="Path to JSON config file")
    parser.add_argument("--output-dir", default=None, help="Directory for JSON results (default: scripts/results/)")
    parser.add_argument("--compare", help="Path to previous result JSON for comparison")
    parser.add_argument("--no-save", action="store_true", help="Don't save JSON result")
    parser.add_argument("--no-render", action="store_true", help="Skip visual rendering")
    args = parser.parse_args()

    config = load_config(args.config)

    # Pass PCB path and render dir for visual check
    out_dir = args.output_dir or os.path.join(os.path.dirname(__file__), "results")
    config["_pcb_path"] = os.path.abspath(args.pcb) if not args.no_render else ""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    config["_render_dir"] = os.path.join(out_dir, f"renders_{ts}") if not args.no_render else ""

    report = run_scoring(args.pcb, config)
    print_summary(report)

    # Save results
    if not args.no_save:
        out_dir = args.output_dir or os.path.join(os.path.dirname(__file__), "results")
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(out_dir, f"score_{ts}.json")
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"  Results saved to: {out_path}\n")

    # Comparison
    if args.compare:
        with open(args.compare) as f:
            previous = json.load(f)
        print_comparison(report, previous)


if __name__ == "__main__":
    main()
