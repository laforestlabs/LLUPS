#!/usr/bin/env python3
"""Autonomous experiment loop for PCB layout optimization.

Inspired by karpathy/autoresearch: mutate parameters, run pipeline,
score, keep or discard. Pure Python — burns electricity, not tokens.

Two modes:
  MINOR: tweak force constants, grid snap, cooling — small perturbations
  MAJOR: reshuffle placement seed, try different cluster strategies

The loop detects plateau (no improvement for N rounds of minor tweaks)
and automatically escalates to a MAJOR mutation to escape local optima.

Usage:
    python3 autoexperiment.py <file.kicad_pcb> [--rounds 100] [--program program.md]
"""
from __future__ import annotations
import argparse
import copy
import glob
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from autoplacer.config import DEFAULT_CONFIG
from autoplacer.pipeline import FullPipeline
from autoplacer.brain.types import ExperimentScore


@dataclass
class Experiment:
    """Record of a single experiment run."""
    round_num: int
    seed: int
    config_delta: dict        # only the keys that differ from baseline
    mode: str                 # "minor" or "major"
    score: float = 0.0
    details: str = ""
    duration_s: float = 0.0
    kept: bool = False
    # Scoring breakdown
    placement_score: float = 0.0
    route_completion: float = 0.0
    trace_efficiency: float = 0.0
    via_score: float = 0.0
    courtyard_overlap: float = 0.0
    board_containment: float = 0.0
    # DRC counts
    drc_shorts: int = 0
    drc_unconnected: int = 0
    drc_clearance: int = 0
    drc_courtyard: int = 0
    drc_total: int = 0


def load_program(path: str) -> dict:
    """Load program.md — the human-editable search space definition.
    Returns parsed config with parameter ranges and strategy."""
    import re
    program = {"param_ranges": {}, "strategy": {}, "score_weights": {}}
    if not os.path.exists(path):
        return program

    with open(path) as f:
        text = f.read()

    # Parse YAML-like blocks from markdown code fences
    for match in re.finditer(r'```(?:yaml|json)\s*\n(.*?)```', text, re.DOTALL):
        block = match.group(1).strip()
        try:
            data = json.loads(block)
            program.update(data)
        except json.JSONDecodeError:
            pass  # skip non-JSON blocks

    return program


def mutate_config_minor(base: dict, rng: random.Random,
                        param_ranges: dict = None) -> dict:
    """Small perturbation of continuous parameters."""
    cfg = copy.deepcopy(base)
    ranges = param_ranges or {}

    # Parameters eligible for minor mutation with (min, max, sigma_frac)
    tunable = {
        "force_attract_k": (0.005, 0.1, 0.15),
        "force_repel_k":   (150.0, 400.0, 0.15),
        "cooling_factor":  (0.90, 0.995, 0.05),
        "edge_margin_mm":  (4.0, 10.0, 0.1),
        "clearance_mm":    (0.15, 0.4, 0.1),
        "existing_trace_cost": (200.0, 5000.0, 0.2),
        "max_rips_per_net": (2, 15, 0.2),
    }
    # Override with program.md ranges if provided
    for k, v in ranges.items():
        if k in tunable and isinstance(v, (list, tuple)) and len(v) >= 2:
            tunable[k] = (v[0], v[1], v[2] if len(v) > 2 else 0.15)

    # Mutate 1-3 parameters
    n_mutations = rng.randint(1, 3)
    keys = rng.sample(list(tunable.keys()), min(n_mutations, len(tunable)))

    for key in keys:
        lo, hi, sigma_frac = tunable[key]
        current = cfg.get(key, (lo + hi) / 2)
        sigma = (hi - lo) * sigma_frac
        new_val = current + rng.gauss(0, sigma)
        # Clamp
        new_val = max(lo, min(hi, new_val))
        # Integer params stay integer
        if isinstance(cfg.get(key), int) or key in ("max_rips_per_net",):
            new_val = int(round(new_val))
        cfg[key] = round(new_val, 4)

    return cfg


