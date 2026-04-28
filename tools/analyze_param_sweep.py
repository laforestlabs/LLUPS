#!/usr/bin/env python3
"""Analyze a two-stage random param sweep and propose new defaults + ranges.

For each parameter that was varied during the sweep, computes:
  - Pearson r between value and score (per stage)
  - Top-quintile median value (-> proposed default)
  - Top-quintile P10/P90 (-> proposed search range)
  - Sensitivity flag (insensitive if |r| < threshold in BOTH stages)

Produces:
  - <out_dir>/proposed_default_config.json   (overlay vs DEFAULT_CONFIG)
  - <out_dir>/proposed_param_ranges.json     (search-space bounds replacement)
  - <out_dir>/analysis.md                    (human-readable sensitivity table)
  - <out_dir>/raw_combined.jsonl             (per-round (params, score) joined)

Inputs (default layout written by run_overnight_param_sweep.py):
  <experiments_dir>/param_sweep/stage_a/round_NNNN/round_config.json
  <experiments_dir>/param_sweep/stage_a.jsonl
  <experiments_dir>/param_sweep/stage_b/round_NNNN/round_config.json
  <experiments_dir>/param_sweep/stage_b.jsonl

The JSONL is one autoexperiment round per line; we pull `round_num` and
`score` and join with the matching round_config.json.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
KICRAFT_PATH = REPO_ROOT / "KiCraft"
if str(KICRAFT_PATH) not in sys.path:
    sys.path.insert(0, str(KICRAFT_PATH))

from kicraft.autoplacer.config import (  # noqa: E402
    CONFIG_SEARCH_SPACE,
    DEFAULT_CONFIG,
)


SENSITIVITY_THRESHOLD = 0.10  # |r| below this is considered noise
TOP_QUINTILE_FRAC = 0.20


def _pearson_r(xs: list[float], ys: list[float]) -> float:
    n = min(len(xs), len(ys))
    if n < 3:
        return 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x == 0.0 or den_y == 0.0:
        return 0.0
    return num / (den_x * den_y)


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = pct * (len(sorted_values) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_values[lo]
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def _stage_a_score(payload: dict[str, Any], total_leaves_hint: int) -> float | None:
    """Stage A is --leaves-only, so the JSONL `score` is always 20.0
    (not_routed tier). Use leaf_score_summary instead, scaled to penalise
    partial solves: score = avg_score * (leaf_count / total_leaves)."""
    summary = payload.get("leaf_score_summary") or {}
    if not isinstance(summary, dict):
        return None
    try:
        avg = float(summary.get("avg_score", 0.0) or 0.0)
        count = int(summary.get("leaf_count", 0) or 0)
    except (TypeError, ValueError):
        return None
    if count <= 0:
        return 0.0
    denom = max(total_leaves_hint, count)
    return avg * (count / denom)


def _stage_b_score(payload: dict[str, Any]) -> float | None:
    """Stage B score: composer_score_total via JSONL `score`."""
    score = payload.get("score")
    try:
        return float(score) if score is not None else None
    except (TypeError, ValueError):
        return None


def _detect_total_leaves(jsonl_path: Path) -> int:
    """Inspect the first round to count total scheduled leaves; fallback to 6."""
    if not jsonl_path.exists():
        return 6
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                payload = json.loads(line.strip())
            except json.JSONDecodeError:
                continue
            scheduled = (
                payload.get("leaf_timing_summary", {}) or {}
            ).get("scheduled_leafs", [])
            if isinstance(scheduled, list) and scheduled:
                return len(scheduled)
            leaf_names = payload.get("leaf_names", [])
            if isinstance(leaf_names, list) and leaf_names:
                return len(leaf_names)
    return 6


def _load_stage_rows(
    stage_dir: Path, jsonl_path: Path, stage: str
) -> list[dict[str, Any]]:
    """Join per-round configs with per-round scores for a single stage.

    `stage` controls which JSONL field becomes the row's score:
      - "A" -> leaf_score_summary.avg_score * coverage_fraction
      - "B" -> top-level composer score (JSONL `score`)
    """
    if not jsonl_path.exists():
        return []
    total_leaves = _detect_total_leaves(jsonl_path) if stage == "A" else 6
    score_by_round: dict[int, float] = {}
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            round_num = payload.get("round_num")
            if not isinstance(round_num, int):
                continue
            score_f = (
                _stage_a_score(payload, total_leaves)
                if stage == "A"
                else _stage_b_score(payload)
            )
            if score_f is None:
                continue
            score_by_round[round_num] = score_f

    rows: list[dict[str, Any]] = []
    if not stage_dir.is_dir():
        return rows
    for round_dir in sorted(stage_dir.iterdir()):
        if not round_dir.is_dir() or not round_dir.name.startswith("round_"):
            continue
        try:
            round_num = int(round_dir.name.split("_", 1)[1])
        except (IndexError, ValueError):
            continue
        cfg_path = round_dir / "round_config.json"
        if not cfg_path.exists():
            continue
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(cfg, dict):
            continue
        if round_num not in score_by_round:
            continue
        rows.append({
            "round_num": round_num,
            "score": score_by_round[round_num],
            "config": cfg,
        })
    return rows


def _per_param_stats(
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """For each param in CONFIG_SEARCH_SPACE, compute sensitivity stats."""
    out: dict[str, dict[str, Any]] = {}
    if not rows:
        return out
    scores = [r["score"] for r in rows]
    score_sorted = sorted(scores, reverse=True)
    n = len(rows)
    top_count = max(1, int(round(n * TOP_QUINTILE_FRAC)))
    score_threshold = score_sorted[top_count - 1] if score_sorted else 0.0

    for key in CONFIG_SEARCH_SPACE.keys():
        xs: list[float] = []
        ys: list[float] = []
        top_xs: list[float] = []
        for row in rows:
            val = row["config"].get(key)
            if val is None:
                continue
            try:
                xv = float(val)
            except (TypeError, ValueError):
                continue
            xs.append(xv)
            ys.append(row["score"])
            if row["score"] >= score_threshold:
                top_xs.append(xv)
        if len(xs) < 3:
            continue
        r = _pearson_r(xs, ys)
        unique_vals = len(set(round(v, 6) for v in xs))
        if unique_vals < 2:
            continue  # param wasn't varied this stage
        top_xs_sorted = sorted(top_xs)
        median = statistics.median(top_xs_sorted) if top_xs_sorted else 0.0
        p10 = _percentile(top_xs_sorted, 0.10)
        p90 = _percentile(top_xs_sorted, 0.90)
        out[key] = {
            "n": len(xs),
            "n_top": len(top_xs),
            "pearson_r": r,
            "abs_r": abs(r),
            "value_min": min(xs),
            "value_max": max(xs),
            "top_median": median,
            "top_p10": p10,
            "top_p90": p90,
            "score_min": min(ys),
            "score_max": max(ys),
            "score_mean": sum(ys) / len(ys),
        }
    return out


def _propose_changes(
    stats_a: dict[str, dict[str, Any]],
    stats_b: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, list[float]], list[dict[str, Any]]]:
    """Combine per-stage stats into proposed defaults + ranges + per-param report."""
    proposed_defaults: dict[str, Any] = {}
    proposed_ranges: dict[str, list[float]] = {}
    report_rows: list[dict[str, Any]] = []

    for key, spec in CONFIG_SEARCH_SPACE.items():
        a = stats_a.get(key)
        b = stats_b.get(key)
        current_default = DEFAULT_CONFIG.get(key)
        current_range = [float(spec["min"]), float(spec["max"])]

        # Choose the winning stage by max |r|.
        if a and b:
            winner = "A" if a["abs_r"] >= b["abs_r"] else "B"
        elif a:
            winner = "A"
        elif b:
            winner = "B"
        else:
            winner = None

        winner_stats = a if winner == "A" else (b if winner == "B" else None)

        # Decide proposed default + range.
        if winner_stats is None:
            new_default = current_default
            new_range = current_range
            classification = "no-data"
        elif winner_stats["abs_r"] < SENSITIVITY_THRESHOLD:
            new_default = current_default
            new_range = current_range
            classification = "insensitive"
        else:
            new_default = winner_stats["top_median"]
            p10 = winner_stats["top_p10"]
            p90 = winner_stats["top_p90"]
            if p10 > p90:
                p10, p90 = p90, p10
            # Don't propose a range narrower than 5% of the spec span -- with
            # ~50 top-quintile samples the P10/P90 can collapse on noise.
            spec_span = current_range[1] - current_range[0]
            min_span = 0.05 * spec_span
            if (p90 - p10) < min_span:
                pad = (min_span - (p90 - p10)) / 2.0
                p10 = max(current_range[0], p10 - pad)
                p90 = min(current_range[1], p90 + pad)
            new_range = [p10, p90]
            classification = "sensitive"

        # Round int params.
        if str(spec.get("type")) == "int":
            try:
                new_default = int(round(float(new_default)))
            except (TypeError, ValueError):
                pass
            new_range = [
                int(math.floor(float(new_range[0]))),
                int(math.ceil(float(new_range[1]))),
            ]
        else:
            try:
                new_default = round(float(new_default), 4)
            except (TypeError, ValueError):
                pass
            new_range = [round(float(new_range[0]), 4), round(float(new_range[1]), 4)]

        if new_default != current_default:
            proposed_defaults[key] = new_default
        if list(new_range) != list(current_range):
            proposed_ranges[key] = new_range

        report_rows.append({
            "param": key,
            "current_default": current_default,
            "current_range": current_range,
            "proposed_default": new_default,
            "proposed_range": new_range,
            "winner_stage": winner or "-",
            "classification": classification,
            "stage_a": a,
            "stage_b": b,
        })

    return proposed_defaults, proposed_ranges, report_rows


def _format_value(val: Any) -> str:
    if isinstance(val, float):
        return f"{val:.4g}"
    return str(val)


def _format_range(rng: list[float]) -> str:
    if not isinstance(rng, list) or len(rng) != 2:
        return str(rng)
    return f"[{_format_value(rng[0])}, {_format_value(rng[1])}]"


def _write_analysis_md(
    out_path: Path,
    report_rows: list[dict[str, Any]],
    rows_a: list[dict[str, Any]],
    rows_b: list[dict[str, Any]],
) -> None:
    lines: list[str] = []
    lines.append("# Parameter Sweep Analysis")
    lines.append("")
    lines.append(f"Stage A rounds analyzed: **{len(rows_a)}**")
    lines.append(f"Stage B rounds analyzed: **{len(rows_b)}**")
    if rows_a:
        scores_a = [r["score"] for r in rows_a]
        lines.append(
            f"Stage A score range: {min(scores_a):.2f} -- {max(scores_a):.2f} "
            f"(mean {sum(scores_a)/len(scores_a):.2f})"
        )
    if rows_b:
        scores_b = [r["score"] for r in rows_b]
        lines.append(
            f"Stage B score range: {min(scores_b):.2f} -- {max(scores_b):.2f} "
            f"(mean {sum(scores_b)/len(scores_b):.2f})"
        )
    lines.append("")
    lines.append("## Per-parameter recommendations")
    lines.append("")
    lines.append(
        "| param | curr default | proposed default | curr range | proposed range "
        "| stage | r_A | r_B | classification |"
    )
    lines.append(
        "|-------|--------------|------------------|------------|----------------"
        "|-------|-----|-----|----------------|"
    )

    rank_key = lambda row: max(  # noqa: E731
        (row["stage_a"]["abs_r"] if row["stage_a"] else 0.0),
        (row["stage_b"]["abs_r"] if row["stage_b"] else 0.0),
    )
    for row in sorted(report_rows, key=rank_key, reverse=True):
        ra = f"{row['stage_a']['pearson_r']:+.2f}" if row["stage_a"] else "n/a"
        rb = f"{row['stage_b']['pearson_r']:+.2f}" if row["stage_b"] else "n/a"
        lines.append(
            f"| `{row['param']}` "
            f"| {_format_value(row['current_default'])} "
            f"| {_format_value(row['proposed_default'])} "
            f"| {_format_range(row['current_range'])} "
            f"| {_format_range(row['proposed_range'])} "
            f"| {row['winner_stage']} "
            f"| {ra} "
            f"| {rb} "
            f"| {row['classification']} |"
        )
    lines.append("")
    lines.append("## How to apply")
    lines.append("")
    lines.append(
        "- `proposed_default_config.json` is an OVERLAY: merge into "
        "`KiCraft/kicraft/autoplacer/config.py::DEFAULT_CONFIG`."
    )
    lines.append(
        "- `proposed_param_ranges.json` replaces the corresponding `min`/`max` "
        "in `KiCraft/kicraft/autoplacer/config.py::CONFIG_SEARCH_SPACE`."
    )
    lines.append(
        "- Validate by running `autoexperiment --rounds 5` with the new defaults "
        "and verifying mean composer_score_total >= the sweep's best."
    )
    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--experiments-dir", default=".experiments",
        help="Path to .experiments dir (default: .experiments)",
    )
    parser.add_argument(
        "--out-dir", default=None,
        help="Output dir (default: <experiments-dir>/param_sweep)",
    )
    args = parser.parse_args(argv or sys.argv[1:])

    experiments_dir = Path(args.experiments_dir).resolve()
    sweep_dir = experiments_dir / "param_sweep"
    out_dir = Path(args.out_dir).resolve() if args.out_dir else sweep_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    rows_a = _load_stage_rows(
        sweep_dir / "stage_a", sweep_dir / "stage_a.jsonl", stage="A"
    )
    rows_b = _load_stage_rows(
        sweep_dir / "stage_b", sweep_dir / "stage_b.jsonl", stage="B"
    )

    if not rows_a and not rows_b:
        print(
            "error: no per-round configs/scores found under "
            f"{sweep_dir}",
            file=sys.stderr,
        )
        return 2

    stats_a = _per_param_stats(rows_a)
    stats_b = _per_param_stats(rows_b)

    proposed_defaults, proposed_ranges, report_rows = _propose_changes(
        stats_a, stats_b
    )

    (out_dir / "proposed_default_config.json").write_text(
        json.dumps(proposed_defaults, indent=2, sort_keys=True), encoding="utf-8"
    )
    (out_dir / "proposed_param_ranges.json").write_text(
        json.dumps(proposed_ranges, indent=2, sort_keys=True), encoding="utf-8"
    )
    _write_analysis_md(out_dir / "analysis.md", report_rows, rows_a, rows_b)
    with (out_dir / "raw_combined.jsonl").open("w", encoding="utf-8") as f:
        for row in rows_a:
            f.write(json.dumps({"stage": "A", **row}) + "\n")
        for row in rows_b:
            f.write(json.dumps({"stage": "B", **row}) + "\n")

    sensitive = sum(1 for r in report_rows if r["classification"] == "sensitive")
    insensitive = sum(1 for r in report_rows if r["classification"] == "insensitive")
    nodata = sum(1 for r in report_rows if r["classification"] == "no-data")
    print(
        f"=== analyze_param_sweep: sensitive={sensitive}, "
        f"insensitive={insensitive}, no-data={nodata} ==="
    )
    print(f"  proposed_default_config.json : {len(proposed_defaults)} changes")
    print(f"  proposed_param_ranges.json   : {len(proposed_ranges)} changes")
    print(f"  analysis.md                  : {out_dir/'analysis.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
