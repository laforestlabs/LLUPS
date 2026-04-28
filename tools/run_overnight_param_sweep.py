#!/usr/bin/env python3
"""Two-stage overnight parameter sweep orchestrator.

Workflow (matches the GUI's leaves-first / pin-best / parent two-phase loop):
  1. Stage A: autoexperiment --leaves-only --random-search   ~3 hr
  2. pin_best_leaves.py: pin the highest-scoring round per leaf
  3. Stage B: autoexperiment --parents-only --random-search  ~3.5 hr
  4. analyze_param_sweep.py: compute proposed defaults + ranges
  5. Validation: 5 rounds with proposed defaults applied (greedy mode)

Outputs end up under <experiments_dir>/param_sweep/. The script is safe to
interrupt: touch <experiments_dir>/stop.now (autoexperiment honours this) or
SIGINT -- the in-flight phase will checkpoint and the script will skip ahead.

Usage:
    python tools/run_overnight_param_sweep.py
        [--stage-a-budget-min 180]
        [--stage-b-budget-min 210]
        [--workers 6]
        [--skip-validation]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_DIR = REPO_ROOT
EXPERIMENTS_DIR = PROJECT_DIR / ".experiments"
SWEEP_DIR = EXPERIMENTS_DIR / "param_sweep"
HIERARCHY_DIR = EXPERIMENTS_DIR / "hierarchical_autoexperiment"
TOOLS_DIR = REPO_ROOT / "tools"
LOG_FILE = SWEEP_DIR / "orchestrator.log"

# Honour SIGINT cleanly so a Ctrl-C while autoexperiment is running does
# not leave child processes orphaned.
_CHILD_PROC: subprocess.Popen | None = None


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _on_sigint(signum: int, frame: Any) -> None:
    _log("SIGINT received, sending stop.now to autoexperiment")
    (EXPERIMENTS_DIR / "stop.now").write_text("orchestrator interrupt\n", encoding="utf-8")
    if _CHILD_PROC is not None and _CHILD_PROC.poll() is None:
        _CHILD_PROC.send_signal(signal.SIGTERM)


def _fmt_elapsed(seconds: float) -> str:
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}h{m:02d}m{s:02d}s"


def _archive_phase(stage_name: str) -> None:
    """Move the autoexperiment outputs into <sweep>/<stage_name>/."""
    target_dir = SWEEP_DIR / stage_name
    target_dir.mkdir(parents=True, exist_ok=True)

    if HIERARCHY_DIR.exists():
        # Move every round_NNNN/ subdir into target_dir/.
        for child in sorted(HIERARCHY_DIR.iterdir()):
            if child.is_dir() and child.name.startswith("round_"):
                shutil.move(str(child), str(target_dir / child.name))
        # Remove the now-empty hierarchy dir so the next phase starts clean.
        try:
            HIERARCHY_DIR.rmdir()
        except OSError:
            pass

    log_src = EXPERIMENTS_DIR / "experiments.jsonl"
    log_dst = SWEEP_DIR / f"{stage_name}.jsonl"
    if log_src.exists():
        shutil.move(str(log_src), str(log_dst))

    rounds_src = EXPERIMENTS_DIR / "rounds"
    if rounds_src.is_dir():
        rounds_dst = target_dir / "rounds"
        if rounds_dst.exists():
            shutil.rmtree(str(rounds_dst))
        shutil.move(str(rounds_src), str(rounds_dst))


def _run_stage(
    *,
    stage_name: str,
    rounds: int,
    workers: int,
    extra_flags: list[str],
    config_path: Path | None = None,
    seed: int | None = None,
    timeout_s: int | None = None,
) -> tuple[int, float]:
    """Run autoexperiment with the given flags. Returns (rc, elapsed_seconds)."""
    pcb = PROJECT_DIR / "LLUPS.kicad_pcb"
    schematic = PROJECT_DIR / "LLUPS.kicad_sch"

    cmd: list[str] = [
        sys.executable,
        "-u",
        "-m",
        "kicraft.cli.autoexperiment",
        str(pcb),
        "--schematic",
        str(schematic),
        "--rounds",
        str(rounds),
        "--workers",
        str(workers),
        "--leaf-rounds",
        "1",
    ]
    if seed is not None:
        cmd += ["--seed", str(seed)]
    if config_path is not None:
        cmd += ["--config", str(config_path)]
    cmd += list(extra_flags)

    _log(f"=== {stage_name} starting: rounds={rounds}, workers={workers} ===")
    _log(f"    cmd: {' '.join(cmd)}")

    # Stream child stdout/stderr to the orchestrator log so we keep a record
    # even when the run is unattended.
    stdout_path = SWEEP_DIR / f"{stage_name}.stdout.log"
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()

    global _CHILD_PROC
    with stdout_path.open("w", encoding="utf-8") as out:
        _CHILD_PROC = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_DIR),
            stdout=out,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            rc = _CHILD_PROC.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            _log(f"    {stage_name} TIMED OUT after {timeout_s}s; sending stop.now")
            (EXPERIMENTS_DIR / "stop.now").write_text("orchestrator timeout\n", encoding="utf-8")
            try:
                rc = _CHILD_PROC.wait(timeout=300)
            except subprocess.TimeoutExpired:
                _CHILD_PROC.terminate()
                rc = _CHILD_PROC.wait(timeout=60)
        finally:
            _CHILD_PROC = None
            elapsed = time.monotonic() - start
            try:
                (EXPERIMENTS_DIR / "stop.now").unlink()
            except FileNotFoundError:
                pass

    _log(f"=== {stage_name} done: rc={rc}, elapsed={_fmt_elapsed(elapsed)} ===")
    return rc, elapsed


def _run_helper(name: str, args: list[str]) -> int:
    cmd = [sys.executable, str(TOOLS_DIR / name)] + args
    _log(f"--- {name} {' '.join(args)} ---")
    out_path = SWEEP_DIR / f"{name.replace('.py', '')}.stdout.log"
    with out_path.open("w", encoding="utf-8") as out:
        rc = subprocess.run(
            cmd, cwd=str(PROJECT_DIR), stdout=out,
            stderr=subprocess.STDOUT, text=True,
        ).returncode
    _log(f"    {name} rc={rc} (output: {out_path})")
    return rc


def _build_validation_config(proposed_overlay_path: Path, dest: Path) -> bool:
    """Merge proposed defaults onto the project config to produce a validation config."""
    if not proposed_overlay_path.exists():
        return False
    try:
        overlay = json.loads(proposed_overlay_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(overlay, dict) or not overlay:
        return False
    project_cfg_path = PROJECT_DIR / "LLUPS_autoplacer.json"
    base: dict[str, Any] = {}
    if project_cfg_path.exists():
        try:
            base = json.loads(project_cfg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            base = {}
    merged = {**base, **overlay}
    dest.write_text(json.dumps(merged, indent=2, sort_keys=True), encoding="utf-8")
    return True


def _estimate_rounds(budget_seconds: float, per_round_estimate_s: float) -> int:
    return max(1, int(budget_seconds / per_round_estimate_s))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage-a-budget-min", type=int, default=180,
        help="Stage A wall-clock budget in minutes (default 180)",
    )
    parser.add_argument(
        "--stage-b-budget-min", type=int, default=210,
        help="Stage B wall-clock budget in minutes (default 210)",
    )
    parser.add_argument(
        "--workers", type=int, default=6,
        help="Leaf solve worker count (default 6)",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Master seed (default: random per-stage)",
    )
    parser.add_argument(
        "--per-round-leaf-s", type=float, default=70.0,
        help="Estimate of seconds per leaves-only round (default 70)",
    )
    parser.add_argument(
        "--per-round-parent-s", type=float, default=60.0,
        help="Estimate of seconds per parents-only round (default 60)",
    )
    parser.add_argument(
        "--skip-validation", action="store_true",
        help="Don't run the post-analysis validation rounds",
    )
    parser.add_argument(
        "--smoke-only", action="store_true",
        help="Run a 1-round smoke check of Stage A and exit",
    )
    args = parser.parse_args(argv or sys.argv[1:])

    SWEEP_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.unlink(missing_ok=True)

    signal.signal(signal.SIGINT, _on_sigint)
    signal.signal(signal.SIGTERM, _on_sigint)

    overall_start = time.monotonic()
    _log(f"orchestrator starting; pid={os.getpid()}; cwd={PROJECT_DIR}")
    _log(f"sweep dir: {SWEEP_DIR}")

    # Wipe stale leaf artifacts so every Stage A round produces fresh solves
    # for every leaf. Without this, prior canonical solved_layout.json files
    # let solve_subcircuits short-circuit unaffected leaves and Stage A only
    # exercises the leaves whose previous solves happened to fail.
    sub_root = EXPERIMENTS_DIR / "subcircuits"
    if sub_root.is_dir() and not args.smoke_only:
        archive = SWEEP_DIR / "preexisting_subcircuits"
        archive.parent.mkdir(parents=True, exist_ok=True)
        if archive.exists():
            shutil.rmtree(str(archive))
        shutil.move(str(sub_root), str(archive))
        _log(f"archived prior subcircuit artifacts to {archive}")
    # Also clear any leftover hierarchical_autoexperiment dir from prior runs
    # so the archive moves later only see this run's outputs.
    if HIERARCHY_DIR.is_dir() and not args.smoke_only:
        for child in list(HIERARCHY_DIR.iterdir()):
            if child.is_dir():
                shutil.rmtree(str(child))
            else:
                child.unlink(missing_ok=True)
        _log(f"cleared {HIERARCHY_DIR}")
    leftover_jsonl = EXPERIMENTS_DIR / "experiments.jsonl"
    if leftover_jsonl.exists() and not args.smoke_only:
        leftover_jsonl.unlink()
        _log(f"cleared {leftover_jsonl}")

    if args.smoke_only:
        rc, _ = _run_stage(
            stage_name="smoke",
            rounds=1,
            workers=args.workers,
            extra_flags=["--leaves-only", "--random-search"],
            seed=args.seed,
            timeout_s=600,
        )
        _archive_phase("smoke")
        return rc

    # ---- Stage A: leaves-only random search ------------------------------
    stage_a_budget_s = args.stage_a_budget_min * 60
    stage_a_rounds = _estimate_rounds(stage_a_budget_s, args.per_round_leaf_s)
    _log(f"stage A: budget={args.stage_a_budget_min}min, rounds={stage_a_rounds}")
    rc_a, _ = _run_stage(
        stage_name="stage_a",
        rounds=stage_a_rounds,
        workers=args.workers,
        extra_flags=["--leaves-only", "--random-search"],
        seed=args.seed,
        timeout_s=int(stage_a_budget_s * 1.10),  # 10% slack
    )
    _archive_phase("stage_a")
    if rc_a != 0:
        _log(f"WARNING: Stage A returned non-zero rc={rc_a}; continuing anyway")

    # ---- Pin best leaves -------------------------------------------------
    pin_rc = _run_helper("pin_best_leaves.py", [
        "--experiments-dir", str(EXPERIMENTS_DIR),
        "--report", str(SWEEP_DIR / "pin_summary.json"),
    ])
    if pin_rc != 0:
        _log(f"WARNING: pin_best_leaves rc={pin_rc}; Stage B may fail")

    # ---- Stage B: parents-only random search -----------------------------
    stage_b_budget_s = args.stage_b_budget_min * 60
    stage_b_rounds = _estimate_rounds(stage_b_budget_s, args.per_round_parent_s)
    _log(f"stage B: budget={args.stage_b_budget_min}min, rounds={stage_b_rounds}")
    rc_b, _ = _run_stage(
        stage_name="stage_b",
        rounds=stage_b_rounds,
        workers=args.workers,
        extra_flags=["--parents-only", "--random-search"],
        seed=(args.seed + 1) if args.seed is not None else None,
        timeout_s=int(stage_b_budget_s * 1.10),
    )
    _archive_phase("stage_b")
    if rc_b != 0:
        _log(f"WARNING: Stage B returned non-zero rc={rc_b}; continuing anyway")

    # ---- Analyze ---------------------------------------------------------
    analyze_rc = _run_helper("analyze_param_sweep.py", [
        "--experiments-dir", str(EXPERIMENTS_DIR),
        "--out-dir", str(SWEEP_DIR),
    ])
    if analyze_rc != 0:
        _log(f"ERROR: analyze rc={analyze_rc}; aborting validation")
        return analyze_rc

    # ---- Validation ------------------------------------------------------
    if args.skip_validation:
        _log("skipping validation (--skip-validation)")
    else:
        validation_cfg = SWEEP_DIR / "validation_config.json"
        ok = _build_validation_config(
            SWEEP_DIR / "proposed_default_config.json", validation_cfg
        )
        if not ok:
            _log("validation: no proposed_default_config.json; using project default")
            validation_cfg_arg: Path | None = None
        else:
            validation_cfg_arg = validation_cfg

        _log("validation: 5 rounds full pipeline at proposed defaults (greedy mode)")
        rc_v, _ = _run_stage(
            stage_name="validation",
            rounds=5,
            workers=args.workers,
            extra_flags=[],  # full pipeline, greedy mutation around proposed default
            config_path=validation_cfg_arg,
            seed=(args.seed + 2) if args.seed is not None else None,
            timeout_s=15 * 60,
        )
        _archive_phase("validation")
        if rc_v != 0:
            _log(f"WARNING: validation rc={rc_v}")

    elapsed = time.monotonic() - overall_start
    _log(f"=== overnight sweep complete: total elapsed={_fmt_elapsed(elapsed)} ===")
    _log(f"see: {SWEEP_DIR / 'analysis.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