def mutate_config_major(base: dict, rng: random.Random,
                        param_ranges: dict = None) -> dict:
    """Large structural change: new seed + aggressive param shifts."""
    cfg = mutate_config_minor(base, rng, param_ranges)

    # Also mutate more aggressively — wider sigma
    aggressive_tunable = {
        "force_attract_k": (0.005, 0.15, 0.4),
        "force_repel_k":   (100.0, 500.0, 0.4),
        "cooling_factor":  (0.90, 0.995, 0.15),
    }
    keys = rng.sample(list(aggressive_tunable.keys()),
                      rng.randint(1, len(aggressive_tunable)))
    for key in keys:
        lo, hi, sigma_frac = aggressive_tunable[key]
        # Sample fresh from range instead of perturbing
        new_val = rng.uniform(lo, hi)
        cfg[key] = round(new_val, 4)

    return cfg


def config_delta(base: dict, candidate: dict) -> dict:
    """Return only the keys that differ between base and candidate."""
    delta = {}
    for k in candidate:
        if k in base and candidate[k] != base[k]:
            delta[k] = candidate[k]
    return delta


def quick_drc(pcb_path: str) -> dict:
    """Run kicad-cli DRC and return violation counts by category."""
    import re
    counts = {"shorts": 0, "unconnected": 0, "clearance": 0, "courtyard": 0, "total": 0}
    try:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            report_path = f.name
        subprocess.run(
            ["kicad-cli", "pcb", "drc", "-o", report_path, pcb_path],
            capture_output=True, text=True, timeout=30,
        )
        with open(report_path) as f:
            report = f.read()
        os.remove(report_path)

        for line in report.splitlines():
            m = re.match(r'^\[(\w+)\]:', line)
            if not m:
                continue
            vtype = m.group(1)
            counts["total"] += 1
            if vtype == "shorting_items":
                counts["shorts"] += 1
            elif vtype == "unconnected_items":
                counts["unconnected"] += 1
            elif vtype in ("clearance", "hole_clearance", "copper_edge_clearance"):
                counts["clearance"] += 1
            elif vtype == "courtyards_overlap":
                counts["courtyard"] += 1
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return counts


def snapshot_pcb(pcb_path: str, output_png: str,
                 canvas_px: int = 900, board_mm: tuple = (140.0, 90.0)):
    """Export a fixed-scale PNG snapshot for progress GIF.

    Renders to a constant canvas (canvas_px square) with the board bbox
    sized to ~80% of the canvas — same scale every frame regardless of
    where components have moved. White opaque background for contrast
    and to prevent prior frames bleeding through GIF disposal.
    """
    try:
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tmp:
            svg_path = tmp.name
        # Use --fit-page-to-board so SVG viewBox = exact board outline.
        # We'll then rescale at fixed mm-to-pixel ratio in magick.
        subprocess.run([
            "kicad-cli", "pcb", "export", "svg",
            "--layers", "F.Cu,B.Cu,F.SilkS,Edge.Cuts",
            "--mode-single", "--fit-page-to-board",
            "--exclude-drawing-sheet", "--drill-shape-opt", "2",
            "-o", svg_path, pcb_path,
        ], capture_output=True, check=True)

        # Fixed scale: canvas is canvas_px square, board occupies 80%.
        bw, bh = board_mm
        scale = (canvas_px * 0.80) / max(bw, bh)
        target_w = int(round(bw * scale))
        target_h = int(round(bh * scale))

        subprocess.run([
            "magick",
            "-density", "300",
            "-background", "white",
            svg_path,
            "-flatten",
            "-resize", f"{target_w}x{target_h}!",
            "-bordercolor", "#222", "-border", "3",
            "-background", "white",
            "-gravity", "center",
            "-extent", f"{canvas_px}x{canvas_px}",
            output_png,
        ], capture_output=True, check=True)
        os.remove(svg_path)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass  # non-fatal — skip snapshot if tools missing


