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
) -> float:
    leaf_total = len(all_leafs)
    leaf_accepted = len(accepted_leafs)
    acceptance_ratio = (leaf_accepted / leaf_total) if leaf_total > 0 else 0.0
    traces = sum(item.get("trace_count", 0) for item in accepted_leafs)
    vias = sum(item.get("via_count", 0) for item in accepted_leafs)

    score = 0.0
    score += acceptance_ratio * 70.0
    score += min(20.0, traces * 0.05)
    score += min(5.0, vias * 0.02)
    if composition_ok:
        score += 10.0
    if visible_ok:
        score += 15.0
    return round(score, 3)


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
) -> None:
    now = time.monotonic()
    elapsed_s = now - start_ts
    progress_pct = (round_num / rounds_total * 100.0) if rounds_total > 0 else 100.0

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
        "workers": {
            "total": 1,
            "in_flight": 0 if phase != "running" else 1,
            "idle": 0 if phase == "running" else 1,
        },
        "maybe_stuck": False,
        "hierarchy": {
            "current_stage": current_stage,
            "leaf_total": leaf_total,
            "leaf_accepted": leaf_accepted,
            "top_level_ready": top_level_ready,
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
        f"leafs: accepted={leaf_accepted} total={leaf_total}",
        f"top_level_ready: {top_level_ready}",
    ]
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
        },
        "artifacts": {
            "artifact_root": round_result.artifact_root,
            "composition_json": round_result.composition_json,
            "visible_output_dir": round_result.visible_output_dir,
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
        "score": round_result.score,
        "mode": round_result.mode,
        "latest_stage": round_result.latest_stage,
        "leaf_total": round_result.leaf_total,
        "leaf_accepted": round_result.leaf_accepted,
        "top_level_ready": round_result.top_level_ready,
    }
    _write_json(frames_dir / f"frame_{round_result.round_num:04d}.json", payload)


def _select_preview_image(visible_output_dir: Path) -> Path | None:
    candidates = [
        visible_output_dir / "parent_routed.png",
        visible_output_dir / "parent_stamped.png",
        visible_output_dir / "board.png",
        visible_output_dir / "snapshot.png",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    pngs = sorted(visible_output_dir.glob("*.png"))
    return pngs[0] if pngs else None


def _build_solve_cmd(
    *,
    schematic: Path,
    pcb: Path,
    rounds: int,
    seed: int,
    config: str | None,
    only: list[str],
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
        "grid",
        "--spacing-mm",
        "12",
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
        default=1,
        help="Reserved for GUI compatibility; not used by the hierarchical runner",
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
    )

    for round_num in range(1, args.rounds + 1):
        if _check_stop_request(work_dir):
            break

        round_seed = rng.randint(0, 2**31 - 1)
        round_dir = hierarchy_dir / f"round_{round_num:04d}"
        visible_output_dir = round_dir / "visible_parent"
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
        )

        t0 = time.monotonic()

        solve_cmd = _build_solve_cmd(
            schematic=schematic,
            pcb=pcb,
            rounds=args.leaf_rounds,
            seed=round_seed,
            config=args.config,
            only=args.only,
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
                current_stage="visible_top_level",
                leaf_total=len(all_leafs),
                leaf_accepted=len(accepted_leafs),
                top_level_ready=False,
            )

            visible_cmd = _build_visible_cmd(
                project_dir=project_dir,
                schematic=schematic,
                pcb=pcb,
                parent=args.parent,
                output_dir=visible_output_dir,
                config=args.config,
                rounds=args.leaf_rounds,
                seed=round_seed,
                only=args.only,
            )
            visible_rc, visible_stdout, visible_stderr = _run_command(
                visible_cmd,
                cwd=project_dir,
                timeout_s=None,
            )
            visible_ok = visible_rc == 0
        else:
            visible_ok = compose_rc == 0

        composition_ok = compose_rc == 0
        score = _score_round(
            accepted_leafs=accepted_leafs,
            all_leafs=all_leafs,
            composition_ok=composition_ok,
            visible_ok=visible_ok,
        )
        duration_s = round(time.monotonic() - t0, 2)

        round_result = HierarchyRound(
            round_num=round_num,
            seed=round_seed,
            mode="hierarchical",
            score=score,
            kept=score > best_score,
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
                f"top={'ok' if visible_ok else 'fail'}"
            ),
            artifact_root=str(project_dir / ".experiments" / "subcircuits"),
            composition_json=str(composition_json),
            visible_output_dir=str(visible_output_dir),
            leaf_names=leaf_names,
            accepted_leaf_names=accepted_leaf_names,
        )

        if round_result.kept:
            best_score = score
            kept_count += 1
            best_round = round_result

            best_summary = {
                "round_num": round_num,
                "seed": round_seed,
                "score": score,
                "details": round_result.details,
                "composition_json": str(composition_json),
                "visible_output_dir": str(visible_output_dir),
            }
            _write_json(best_dir / "best_hierarchical_round.json", best_summary)

            if composition_json.exists():
                _copy_if_exists(
                    composition_json, best_dir / "best_parent_composition.json"
                )

            preview = _select_preview_image(visible_output_dir)
            if preview is not None:
                _copy_if_exists(preview, work_dir / "best_preview.png")
                _copy_if_exists(preview, frames_dir / f"frame_{round_num:04d}.png")

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
        )
        _write_frame_metadata(frames_dir, round_result)

        latest_marker = "new best" if round_result.kept else "discarded"
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
        "kept_count": kept_count,
        "best_round": asdict(best_round) if best_round else None,
    }
    _write_json(work_dir / "hierarchical_summary.json", final_payload)

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
