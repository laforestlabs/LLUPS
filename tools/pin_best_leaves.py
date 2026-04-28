#!/usr/bin/env python3
"""Pin the highest-scoring snapshot for every leaf in .experiments/subcircuits/.

Used by the overnight parameter sweep between Stage A (--leaves-only random
search) and Stage B (--parents-only random search).

For each leaf artifact dir, scans round_NNNN_solved_layout.json files,
picks the round with the highest "score" field, and calls pins.pin_leaf()
to copy that round's snapshots over the canonical files. Writes a small
summary to stdout and a JSON report to .experiments/param_sweep/pin_summary.json.

Usage:
    python tools/pin_best_leaves.py [--experiments-dir .experiments] \\
        [--report .experiments/param_sweep/pin_summary.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kicraft.autoplacer.brain.pins import pin_leaf, list_available_rounds


def _load_round_score(snapshot_path: Path) -> float | None:
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    score = payload.get("score")
    if isinstance(score, (int, float)):
        return float(score)
    for note in payload.get("notes", []) or []:
        if isinstance(note, str) and note.startswith("score="):
            try:
                return float(note.split("=", 1)[1])
            except ValueError:
                continue
    return None


def _pick_best_round(leaf_dir: Path, rounds: list[int]) -> tuple[int | None, float | None]:
    best_round: int | None = None
    best_score: float | None = None
    for round_num in rounds:
        snap = leaf_dir / f"round_{round_num:04d}_solved_layout.json"
        score = _load_round_score(snap)
        if score is None:
            continue
        if best_score is None or score > best_score:
            best_score = score
            best_round = round_num
    return best_round, best_score


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--experiments-dir",
        default=".experiments",
        help="Path to .experiments dir (default: .experiments)",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="Write JSON summary to this path (default: <experiments-dir>/param_sweep/pin_summary.json)",
    )
    args = parser.parse_args(argv or sys.argv[1:])

    experiments_dir = Path(args.experiments_dir).resolve()
    if not experiments_dir.is_dir():
        print(f"error: experiments dir not found: {experiments_dir}", file=sys.stderr)
        return 2

    sub_root = experiments_dir / "subcircuits"
    if not sub_root.is_dir():
        print(f"error: no subcircuits/ under {experiments_dir}", file=sys.stderr)
        return 2

    summary: dict[str, dict[str, object]] = {}
    pinned_count = 0
    skipped_count = 0
    failed_count = 0

    for leaf_dir in sorted(sub_root.iterdir()):
        if not leaf_dir.is_dir():
            continue
        if leaf_dir.name.startswith("subcircuit__"):
            continue
        leaf_key = leaf_dir.name
        rounds = list_available_rounds(experiments_dir, leaf_key)
        if not rounds:
            summary[leaf_key] = {
                "status": "no-snapshots",
                "round": None,
                "score": None,
                "sheet_name": _read_sheet_name(leaf_dir),
            }
            skipped_count += 1
            continue
        best_round, best_score = _pick_best_round(leaf_dir, rounds)
        sheet_name = _read_sheet_name(leaf_dir)
        if best_round is None:
            summary[leaf_key] = {
                "status": "no-scores",
                "round": None,
                "score": None,
                "sheet_name": sheet_name,
            }
            failed_count += 1
            continue
        try:
            pin_leaf(experiments_dir, leaf_key, best_round, source="overnight_param_sweep")
        except FileNotFoundError as exc:
            summary[leaf_key] = {
                "status": "pin-failed",
                "round": best_round,
                "score": best_score,
                "sheet_name": sheet_name,
                "error": str(exc),
            }
            failed_count += 1
            continue
        summary[leaf_key] = {
            "status": "pinned",
            "round": best_round,
            "score": best_score,
            "sheet_name": sheet_name,
            "candidate_rounds": rounds,
        }
        pinned_count += 1

    print(f"=== pin_best_leaves: pinned {pinned_count}, skipped {skipped_count}, failed {failed_count} ===")
    for leaf_key, row in summary.items():
        sheet = row.get("sheet_name", "?") or "?"
        status = row.get("status", "?")
        rnd = row.get("round")
        sc = row.get("score")
        score_s = f"{sc:.2f}" if isinstance(sc, (int, float)) else "n/a"
        print(f"  {sheet:18s}  status={status:13s}  round={rnd}  score={score_s}")

    report_path = Path(args.report) if args.report else (experiments_dir / "param_sweep" / "pin_summary.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(f"  report: {report_path}")

    return 0 if failed_count == 0 else 1


def _read_sheet_name(leaf_dir: Path) -> str:
    metadata_path = leaf_dir / "metadata.json"
    if not metadata_path.exists():
        return ""
    try:
        return str(json.loads(metadata_path.read_text(encoding="utf-8")).get("sheet_name", ""))
    except Exception:
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
