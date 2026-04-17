#!/usr/bin/env python3
"""Hierarchical autoexperiment orchestrator for the subcircuit pipeline.

This replaces the legacy whole-board mutate/place/route experiment loop with a
clean bottom-up hierarchical runner.

Design goals:
- no legacy whole-board routing path
- no fallback to the old flat pipeline
- drive only the subcircuit leaf-first flow
- emit machine-readable progress for the Experiment Manager GUI
- preserve visual artifacts for both leaf and top-level progression
- keep the CLI simple and stable

High-level flow per round:
1. solve routed leaf subcircuits with `solve_subcircuits.py`
2. inspect accepted leaf artifacts under `.experiments/subcircuits/`
3. compose a parent/top-level snapshot with `compose_subcircuits.py`
4. optionally run the visible hierarchical pipeline runner
5. score the round from accepted artifact quality and hierarchy coverage
6. keep the best round and publish live status / JSONL events / frame metadata

This file intentionally does not import or use the old `FullPipeline`
whole-board experiment machinery.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parents[4]

DEFAULT_SCHEMATIC = PROJECT_DIR / "LLUPS.kicad_sch"
DEFAULT_PCB = PROJECT_DIR / "LLUPS.kicad_pcb"


@dataclass
class HierarchyRound:
    round_num: int
    seed: int
    mode: str
    score: float
    kept: bool
    duration_s: float
    leaf_total: int = 0
    leaf_accepted: int = 0
    parent_composed: bool = False
    top_level_ready: bool = False
    accepted_trace_count: int = 0
    accepted_via_count: int = 0
    latest_stage: str = ""
    details: str = ""
    artifact_root: str = ""
    composition_json: str = ""
    visible_output_dir: str = ""
    leaf_names: list[str] = field(default_factory=list)
    accepted_leaf_names: list[str] = field(default_factory=list)
    score_breakdown: dict[str, float] = field(default_factory=dict)
    score_notes: list[str] = field(default_factory=list)
    absolute_score: float = 0.0
    improvement_score: float = 0.0
    plateau_escape_score: float = 0.0
    parent_quality_score: float = 0.0
    baseline_score: float = 0.0
    rolling_score: float = 0.0
    improvement_vs_best: float = 0.0
    improvement_vs_baseline: float = 0.0
    improvement_vs_recent: float = 0.0
    plateau_count: int = 0

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=False)


def _check_stop_request(work_dir: Path) -> bool:
    return (work_dir / "stop.now").exists()


def _request_stop(work_dir: Path) -> None:
    (work_dir / "stop.now").touch()


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def _format_mmss(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}m{seconds % 60:02d}s"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


def _run_command(
    cmd: list[str],
    *,
    cwd: Path,
    timeout_s: int | None = None,
) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout_s,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _discover_artifact_dirs(project_dir: Path) -> list[Path]:
    root = project_dir / ".experiments" / "subcircuits"
    if not root.exists():
        return []
    result: list[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if (child / "metadata.json").exists() and (
            child / "solved_layout.json"
        ).exists():
            result.append(child)
    return result


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _accepted_leaf_artifacts(project_dir: Path) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    for artifact_dir in _discover_artifact_dirs(project_dir):
        solved_layout_path = artifact_dir / "solved_layout.json"
        metadata_path = artifact_dir / "metadata.json"
        try:
            solved_layout = _load_json(solved_layout_path)
            metadata = _load_json(metadata_path)
        except Exception:
            continue

        validation = solved_layout.get("validation", {})
        if validation.get("accepted") is True:
            accepted.append(
                {
                    "artifact_dir": str(artifact_dir),
                    "sheet_name": solved_layout.get(
                        "sheet_name", metadata.get("sheet_name", "")
                    ),
                    "instance_path": solved_layout.get("instance_path", ""),
                    "trace_count": len(solved_layout.get("traces", [])),
                    "via_count": len(solved_layout.get("vias", [])),
                    "validation": validation,
                    "metadata": metadata,
                    "solved_layout": solved_layout,
                }
            )
    return accepted


def _all_leaf_artifacts(project_dir: Path) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for artifact_dir in _discover_artifact_dirs(project_dir):
        solved_layout_path = artifact_dir / "solved_layout.json"
        metadata_path = artifact_dir / "metadata.json"
        try:
            solved_layout = _load_json(solved_layout_path)
            metadata = _load_json(metadata_path)
        except Exception:
            continue
        artifacts.append(
            {
                "artifact_dir": str(artifact_dir),
                "sheet_name": solved_layout.get(
                    "sheet_name", metadata.get("sheet_name", "")
                ),
                "instance_path": solved_layout.get("instance_path", ""),
                "trace_count": len(solved_layout.get("traces", [])),
                "via_count": len(solved_layout.get("vias", [])),
                "validation": solved_layout.get("validation", {}),
                "metadata": metadata,
                "solved_layout": solved_layout,
            }
        )
    return artifacts


def _score_round(
    *,
    accepted_leafs: list[dict[str, Any]],
    all_leafs: list[dict[str, Any]],
    composition_ok: bool,
    visible_ok: bool,
    parent_copper_accounting: dict[str, int] | None,
    baseline_score: float | None,
    recent_scores: list[float],
    plateau_count: int,
) -> tuple[float, dict[str, float], list[str], dict[str, float]]:
    leaf_total = len(all_leafs)
    leaf_accepted = len(accepted_leafs)
    acceptance_ratio = (leaf_accepted / leaf_total) if leaf_total > 0 else 0.0

    accepted_trace_count = sum(item.get("trace_count", 0) for item in accepted_leafs)
    accepted_via_count = sum(item.get("via_count", 0) for item in accepted_leafs)

    all_trace_count = sum(item.get("trace_count", 0) for item in all_leafs)
    all_via_count = sum(item.get("via_count", 0) for item in all_leafs)

    trace_coverage_ratio = (
        accepted_trace_count / all_trace_count if all_trace_count > 0 else 0.0
    )
    via_coverage_ratio = (
        accepted_via_count / all_via_count if all_via_count > 0 else 0.0
    )

    copper = dict(parent_copper_accounting or {})
    expected_child_traces = int(
        copper.get("expected_preserved_child_trace_count", 0) or 0
    )
    expected_child_vias = int(copper.get("expected_preserved_child_via_count", 0) or 0)
    preserved_child_traces = int(copper.get("preserved_child_trace_count", 0) or 0)
    preserved_child_vias = int(copper.get("preserved_child_via_count", 0) or 0)
    routed_total_traces = int(copper.get("routed_total_trace_count", 0) or 0)
    routed_total_vias = int(copper.get("routed_total_via_count", 0) or 0)
    added_parent_traces = int(copper.get("added_parent_trace_count", 0) or 0)
    added_parent_vias = int(copper.get("added_parent_via_count", 0) or 0)

    preserved_trace_ratio = (
        preserved_child_traces / expected_child_traces
        if expected_child_traces > 0
        else 0.0
    )
    preserved_via_ratio = (
        preserved_child_vias / expected_child_vias if expected_child_vias > 0 else 0.0
    )
    parent_added_copper_present = (
        1.0 if (added_parent_traces + added_parent_vias) > 0 else 0.0
    )
    parent_routed_copper_ratio = (routed_total_traces + routed_total_vias) / max(
        1,
        expected_child_traces
        + expected_child_vias
        + added_parent_traces
        + added_parent_vias,
    )

    leaf_acceptance_score = acceptance_ratio * 34.0
    routed_copper_score = min(
        16.0,
        trace_coverage_ratio * 12.0 + via_coverage_ratio * 4.0,
    )
    parent_composition_score = 8.0 if composition_ok else 0.0
    top_level_score = 8.0 if visible_ok else 0.0

    parent_quality_score = min(
        14.0,
        preserved_trace_ratio * 7.0
        + preserved_via_ratio * 3.0
        + parent_added_copper_present * 2.0
        + min(1.0, parent_routed_copper_ratio) * 2.0,
    )

    absolute_score = round(
        leaf_acceptance_score
        + routed_copper_score
        + parent_composition_score
        + top_level_score
        + parent_quality_score,
        3,
    )

    effective_baseline = absolute_score if baseline_score is None else baseline_score
    rolling_reference = (
        sum(recent_scores) / len(recent_scores) if recent_scores else effective_baseline
    )

    improvement_vs_baseline = absolute_score - effective_baseline
    improvement_vs_recent = absolute_score - rolling_reference

    baseline_improvement_score = max(0.0, min(10.0, improvement_vs_baseline * 0.6))
    recent_improvement_score = max(0.0, min(4.0, improvement_vs_recent * 1.0))

    plateau_escape_trigger = max(2, plateau_count)
    plateau_escape_score = 0.0
    if plateau_count >= plateau_escape_trigger and improvement_vs_recent > 0.5:
        plateau_escape_score = min(4.0, 1.0 + improvement_vs_recent * 0.75)

    improvement_score = round(
        baseline_improvement_score + recent_improvement_score,
        3,
    )
    plateau_escape_score = round(plateau_escape_score, 3)

    score_breakdown = {
        "absolute_leaf_acceptance": round(leaf_acceptance_score, 3),
        "absolute_routed_copper": round(routed_copper_score, 3),
        "absolute_parent_composition": round(parent_composition_score, 3),
        "absolute_top_level_ready": round(top_level_score, 3),
        "absolute_parent_quality": round(parent_quality_score, 3),
        "improvement_vs_baseline": round(baseline_improvement_score, 3),
        "improvement_vs_recent": round(recent_improvement_score, 3),
        "plateau_escape": plateau_escape_score,
    }
    score = round(
        absolute_score + improvement_score + plateau_escape_score,
        3,
    )

    score_notes = [
        f"leaf_acceptance_ratio={acceptance_ratio:.3f}",
        f"trace_coverage_ratio={trace_coverage_ratio:.3f}",
        f"via_coverage_ratio={via_coverage_ratio:.3f}",
        f"accepted_leafs={leaf_accepted}/{leaf_total}",
        f"accepted_traces={accepted_trace_count}/{all_trace_count}",
        f"accepted_vias={accepted_via_count}/{all_via_count}",
        f"composition_ok={composition_ok}",
        f"top_level_ready={visible_ok}",
        f"preserved_child_trace_ratio={preserved_trace_ratio:.3f}",
        f"preserved_child_via_ratio={preserved_via_ratio:.3f}",
        f"parent_added_copper_present={parent_added_copper_present:.3f}",
        f"parent_routed_copper_ratio={parent_routed_copper_ratio:.3f}",
        f"baseline_score={effective_baseline:.3f}",
        f"rolling_score={rolling_reference:.3f}",
        f"improvement_vs_baseline={improvement_vs_baseline:.3f}",
        f"improvement_vs_recent={improvement_vs_recent:.3f}",
        f"plateau_count_in={plateau_count}",
        "score_architecture=absolute_plus_improvement_plus_plateau_escape",
        "score_scale=bounded_components_with_relative_rewards",
        "board_size_reduction_plan=after_best_layout_run_iterative_outline_shrink_loop_at_leaf_and_parent_levels",
        "board_size_reduction_loop=shrink_outline_then_revalidate_route_then_accept_smallest_passing_size",
    ]
    score_context = {
        "absolute_score": absolute_score,
        "improvement_score": improvement_score,
        "plateau_escape_score": plateau_escape_score,
        "parent_quality_score": round(parent_quality_score, 3),
        "baseline_score": round(effective_baseline, 3),
        "rolling_score": round(rolling_reference, 3),
        "improvement_vs_baseline": round(improvement_vs_baseline, 3),
        "improvement_vs_recent": round(improvement_vs_recent, 3),
    }
    return score, score_breakdown, score_notes, score_context


def _extract_parent_copper_accounting(project_dir: Path) -> dict[str, int]:
    def _normalize_copper_accounting(payload: dict[str, Any]) -> dict[str, int]:
        return {
            "expected_preserved_child_trace_count": int(
                payload.get("expected_preserved_child_trace_count", 0) or 0
            ),
            "expected_preserved_child_via_count": int(
                payload.get("expected_preserved_child_via_count", 0) or 0
            ),
            "preserved_child_trace_count": int(
                payload.get("preserved_child_trace_count", 0) or 0
            ),
            "preserved_child_via_count": int(
                payload.get("preserved_child_via_count", 0) or 0
            ),
            "routed_total_trace_count": int(
                payload.get("routed_total_trace_count", 0) or 0
            ),
            "routed_total_via_count": int(
                payload.get("routed_total_via_count", 0) or 0
            ),
            "added_parent_trace_count": int(
                payload.get("added_parent_trace_count", 0) or 0
            ),
            "added_parent_via_count": int(
                payload.get("added_parent_via_count", 0) or 0
            ),
        }

    candidate_paths = [
        project_dir
        / ".experiments"
        / "subcircuits"
        / "subcircuit__8a5edab282"
        / "debug.json",
        project_dir
        / ".experiments"
        / "subcircuits"
        / "subcircuit__8a5edab282"
        / "metadata.json",
        project_dir / ".experiments" / "hierarchical_pipeline" / "parent_pipeline.json",
    ]

    for candidate in candidate_paths:
        try:
            payload = _load_json(candidate)
        except Exception:
            continue

        if candidate.name == "debug.json":
            routing_result = payload.get("routing_result", {})
            if isinstance(routing_result, dict):
                copper = routing_result.get("copper_accounting", {})
                if isinstance(copper, dict) and any(
                    int(copper.get(k, 0) or 0) for k in copper
                ):
                    return _normalize_copper_accounting(copper)

        elif candidate.name == "metadata.json":
            normalized = _normalize_copper_accounting(payload)
            if any(normalized.values()):
                return normalized

        elif candidate.name == "parent_pipeline.json":
            state = payload.get("state", {})
            if isinstance(state, dict):
                normalized = _normalize_copper_accounting(state)
                if any(normalized.values()):
                    return normalized

    return {}


def _write_live_status(
    status_json_path: Path,
    status_txt_path: Path,
    *,
    phase: str,
    rounds_total: int,
    round_num: int,
    best_score: float,
    kept_count: int,
    latest_score: float | None,
    latest_marker: str | None,
    start_ts: float,
    current_stage: str,
    leaf_total: int,
    leaf_accepted: int,
    top_level_ready: bool,
    leaf_worker_count: int = 1,
    leaf_workers_active: int = 0,
    leaf_workers_queued: int = 0,
    leaf_workers_completed: int | None = None,
    current_node: str | None = None,
    current_leaf: str | None = None,
    current_parent: str | None = None,
    top_level_status: str | None = None,
    composition_status: str | None = None,
    copper_accounting: dict[str, int] | None = None,
) -> None:
    now = time.monotonic()
    elapsed_s = now - start_ts
    normalized_leaf_worker_count = max(1, leaf_worker_count)
    normalized_leaf_workers_active = max(
        0, min(normalized_leaf_worker_count, int(leaf_workers_active or 0))
    )
    normalized_leaf_workers_queued = max(0, int(leaf_workers_queued or 0))
    normalized_leaf_workers_completed = max(
        0,
        int(
            leaf_accepted if leaf_workers_completed is None else leaf_workers_completed
        ),
    )
    progress_pct = (round_num / rounds_total * 100.0) if rounds_total > 0 else 100.0
    copper = dict(copper_accounting or {})
    hierarchy_top_level_status = (
        top_level_status
        if top_level_status is not None
        else ("ready" if top_level_ready else "not_ready")
    )
    hierarchy_composition_status = (
        composition_status if composition_status is not None else current_stage
    )

    payload = {
        "phase": phase,
        "pipeline": "hierarchical_subcircuits",
        "round": round_num,
        "total_rounds": rounds_total,
        "progress_percent": round(progress_pct, 2),
        "best_score": round(best_score, 3),
        "latest_score": None if latest_score is None else round(latest_score, 3),
        "latest_marker": latest_marker,
        "kept_count": kept_count,
        "elapsed_s": round(elapsed_s, 1),
        "eta_s": 0.0,
        "current_node": current_node,
        "current_leaf": current_leaf,
        "current_parent": current_parent,
        "top_level_status": hierarchy_top_level_status,
        "composition_status": hierarchy_composition_status,
        "workers": {
            "total": 1,
            "in_flight": 0 if phase != "running" else 1,
            "idle": 0 if phase == "running" else 1,
            "leaf_workers": normalized_leaf_worker_count,
        },
        "maybe_stuck": False,
        "hierarchy": {
            "current_stage": current_stage,
            "leaf_total": leaf_total,
            "leaf_accepted": leaf_accepted,
            "top_level_ready": top_level_ready,
            "leaf_parallelism_enabled": normalized_leaf_worker_count > 1,
            "leaf_worker_count": normalized_leaf_worker_count,
            "leaf_workers": {
                "total": normalized_leaf_worker_count,
                "active": normalized_leaf_workers_active,
                "idle": max(
                    0, normalized_leaf_worker_count - normalized_leaf_workers_active
                ),
                "queued": normalized_leaf_workers_queued,
                "completed": normalized_leaf_workers_completed,
            },
            "current_node": current_node,
            "current_leaf": current_leaf,
            "current_parent": current_parent,
            "top_level_status": hierarchy_top_level_status,
            "composition_status": hierarchy_composition_status,
            "copper_accounting": copper,
        },
        "timestamp_epoch_s": time.time(),
    }
    _write_json(status_json_path, payload)

    lines = [
        "=== Hierarchical Autoexperiment Live Status ===",
        f"phase: {phase}",
        "pipeline: hierarchical_subcircuits",
        f"progress: {round_num}/{rounds_total} ({progress_pct:.1f}%)",
        f"best_score: {best_score:.2f}",
        f"latest_score: {'n/a' if latest_score is None else f'{latest_score:.2f}'}",
        f"latest_event: {latest_marker or 'n/a'}",
        f"kept_count: {kept_count}",
        f"elapsed: {_format_mmss(elapsed_s)}",
        f"current_stage: {current_stage}",
        f"current_node: {current_node or 'n/a'}",
        f"current_leaf: {current_leaf or 'n/a'}",
        f"current_parent: {current_parent or 'n/a'}",
        f"leafs: accepted={leaf_accepted} total={leaf_total}",
        (
            "leaf_workers: "
            f"active={normalized_leaf_workers_active}/"
            f"{normalized_leaf_worker_count} "
            f"queued={normalized_leaf_workers_queued} "
            f"completed={normalized_leaf_workers_completed}"
        ),
        f"composition_status: {hierarchy_composition_status}",
        f"top_level_status: {hierarchy_top_level_status}",
        f"top_level_ready: {top_level_ready}",
    ]
    if copper:
        lines.extend(
            [
                "copper_accounting:",
                (
                    "  preserved_child_traces: "
                    f"{copper.get('preserved_child_trace_count', 0)}/"
                    f"{copper.get('expected_preserved_child_trace_count', 0)}"
                ),
                (
                    "  preserved_child_vias: "
                    f"{copper.get('preserved_child_via_count', 0)}/"
                    f"{copper.get('expected_preserved_child_via_count', 0)}"
                ),
                (f"  routed_total_traces: {copper.get('routed_total_trace_count', 0)}"),
                (f"  routed_total_vias: {copper.get('routed_total_via_count', 0)}"),
                (f"  added_parent_traces: {copper.get('added_parent_trace_count', 0)}"),
                (f"  added_parent_vias: {copper.get('added_parent_via_count', 0)}"),
            ]
        )
    status_txt_path.parent.mkdir(parents=True, exist_ok=True)
    with open(status_txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _write_round_detail(
    rounds_dir: Path,
    round_result: HierarchyRound,
    *,
    accepted_leafs: list[dict[str, Any]],
    all_leafs: list[dict[str, Any]],
    solve_exit_code: int,
    compose_exit_code: int,
    visible_exit_code: int | None,
    solve_stdout: str,
    solve_stderr: str,
    compose_stdout: str,
    compose_stderr: str,
    visible_stdout: str,
    visible_stderr: str,
    parent_copper_accounting: dict[str, int] | None = None,
) -> None:
    payload = {
        "round": round_result.round_num,
        "round_num": round_result.round_num,
        "seed": round_result.seed,
        "mode": round_result.mode,
        "score": round_result.score,
        "kept": round_result.kept,
        "duration_s": round_result.duration_s,
        "latest_stage": round_result.latest_stage,
        "hierarchy": {
            "leaf_total": round_result.leaf_total,
            "leaf_accepted": round_result.leaf_accepted,
            "parent_composed": round_result.parent_composed,
            "top_level_ready": round_result.top_level_ready,
            "accepted_trace_count": round_result.accepted_trace_count,
            "accepted_via_count": round_result.accepted_via_count,
            "leaf_names": round_result.leaf_names,
            "accepted_leaf_names": round_result.accepted_leaf_names,
            "score_breakdown": dict(round_result.score_breakdown),
            "score_notes": list(round_result.score_notes),
            "absolute_score": round_result.absolute_score,
            "improvement_score": round_result.improvement_score,
            "plateau_escape_score": round_result.plateau_escape_score,
            "parent_quality_score": round_result.parent_quality_score,
            "baseline_score": round_result.baseline_score,
            "rolling_score": round_result.rolling_score,
            "improvement_vs_best": round_result.improvement_vs_best,
            "improvement_vs_baseline": round_result.improvement_vs_baseline,
            "improvement_vs_recent": round_result.improvement_vs_recent,
            "plateau_count": round_result.plateau_count,
        },
        "artifacts": {
            "artifact_root": round_result.artifact_root,
            "composition_json": round_result.composition_json,
            "visible_output_dir": round_result.visible_output_dir,
            "parent_copper_accounting": dict(parent_copper_accounting or {}),
        },
        "commands": {
            "solve_exit_code": solve_exit_code,
            "compose_exit_code": compose_exit_code,
            "visible_exit_code": visible_exit_code,
        },
        "accepted_leaf_artifacts": accepted_leafs,
        "all_leaf_artifacts": all_leafs,
        "logs": {
            "solve_stdout_tail": solve_stdout[-12000:],
            "solve_stderr_tail": solve_stderr[-12000:],
            "compose_stdout_tail": compose_stdout[-12000:],
            "compose_stderr_tail": compose_stderr[-12000:],
            "visible_stdout_tail": visible_stdout[-12000:],
            "visible_stderr_tail": visible_stderr[-12000:],
        },
    }
    _write_json(rounds_dir / f"round_{round_result.round_num:04d}.json", payload)


def _write_frame_metadata(
    frames_dir: Path,
    round_result: HierarchyRound,
) -> None:
    payload = {
        "round_num": round_result.round_num,
        "kept": round_result.kept,
        "accepted": round_result.kept,
        "score": round_result.score,
        "mode": round_result.mode,
        "stage": round_result.latest_stage,
        "latest_stage": round_result.latest_stage,
        "leaf_total": round_result.leaf_total,
        "leaf_accepted": round_result.leaf_accepted,
        "top_level_ready": round_result.top_level_ready,
        "parent_composed": round_result.parent_composed,
        "accepted_trace_count": round_result.accepted_trace_count,
        "accepted_via_count": round_result.accepted_via_count,
        "score_breakdown": dict(round_result.score_breakdown),
        "score_notes": list(round_result.score_notes),
        "absolute_score": round_result.absolute_score,
        "improvement_score": round_result.improvement_score,
        "plateau_escape_score": round_result.plateau_escape_score,
        "parent_quality_score": round_result.parent_quality_score,
        "baseline_score": round_result.baseline_score,
        "rolling_score": round_result.rolling_score,
        "improvement_vs_best": round_result.improvement_vs_best,
        "improvement_vs_baseline": round_result.improvement_vs_baseline,
        "improvement_vs_recent": round_result.improvement_vs_recent,
        "plateau_count": round_result.plateau_count,
        "sheet_name": ", ".join(round_result.accepted_leaf_names[:3])
        if round_result.accepted_leaf_names
        else "",
        "instance_path": round_result.visible_output_dir
        or round_result.composition_json,
        "artifact_root": round_result.artifact_root,
        "composition_json": round_result.composition_json,
        "visible_output_dir": round_result.visible_output_dir,
        "details": round_result.details,
    }
    _write_json(frames_dir / f"frame_{round_result.round_num:04d}.json", payload)


def _select_preview_image(visible_output_dir: Path) -> Path | None:
    candidates = [
        visible_output_dir / "routed_png.png",
        visible_output_dir / "parent_routed.png",
        visible_output_dir / "routed.png",
        visible_output_dir / "preloaded_png.png",
        visible_output_dir / "parent_stamped.png",
        visible_output_dir / "board_routed.png",
        visible_output_dir / "board.png",
        visible_output_dir / "snapshot.png",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    pngs = sorted(
        visible_output_dir.glob("*.png"),
        key=lambda path: (
            0
            if "routed" in path.name.lower()
            else 1
            if "preloaded" in path.name.lower() or "stamped" in path.name.lower()
            else 2,
            path.name.lower(),
        ),
    )
    return pngs[0] if pngs else None


def _build_solve_cmd(
    *,
    schematic: Path,
    pcb: Path,
    rounds: int,
    seed: int,
    config: str | None,
    only: list[str],
    workers: int,
) -> list[str]:
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "solve_subcircuits.py"),
        str(schematic),
        "--pcb",
        str(pcb),
        "--rounds",
        str(max(1, rounds)),
        "--seed",
        str(seed),
        "--route",
        "--json",
        "--workers",
        str(max(1, workers)),
    ]
    if config:
        cmd.extend(["--config", config])
    for selector in only:
        cmd.extend(["--only", selector])
    return cmd


def _build_compose_cmd(
    *,
    project_dir: Path,
    parent: str,
    output_json: Path,
    only: list[str],
) -> list[str]:
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "compose_subcircuits.py"),
        "--project",
        str(project_dir),
        "--parent",
        parent,
        "--mode",
        "packed",
        "--spacing-mm",
        "6",
        "--output",
        str(output_json),
        "--json",
    ]
    for selector in only:
        cmd.extend(["--only", selector])
    return cmd


def _build_visible_cmd(
    *,
    project_dir: Path,
    schematic: Path,
    pcb: Path,
    parent: str,
    output_dir: Path,
    config: str | None,
    rounds: int,
    seed: int,
    only: list[str],
) -> list[str]:
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "run_hierarchical_pipeline.py"),
        "--project",
        str(project_dir),
        "--schematic",
        str(schematic),
        "--pcb",
        str(pcb),
        "--parent",
        parent,
        "--output-dir",
        str(output_dir),
        "--rounds",
        str(max(1, rounds)),
        "--seed",
        str(seed),
        "--render-png",
        "--json",
    ]
    if config:
        cmd.extend(["--config", config])
    for selector in only:
        cmd.extend(["--only", selector])
    return cmd


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Hierarchical subcircuit autoexperiment orchestrator"
    )
    parser.add_argument(
        "pcb",
        nargs="?",
        default=str(DEFAULT_PCB),
        help="Top-level PCB path (default: LLUPS.kicad_pcb)",
    )
    parser.add_argument(
        "--schematic",
        default=str(DEFAULT_SCHEMATIC),
        help="Top-level schematic path (default: LLUPS.kicad_sch)",
    )
    parser.add_argument(
        "--rounds",
        "-n",
        type=int,
        default=10,
        help="Number of hierarchical experiment rounds",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=1,
        help="Reserved for GUI compatibility; hierarchical mode currently runs single-worker",
    )
    parser.add_argument(
        "--plateau",
        type=int,
        default=2,
        help="Number of non-improving rounds tolerated before plateau markers become explicit",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Master RNG seed",
    )
    parser.add_argument(
        "--config",
        help="Optional project config path passed through to child commands",
    )
    parser.add_argument(
        "--parent",
        default="/",
        help="Parent selector for composition / visible top-level assembly",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Restrict to specific leaf selectors",
    )
    parser.add_argument(
        "--leaf-rounds",
        type=int,
        default=1,
        help="Leaf solve rounds per experiment round",
    )
    parser.add_argument(
        "--skip-visible",
        action="store_true",
        help="Skip the visible top-level pipeline stage",
    )
    parser.add_argument(
        "--status-file",
        default="run_status.json",
        help="Status JSON filename inside .experiments/",
    )
    parser.add_argument(
        "--log",
        default="experiments.jsonl",
        help="JSONL log filename inside .experiments/",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output best top-level artifact directory marker file",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    project_dir = Path(args.pcb).resolve().parent
    pcb = Path(args.pcb).resolve()
    schematic = Path(args.schematic).resolve()

    if not pcb.exists():
        print(f"error: pcb not found: {pcb}", file=sys.stderr)
        return 2
    if not schematic.exists():
        print(f"error: schematic not found: {schematic}", file=sys.stderr)
        return 2

    work_dir = project_dir / ".experiments"
    work_dir.mkdir(parents=True, exist_ok=True)
    rounds_dir = work_dir / "rounds"
    frames_dir = work_dir / "frames"
    best_dir = work_dir / "best"
    hierarchy_dir = work_dir / "hierarchical_autoexperiment"

    for path in (rounds_dir, frames_dir, best_dir, hierarchy_dir):
        path.mkdir(parents=True, exist_ok=True)

    log_path = work_dir / args.log
    status_json_path = work_dir / args.status_file
    status_txt_path = work_dir / "run_status.txt"

    _safe_unlink(log_path)
    _safe_unlink(status_json_path)
    _safe_unlink(status_txt_path)
    _safe_unlink(work_dir / "stop.now")

    def _sigterm_handler(signum: int, frame: Any) -> None:
        _request_stop(work_dir)

    signal.signal(signal.SIGTERM, _sigterm_handler)

    master_seed = args.seed if args.seed is not None else random.randint(0, 2**31 - 1)
    rng = random.Random(master_seed)

    print("=== Hierarchical Autoexperiment Complete ===")
    print(f"Project:      {project_dir}")
    print(f"Schematic:    {schematic}")
    print(f"PCB:          {pcb}")
    print(f"Rounds:       {args.rounds}")
    print(f"Leaf rounds:  {args.leaf_rounds}")
    print(f"Parent:       {args.parent}")
    print(f"Master seed:  {master_seed}")
    print("Mode:         subcircuit leaf bottom-up only")
    print()

    start_ts = time.monotonic()
    best_score = -1.0
    kept_count = 0
    plateau_count = 0
    baseline_score: float | None = None
    recent_scores: list[float] = []
    best_round: HierarchyRound | None = None

    _write_live_status(
        status_json_path,
        status_txt_path,
        phase="running",
        rounds_total=args.rounds,
        round_num=0,
        best_score=0.0,
        kept_count=0,
        latest_score=None,
        latest_marker="starting hierarchical run",
        start_ts=start_ts,
        current_stage="startup",
        leaf_total=0,
        leaf_accepted=0,
        top_level_ready=False,
        leaf_worker_count=max(1, args.workers),
        leaf_workers_active=0,
        leaf_workers_queued=0,
        leaf_workers_completed=0,
        current_node=args.parent,
        current_parent=args.parent,
        top_level_status="pending",
        composition_status="startup",
        copper_accounting={},
    )

    for round_num in range(1, args.rounds + 1):
        if _check_stop_request(work_dir):
            break

        round_seed = rng.randint(0, 2**31 - 1)
        round_dir = hierarchy_dir / f"round_{round_num:04d}"
        parent_output_json = round_dir / "parent_pipeline.json"
        composition_json = round_dir / "parent_composition.json"
        round_dir.mkdir(parents=True, exist_ok=True)

        _write_live_status(
            status_json_path,
            status_txt_path,
            phase="running",
            rounds_total=args.rounds,
            round_num=round_num,
            best_score=max(best_score, 0.0),
            kept_count=kept_count,
            latest_score=None,
            latest_marker=f"round {round_num} started",
            start_ts=start_ts,
            current_stage="solve_leafs",
            leaf_total=0,
            leaf_accepted=0,
            top_level_ready=False,
            leaf_worker_count=max(1, args.workers),
            leaf_workers_active=max(1, min(args.workers, 1)),
            leaf_workers_queued=0,
            leaf_workers_completed=0,
            current_node=args.parent,
            current_parent=args.parent,
            top_level_status="pending",
            composition_status="solving_leafs",
            copper_accounting={},
        )

        t0 = time.monotonic()

        solve_cmd = _build_solve_cmd(
            schematic=schematic,
            pcb=pcb,
            rounds=args.leaf_rounds,
            seed=round_seed,
            config=args.config,
            only=args.only,
            workers=max(1, args.workers),
        )
        solve_rc, solve_stdout, solve_stderr = _run_command(
            solve_cmd,
            cwd=project_dir,
            timeout_s=None,
        )

        all_leafs = _all_leaf_artifacts(project_dir)
        accepted_leafs = _accepted_leaf_artifacts(project_dir)

        leaf_names = [item.get("sheet_name", "") for item in all_leafs]
        accepted_leaf_names = [item.get("sheet_name", "") for item in accepted_leafs]

        _write_live_status(
            status_json_path,
            status_txt_path,
            phase="running",
            rounds_total=args.rounds,
            round_num=round_num,
            best_score=max(best_score, 0.0),
            kept_count=kept_count,
            latest_score=None,
            latest_marker=f"round {round_num} leaf solve complete",
            start_ts=start_ts,
            current_stage="compose_parent",
            leaf_total=len(all_leafs),
            leaf_accepted=len(accepted_leafs),
            top_level_ready=False,
            leaf_worker_count=max(1, args.workers),
            leaf_workers_active=0,
            leaf_workers_queued=0,
            leaf_workers_completed=len(accepted_leafs),
            current_node=args.parent,
            current_parent=args.parent,
            top_level_status="pending",
            composition_status="composing_parent",
            copper_accounting={},
        )

        compose_cmd = _build_compose_cmd(
            project_dir=project_dir,
            parent=args.parent,
            output_json=composition_json,
            only=args.only,
        )
        compose_rc, compose_stdout, compose_stderr = _run_command(
            compose_cmd,
            cwd=project_dir,
            timeout_s=None,
        )

        visible_rc: int | None = None
        visible_stdout = ""
        visible_stderr = ""
        visible_ok = False
        parent_copper_accounting: dict[str, int] = {}

        if not args.skip_visible:
            _write_live_status(
                status_json_path,
                status_txt_path,
                phase="running",
                rounds_total=args.rounds,
                round_num=round_num,
                best_score=max(best_score, 0.0),
                kept_count=kept_count,
                latest_score=None,
                latest_marker=f"round {round_num} parent composed",
                start_ts=start_ts,
                current_stage="route_parent",
                leaf_total=len(all_leafs),
                leaf_accepted=len(accepted_leafs),
                top_level_ready=False,
                leaf_worker_count=max(1, args.workers),
                leaf_workers_active=0,
                leaf_workers_queued=0,
                leaf_workers_completed=len(accepted_leafs),
                current_node=args.parent,
                current_parent=args.parent,
                top_level_status="routing_top_level",
                composition_status="routing_parent",
                copper_accounting={},
            )

            visible_cmd = [
                sys.executable,
                str(SCRIPT_DIR / "compose_subcircuits.py"),
                "--project",
                str(project_dir),
                "--parent",
                args.parent,
                "--mode",
                "packed",
                "--spacing-mm",
                "6",
                "--pcb",
                str(pcb),
                "--route",
                "--output",
                str(parent_output_json),
            ]
            if args.config:
                visible_cmd.extend(["--config", args.config])
            if args.jar:
                visible_cmd.extend(["--jar", args.jar])
            for selector in args.only:
                visible_cmd.extend(["--only", selector])

            visible_rc, visible_stdout, visible_stderr = _run_command(
                visible_cmd,
                cwd=project_dir,
                timeout_s=None,
            )
            visible_ok = visible_rc == 0
            parent_copper_accounting = _extract_parent_copper_accounting(project_dir)
        else:
            visible_ok = compose_rc == 0
            parent_copper_accounting = _extract_parent_copper_accounting(project_dir)

        composition_ok = compose_rc == 0
        score, score_breakdown, score_notes, score_context = _score_round(
            accepted_leafs=accepted_leafs,
            all_leafs=all_leafs,
            composition_ok=composition_ok,
            visible_ok=visible_ok,
            parent_copper_accounting=parent_copper_accounting,
            baseline_score=baseline_score,
            recent_scores=recent_scores,
            plateau_count=plateau_count,
        )
        duration_s = round(time.monotonic() - t0, 2)

        if baseline_score is None:
            baseline_score = score_context["absolute_score"]

        improvement_vs_best = (
            score if best_score < 0.0 else round(score - best_score, 3)
        )
        keep_threshold = 0.5
        is_meaningful_improvement = (
            best_score < 0.0 or improvement_vs_best >= keep_threshold
        )

        if is_meaningful_improvement:
            plateau_count = 0
        else:
            plateau_count += 1

        round_result = HierarchyRound(
            round_num=round_num,
            seed=round_seed,
            mode="hierarchical",
            score=score,
            kept=is_meaningful_improvement,
            duration_s=duration_s,
            leaf_total=len(all_leafs),
            leaf_accepted=len(accepted_leafs),
            parent_composed=composition_ok,
            top_level_ready=visible_ok,
            accepted_trace_count=sum(
                item.get("trace_count", 0) for item in accepted_leafs
            ),
            accepted_via_count=sum(item.get("via_count", 0) for item in accepted_leafs),
            latest_stage="done",
            details=(
                f"leafs {len(accepted_leafs)}/{len(all_leafs)} accepted; "
                f"compose={'ok' if composition_ok else 'fail'}; "
                f"top={'ok' if visible_ok else 'fail'}; "
                f"absolute={score_context['absolute_score']:.2f}; "
                f"parent_quality={score_context['parent_quality_score']:.2f}; "
                f"improvement={score_context['improvement_score']:.2f}; "
                f"escape={score_context['plateau_escape_score']:.2f}; "
                f"improvement_vs_best={improvement_vs_best:+.2f}; "
                f"plateau={plateau_count}"
            ),
            artifact_root=str(project_dir / ".experiments" / "subcircuits"),
            composition_json=str(composition_json),
            visible_output_dir=str(parent_output_json),
            leaf_names=leaf_names,
            accepted_leaf_names=accepted_leaf_names,
            score_breakdown=score_breakdown,
            score_notes=score_notes
            + [
                f"absolute_score={score_context['absolute_score']:.3f}",
                f"parent_quality_score={score_context['parent_quality_score']:.3f}",
                f"improvement_score={score_context['improvement_score']:.3f}",
                f"plateau_escape_score={score_context['plateau_escape_score']:.3f}",
                "leaf_size_reduction_loop_plan=after_best_leaf_layout_found_shrink_local_outline_in_small_steps_until_validation_fails_then_keep_last_passing_size",
                "parent_size_reduction_loop_plan=after_best_parent_layout_found_shrink_parent_outline_in_small_steps_preserving_child_copper_then_reroute_and_keep_last_passing_size",
                "size_reduction_acceptance=must_preserve_required_anchors_and_avoid_new_illegal_geometry_or_drc_regression",
                f"keep_threshold={keep_threshold:.2f}",
                f"plateau_threshold={max(1, args.plateau)}",
                f"meaningful_improvement={is_meaningful_improvement}",
            ],
            absolute_score=score_context["absolute_score"],
            improvement_score=score_context["improvement_score"],
            plateau_escape_score=score_context["plateau_escape_score"],
            parent_quality_score=score_context["parent_quality_score"],
            baseline_score=score_context["baseline_score"],
            rolling_score=score_context["rolling_score"],
            improvement_vs_best=improvement_vs_best,
            improvement_vs_baseline=score_context["improvement_vs_baseline"],
            improvement_vs_recent=score_context["improvement_vs_recent"],
            plateau_count=plateau_count,
        )

        if round_result.kept:
            best_score = score
            kept_count += 1
            best_round = round_result

            best_summary = {
                "round_num": round_num,
                "seed": round_seed,
                "score": score,
                "absolute_score": round_result.absolute_score,
                "improvement_score": round_result.improvement_score,
                "plateau_escape_score": round_result.plateau_escape_score,
                "parent_quality_score": round_result.parent_quality_score,
                "baseline_score": round_result.baseline_score,
                "rolling_score": round_result.rolling_score,
                "details": round_result.details,
                "composition_json": str(composition_json),
                "visible_output_dir": str(parent_output_json),
            }
            _write_json(best_dir / "best_hierarchical_round.json", best_summary)

            if composition_json.exists():
                _copy_if_exists(
                    composition_json, best_dir / "best_parent_composition.json"
                )

            preview = _select_preview_image(
                project_dir
                / ".experiments"
                / "subcircuits"
                / "subcircuit__8a5edab282"
                / "renders"
            )
            if preview is not None:
                _copy_if_exists(preview, work_dir / "best_preview.png")
                _copy_if_exists(preview, frames_dir / f"frame_{round_num:04d}.png")
                _copy_if_exists(preview, frames_dir / "frame_latest.png")

        recent_scores.append(round_result.absolute_score)
        if len(recent_scores) > 5:
            recent_scores = recent_scores[-5:]

        _append_jsonl(log_path, asdict(round_result))
        _write_round_detail(
            rounds_dir,
            round_result,
            accepted_leafs=accepted_leafs,
            all_leafs=all_leafs,
            solve_exit_code=solve_rc,
            compose_exit_code=compose_rc,
            visible_exit_code=visible_rc,
            solve_stdout=solve_stdout,
            solve_stderr=solve_stderr,
            compose_stdout=compose_stdout,
            compose_stderr=compose_stderr,
            visible_stdout=visible_stdout,
            visible_stderr=visible_stderr,
            parent_copper_accounting=parent_copper_accounting,
        )
        _write_frame_metadata(frames_dir, round_result)

        latest_marker = (
            "new best"
            if round_result.kept
            else (
                "plateau"
                if plateau_count >= max(1, args.plateau)
                else "no meaningful improvement"
            )
        )
        _write_live_status(
            status_json_path,
            status_txt_path,
            phase="running",
            rounds_total=args.rounds,
            round_num=round_num,
            best_score=max(best_score, 0.0),
            kept_count=kept_count,
            latest_score=score,
            latest_marker=latest_marker,
            start_ts=start_ts,
            current_stage="done",
            leaf_total=len(all_leafs),
            leaf_accepted=len(accepted_leafs),
            top_level_ready=visible_ok,
            leaf_worker_count=max(1, args.workers),
            leaf_workers_active=0,
            leaf_workers_queued=0,
            leaf_workers_completed=len(accepted_leafs),
            current_node=args.parent,
            current_parent=args.parent,
            top_level_status="ready" if visible_ok else "not_ready",
            composition_status="done" if composition_ok else "failed",
            copper_accounting=parent_copper_accounting,
        )

        print(
            f"Round {round_num:3d}/{args.rounds} "
            f"score={score:6.2f} "
            f"leafs={len(accepted_leafs)}/{len(all_leafs)} "
            f"compose={'ok' if composition_ok else 'fail'} "
            f"top={'ok' if visible_ok else 'fail'} "
            f"[{'KEPT' if round_result.kept else 'discard'}]"
        )

    phase = "done"
    if _check_stop_request(work_dir):
        phase = "done"
        _safe_unlink(work_dir / "stop.now")

    final_payload = {
        "pipeline": "hierarchical_subcircuits",
        "status": phase,
        "master_seed": master_seed,
        "rounds_requested": args.rounds,
        "best_score": max(best_score, 0.0),
        "baseline_score": baseline_score,
        "recent_scores": recent_scores,
        "kept_count": kept_count,
        "plateau_count": plateau_count,
        "best_round": asdict(best_round) if best_round else None,
    }
    _write_json(work_dir / "hierarchical_summary.json", final_payload)

    final_parent_copper_accounting = _extract_parent_copper_accounting(project_dir)

    _write_live_status(
        status_json_path,
        status_txt_path,
        phase=phase,
        rounds_total=args.rounds,
        round_num=best_round.round_num if best_round else 0,
        best_score=max(best_score, 0.0),
        kept_count=kept_count,
        latest_score=max(best_score, 0.0) if best_round else None,
        latest_marker="run complete",
        start_ts=start_ts,
        current_stage="complete",
        leaf_total=best_round.leaf_total if best_round else 0,
        leaf_accepted=best_round.leaf_accepted if best_round else 0,
        top_level_ready=best_round.top_level_ready if best_round else False,
        leaf_worker_count=max(1, args.workers),
        leaf_workers_active=0,
        leaf_workers_queued=0,
        leaf_workers_completed=best_round.leaf_accepted if best_round else 0,
        current_node=args.parent,
        current_parent=args.parent,
        top_level_status=(
            "ready" if best_round and best_round.top_level_ready else "not_ready"
        ),
        composition_status="complete",
        copper_accounting=final_parent_copper_accounting,
    )

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(final_payload, f, indent=2)
            f.write("\n")

    print()
    print("=== Hierarchical Autoexperiment Complete ===")
    print(f"Best score: {max(best_score, 0.0):.2f}")
    if best_round:
        print(f"Best round: {best_round.round_num}")
        print(
            f"Leafs:      {best_round.leaf_accepted}/{best_round.leaf_total} accepted"
        )
        print(f"Top level:  {'ready' if best_round.top_level_ready else 'not ready'}")
    print(f"Log:        {log_path}")
    print(f"Status:     {status_json_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