def assemble_gif(frames_dir: Path, output_path: str, delay_cs: int = 50):
    """Stitch numbered PNG frames into an animated GIF using ImageMagick.

    Uses -dispose Background and skips -layers Optimize so each frame is
    a full redraw — prevents stale pixels from prior frames sticking around.
    """
    frames = sorted(glob.glob(str(frames_dir / "frame_*.png")))
    if len(frames) < 2:
        return
    cmd = [
        "magick",
        "-dispose", "Background",
        "-delay", str(delay_cs), "-loop", "0",
    ]
    cmd.extend(frames[:-1])
    cmd.extend(["-delay", "200", frames[-1]])
    # Coalesce ensures every frame is independent (no incremental diffs).
    cmd.extend(["-coalesce", output_path])
    try:
        subprocess.run(cmd, capture_output=True, check=True)
        print(f"  GIF saved: {output_path} ({len(frames)} frames)")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"  GIF assembly failed: {e}", file=sys.stderr)


def run_experiment(pcb_path: str, work_dir: Path, cfg: dict,
                   seed: int, quiet: bool = True) -> tuple[ExperimentScore, float]:
    """Run one full pipeline experiment. Returns (score, duration_seconds)."""
    # Work on a copy so we don't corrupt the original
    work_pcb = str(work_dir / "experiment.kicad_pcb")
    shutil.copy2(pcb_path, work_pcb)

    # Suppress stdout/stderr during experiment if quiet.
    # wxWidgets writes debug spam directly to fd 1/2, so we redirect
    # the underlying file descriptors, not just Python's sys.std*.
    if quiet:
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        saved_stdout_fd = os.dup(1)
        saved_stderr_fd = os.dup(2)
        os.dup2(devnull_fd, 1)
        os.dup2(devnull_fd, 2)
        os.close(devnull_fd)
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = open(os.devnull, 'w')
        sys.stderr = open(os.devnull, 'w')

    t0 = time.monotonic()
    try:
        pipeline = FullPipeline()
        result = pipeline.run(work_pcb, work_pcb, config=cfg, seed=seed)
        exp_score = result["experiment_score"]
    except Exception as e:
        exp_score = ExperimentScore()
        exp_score.total = -1.0
        if not quiet:
            print(f"  FAILED: {e}")
    finally:
        duration = time.monotonic() - t0
        if quiet:
            sys.stdout.close()
            sys.stderr.close()
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            os.dup2(saved_stdout_fd, 1)
            os.dup2(saved_stderr_fd, 2)
            os.close(saved_stdout_fd)
            os.close(saved_stderr_fd)

    return exp_score, duration


def main():
    parser = argparse.ArgumentParser(
        description="Autonomous PCB layout experiment loop")
    parser.add_argument("pcb", help="Input .kicad_pcb file")
    parser.add_argument("--rounds", "-n", type=int, default=50,
                        help="Max experiment rounds (default: 50)")
    parser.add_argument("--program", "-p", default="program.md",
                        help="Path to program.md search space definition")
    parser.add_argument("--output", "-o",
                        help="Output best .kicad_pcb (default: <input>_best.kicad_pcb)")
    parser.add_argument("--log", "-l", default="experiments.jsonl",
                        help="Experiment log file (JSONL)")
    parser.add_argument("--plateau", type=int, default=5,
                        help="Minor rounds without improvement before MAJOR (default: 5)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Master RNG seed (default: random)")
    parser.add_argument("--quiet", "-q", action="store_true", default=True,
                        help="Suppress pipeline output (default: on)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show pipeline output")
    parser.add_argument("--no-render", action="store_true",
                        help="Skip PCB snapshot rendering (saves time)")
    args = parser.parse_args()

    if args.verbose:
        args.quiet = False

    # Setup
    master_seed = args.seed if args.seed is not None else random.randint(0, 2**31)
    rng = random.Random(master_seed)
    program = load_program(args.program)
    param_ranges = program.get("param_ranges", {})
    score_weights = program.get("score_weights", None)

    work_dir = Path(args.pcb).parent / ".experiments"
    work_dir.mkdir(exist_ok=True)
    best_dir = work_dir / "best"
    best_dir.mkdir(exist_ok=True)
    frames_dir = work_dir / "frames"
    if not args.no_render:
        frames_dir.mkdir(exist_ok=True)

    output_path = args.output or str(Path(args.pcb).with_suffix('')) + "_best.kicad_pcb"
    log_path = work_dir / args.log

    # Sniff board outline once so all GIF frames render at the same scale.
    board_mm = (140.0, 90.0)
    try:
        with open(args.pcb) as f:
            pcb_text = f.read()
        m = re.search(r'\(gr_rect\s+\(start\s+([\d.\-]+)\s+([\d.\-]+)\)\s+'
                      r'\(end\s+([\d.\-]+)\s+([\d.\-]+)\)', pcb_text)
        if m:
            x0, y0, x1, y1 = (float(v) for v in m.groups())
            board_mm = (abs(x1 - x0), abs(y1 - y0))
            print(f"Board outline: {board_mm[0]:.1f} x {board_mm[1]:.1f} mm")
    except (OSError, ValueError):
        pass

    print(f"=== Autonomous PCB Experiment Loop ===")
    print(f"PCB:         {args.pcb}")
    print(f"Rounds:      {args.rounds}")
    print(f"Master seed: {master_seed}")
    print(f"Plateau:     {args.plateau} minor rounds -> MAJOR")
    print(f"Log:         {log_path}")
    print(f"Output:      {output_path}")
    print()

    # Run baseline
    print("Round   0/-- [BASE ] running baseline...", flush=True)
    best_cfg = dict(DEFAULT_CONFIG)
    best_seed = 0
    best_score, base_dur = run_experiment(
        args.pcb, work_dir, best_cfg, best_seed, quiet=args.quiet)
    if score_weights:
        best_score.compute(score_weights)

    # Apply same shorts penalty to baseline so it's directly comparable
    base_drc = quick_drc(str(work_dir / "experiment.kicad_pcb"))
    if base_drc["shorts"] > 0:
        import math
        base_penalty = 0.10 / (1 + math.log10(1 + base_drc["shorts"]))
        best_score.total *= base_penalty

    print(f"  -> baseline score={best_score.total:6.2f} shorts={base_drc['shorts']} "
          f"drc={base_drc['total']} ({base_dur:.1f}s)", flush=True)

    # Save baseline as current best
    shutil.copy2(str(work_dir / "experiment.kicad_pcb"),
                 str(best_dir / "best.kicad_pcb"))
    best_total = best_score.total

    experiments: list[Experiment] = []
    minor_stagnant = 0
    kept_count = 0
    loop_t0 = time.monotonic()

    for round_num in range(1, args.rounds + 1):
        # Decide mode
        if minor_stagnant >= args.plateau:
            mode = "major"
            minor_stagnant = 0
        else:
            mode = "minor"

        # Mutate
        exp_seed = rng.randint(0, 2**31)
        if mode == "minor":
            candidate_cfg = mutate_config_minor(best_cfg, rng, param_ranges)
            candidate_seed = best_seed  # keep same seed for minor tweaks
        else:
            candidate_cfg = mutate_config_major(best_cfg, rng, param_ranges)
            candidate_seed = exp_seed   # new seed = new initial placement

        delta = config_delta(DEFAULT_CONFIG, candidate_cfg)

        # Run — announce BEFORE so user sees progress immediately
        t_label = f"Round {round_num:3d}/{args.rounds} [{mode[:5].upper():5s}]"
        delta_str = " ".join(f"{k}={v}" for k, v in delta.items()) or "(no delta)"
        print(f"{t_label} running... {delta_str[:80]}", flush=True)
        score, duration = run_experiment(
            args.pcb, work_dir, candidate_cfg, candidate_seed, quiet=args.quiet)

        if score_weights:
            score.compute(score_weights)

        # Run DRC — shorts are heavily penalized but allow incremental improvement
        drc = quick_drc(str(work_dir / "experiment.kicad_pcb"))
        if drc["shorts"] > 0:
            # Logarithmic penalty: 1 short = ~10% of original, 10 shorts = ~5%,
            # 100 shorts = ~3%, 1000 shorts = ~2%. Always positive so fewer
            # shorts beats more shorts even when both are "failing".
            import math
            penalty_factor = 0.10 / (1 + math.log10(1 + drc["shorts"]))
            score.total *= penalty_factor

        # Keep or discard
        kept = score.total > best_total
        if kept:
            improvement = score.total - best_total
            best_total = score.total
            best_cfg = candidate_cfg
            best_seed = candidate_seed
            best_score = score
            minor_stagnant = 0
            kept_count += 1
            # Save best PCB
            shutil.copy2(str(work_dir / "experiment.kicad_pcb"),
                         str(best_dir / "best.kicad_pcb"))
            marker = f"NEW BEST +{improvement:.2f}"
        else:
            minor_stagnant += 1
            marker = f"discard (stagnant={minor_stagnant})"

        # Per-round line + running progress summary (ETA, kept count)
        elapsed = time.monotonic() - loop_t0
        avg_round = elapsed / round_num
        eta_s = avg_round * (args.rounds - round_num)
        eta_str = f"{int(eta_s // 60)}m{int(eta_s % 60):02d}s"
        print(f"  -> score={score.total:6.2f} best={best_total:6.2f} "
              f"shorts={drc['shorts']:3d} drc={drc['total']:4d} "
              f"({duration:.1f}s) [{marker}]", flush=True)
        print(f"     [progress {round_num}/{args.rounds}  kept={kept_count}  "
              f"elapsed={int(elapsed//60)}m{int(elapsed%60):02d}s  ETA={eta_str}]",
              flush=True)

        # Compute sub-scores for breakdown logging
        if score.total_nets > 0:
            route_pct = ((score.total_nets - score.failed_nets) / score.total_nets) * 100
        else:
            route_pct = 100.0
        if score.total_trace_length_mm > 0 and score.total_nets > 0:
            avg_per_net = score.total_trace_length_mm / max(1, score.routed_nets)
            trace_eff = max(0, min(100, 100 - avg_per_net))
        else:
            trace_eff = 50.0
        if score.routed_nets > 0:
            via_sc = max(0, min(100, 100 - (score.via_count / score.routed_nets) * 20))
        else:
            via_sc = 50.0

        # Log
        exp = Experiment(
            round_num=round_num,
            seed=candidate_seed,
            config_delta=delta,
            mode=mode,
            score=score.total,
            details=score.summary(),
            duration_s=round(duration, 1),
            kept=kept,
            placement_score=round(score.placement.total, 1),
            route_completion=round(route_pct, 1),
            trace_efficiency=round(trace_eff, 1),
            via_score=round(via_sc, 1),
            courtyard_overlap=round(score.placement.courtyard_overlap, 1),
            board_containment=round(score.placement.board_containment, 1),
            drc_shorts=drc["shorts"],
            drc_unconnected=drc["unconnected"],
            drc_clearance=drc["clearance"],
            drc_courtyard=drc["courtyard"],
            drc_total=drc["total"],
        )
        experiments.append(exp)

        with open(log_path, 'a') as f:
            f.write(json.dumps(asdict(exp), default=str) + '\n')

        # Snapshot kept improvements for progress GIF
        if not args.no_render and kept:
            frame_png = str(frames_dir / f"frame_{round_num:04d}.png")
            snapshot_pcb(str(best_dir / "best.kicad_pcb"), frame_png,
                         board_mm=board_mm)

    # Assemble progress GIF from frames
    if not args.no_render:
        gif_path = str(work_dir / "progress.gif")
        assemble_gif(frames_dir, gif_path)

    # Copy best result to output
    best_pcb = str(best_dir / "best.kicad_pcb")
    if os.path.exists(best_pcb):
        shutil.copy2(best_pcb, output_path)

    print()
    print(f"=== Done: {len(experiments)} experiments ===")
    print(f"Best score: {best_score.summary()}")
    print(f"Best config delta from default: {json.dumps(config_delta(DEFAULT_CONFIG, best_cfg), indent=2)}")
    print(f"Best seed: {best_seed}")
    print(f"Output: {output_path}")
    print(f"Log:    {log_path}")


if __name__ == "__main__":
    main()
