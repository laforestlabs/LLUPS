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
import multiprocessing as mp
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Must come before autoplacer imports so spawn workers can find the package
_SCRIPT_DIR = str(Path(__file__).parent.absolute())
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from autoplacer.config import DEFAULT_CONFIG, LLUPS_CONFIG
from autoplacer.pipeline import FullPipeline
from autoplacer.brain.types import ExperimentScore

# Optional logging support
try:
    import logging_config
    LOGGING_AVAILABLE = True
except ImportError:
    LOGGING_AVAILABLE = False

log = None  # Will be initialized in main if logging available

def _check_stop_request(work_dir: Path) -> bool:
    """Check if stop has been requested via signal file."""
    stop_file = work_dir / "stop.now"
    return stop_file.exists()


def _request_stop(work_dir: Path) -> None:
    """Request graceful stop by creating signal file."""
    stop_file = work_dir / "stop.now"
    stop_file.touch()


def _log_event(event: str, **kwargs) -> None:
    """Log event if logging is available."""
    global log
    if log is not None:
        log.info(event, **kwargs)


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
    # Phase timing (ms)
    placement_ms: float = 0.0
    routing_ms: float = 0.0
    # Routing detail
    nets_routed: int = 0
    failed_net_names: list = field(default_factory=list)


def _format_mmss(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}m{seconds % 60:02d}s"


def _safe_mean(values: list[float], default: float = 0.0) -> float:
    return sum(values) / len(values) if values else default


def _write_live_status(
    status_json_path: Path,
    status_txt_path: Path,
    *,
    phase: str,
    args,
    start_ts: float,
    round_num: int,
    best_total: float,
    kept_count: int,
    minor_stagnant: int,
    n_workers: int,
    in_flight: int,
    completed_durations: list[float],
    last_completion_ts: float | None,
    latest_score: float | None,
    latest_marker: str | None,
) -> None:
    """Write machine+human readable live run status files."""
    now = time.monotonic()
    elapsed_s = now - start_ts
    avg_round_s = _safe_mean(completed_durations, default=0.0)
    remaining = max(0, args.rounds - round_num)
    eta_s = (avg_round_s * remaining / max(1, n_workers)) if avg_round_s > 0 else 0.0
    if last_completion_ts is None:
        idle_s = elapsed_s
    else:
        idle_s = now - last_completion_ts

    # Conservative stall heuristic: no completion for >3x avg worker time or 120s.
    idle_threshold_s = max(120.0, avg_round_s * 3.0)
    maybe_stuck = in_flight > 0 and idle_s > idle_threshold_s and round_num > 0
    progress_pct = (round_num / args.rounds * 100.0) if args.rounds > 0 else 100.0
    throughput = (round_num / elapsed_s * 60.0) if elapsed_s > 0 else 0.0

    payload = {
        "phase": phase,
        "round": round_num,
        "total_rounds": args.rounds,
        "progress_percent": round(progress_pct, 2),
        "workers": {
            "total": n_workers,
            "in_flight": in_flight,
            "idle": max(0, n_workers - in_flight),
        },
        "kept_count": kept_count,
        "best_score": round(best_total, 3),
        "latest_score": None if latest_score is None else round(latest_score, 3),
        "latest_marker": latest_marker,
        "minor_stagnant": minor_stagnant,
        "elapsed_s": round(elapsed_s, 1),
        "eta_s": round(eta_s, 1),
        "avg_round_s": round(avg_round_s, 2),
        "throughput_rounds_per_min": round(throughput, 2),
        "time_since_last_completion_s": round(idle_s, 1),
        "idle_threshold_s": round(idle_threshold_s, 1),
        "maybe_stuck": maybe_stuck,
        "timestamp_epoch_s": time.time(),
    }
    with open(status_json_path, "w") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")

    status_lines = [
        "=== Autoexperiment Live Status ===",
        f"phase: {phase}",
        f"progress: {round_num}/{args.rounds} ({progress_pct:.1f}%)",
        f"workers: total={n_workers} in_flight={in_flight} idle={max(0, n_workers - in_flight)}",
        f"best_score: {best_total:.2f}",
        f"latest_score: {'n/a' if latest_score is None else f'{latest_score:.2f}'}",
        f"latest_event: {latest_marker or 'n/a'}",
        f"kept_count: {kept_count}",
        f"minor_stagnant: {minor_stagnant}",
        f"elapsed: {_format_mmss(elapsed_s)}",
        f"eta: {_format_mmss(eta_s)}",
        f"avg_round: {avg_round_s:.1f}s",
        f"throughput: {throughput:.2f} rounds/min",
        f"time_since_last_completion: {_format_mmss(idle_s)}",
        f"idle_alert_threshold: {_format_mmss(idle_threshold_s)}",
        f"health: {'MAYBE STUCK (no completions recently)' if maybe_stuck else 'active'}",
    ]
    with open(status_txt_path, "w") as f:
        f.write("\n".join(status_lines) + "\n")


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
        "force_attract_k": (0.005, 0.15, 0.15),
        "force_repel_k":   (100.0, 500.0, 0.15),
        "cooling_factor":  (0.90, 0.995, 0.05),
        "edge_margin_mm":  (4.0, 10.0, 0.1),
        "placement_clearance_mm": (1.0, 3.0, 0.15),
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
        if isinstance(cfg.get(key), int):
            new_val = int(round(new_val))
        cfg[key] = round(new_val, 4)

    return cfg


def mutate_config_major(base: dict, rng: random.Random,
                        param_ranges: dict = None) -> dict:
    """Large structural change: new seed + aggressive param shifts.

    Uses uniform sampling across full parameter ranges (not Gaussian
    perturbation) to create genuinely different force dynamics.
    """
    cfg = mutate_config_minor(base, rng, param_ranges)

    # Sample fresh from full ranges — uniform, not Gaussian
    aggressive_tunable = {
        "force_attract_k": (0.005, 0.15),
        "force_repel_k":   (100.0, 500.0),
        "cooling_factor":  (0.90, 0.995),
        "placement_clearance_mm": (1.5, 5.0),
    }
    keys = rng.sample(list(aggressive_tunable.keys()),
                      rng.randint(1, len(aggressive_tunable)))
    for key in keys:
        lo, hi = aggressive_tunable[key]
        new_val = rng.uniform(lo, hi)
        cfg[key] = round(new_val, 4)

    # MAJOR mode: enable aggressive layout diversity
    cfg["randomize_group_layout"] = True
    cfg["reheat_strength"] = rng.uniform(0.05, 0.2)
    # 50% chance of random scatter (vs cluster-based)
    cfg["scatter_mode"] = "random" if rng.random() < 0.5 else "cluster"

    return cfg


def config_delta(base: dict, candidate: dict) -> dict:
    """Return only the keys that differ between base and candidate."""
    delta = {}
    for k in candidate:
        if k in base and candidate[k] != base[k]:
            delta[k] = candidate[k]
    return delta


def quick_drc(pcb_path: str) -> dict:
    """Run kicad-cli DRC and return violation counts + locations by category."""
    import re
    counts = {"shorts": 0, "unconnected": 0, "clearance": 0, "courtyard": 0, "total": 0}
    violations = []  # list of {type, description, x_mm, y_mm, net1, net2}
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

            # Parse location: "@(x_mm, y_mm)" pattern
            loc_m = re.search(r'@\(([\d.\-]+)\s*mm\s*,\s*([\d.\-]+)\s*mm\)', line)
            x_mm = float(loc_m.group(1)) if loc_m else None
            y_mm = float(loc_m.group(2)) if loc_m else None

            # Parse net names from the line
            net_matches = re.findall(r'\[Net\s+\d+\]\(([^)]+)\)', line)
            net1 = net_matches[0] if len(net_matches) > 0 else None
            net2 = net_matches[1] if len(net_matches) > 1 else None

            violation = {
                "type": vtype,
                "description": line.strip(),
                "x_mm": x_mm,
                "y_mm": y_mm,
                "net1": net1,
                "net2": net2,
            }
            violations.append(violation)

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
    counts["violations"] = violations
    return counts


def snapshot_pcb(pcb_path: str, output_png: str,
                  canvas_px: int = 900, board_mm: tuple = (140.0, 90.0),
                  frame_info: dict | None = None):
    """Export a fixed-scale PNG snapshot for progress GIF.

    Renders to a constant canvas (canvas_px square) with the board bbox
    sized to ~80% of the canvas — same scale every frame regardless of
    where components have moved. White opaque background for contrast
    and to prevent prior frames bleeding through GIF disposal.

    Args:
        frame_info: Optional dict with keys:
            - round_num: int
            - score: float
            - kept: bool
            - timestamp: float (wall clock time from time.monotonic())
            - drc_shorts: int (optional — if >0, frame gets red border & short markers)
            - drc_violations: list[dict] (optional — DRC violations with coordinates)
            - placement_score: float (optional — placement sub-score)
            - drc_score: float (optional — DRC sub-score)
            - route_pct: float (optional — route completion %)
            - via_score: float (optional — via penalty sub-score)
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

        # Build ImageMagick command for rendering + optional text overlay
        cmd = [
            "magick",
            "-density", "300",
            "-background", "white",
            svg_path,
            "-flatten",
            "-resize", f"{target_w}x{target_h}!",
            "-gravity", "center",
            "-extent", f"{canvas_px}x{canvas_px}",
        ]

        if frame_info:
            # Format timestamp as HH:MM:SS
            ts = frame_info.get("timestamp", 0)
            elapsed_s = ts
            hours = int(elapsed_s // 3600)
            mins = int((elapsed_s % 3600) // 60)
            secs = int(elapsed_s % 60)
            time_str = f"{hours:02d}:{mins:02d}:{secs:02d}"

            round_num = frame_info.get("round_num", 0)
            score = frame_info.get("score", 0)
            kept = frame_info.get("kept", False)
            drc_shorts = frame_info.get("drc_shorts", 0)

            # Border color: green=kept, red=shorts, gray=discarded
            if drc_shorts > 0:
                border_color = "#CC0000"
            elif kept:
                border_color = "#00CC00"
            else:
                border_color = "#888888"

            status_color = "#00CC00" if kept else "#CC0000"
            status_text = "KEPT" if kept else "DISCARDED"

            info_line = f"R{round_num:03d} | {time_str} | Score: {score:.1f} | {status_text}"
            if drc_shorts > 0:
                info_line += f" | SHORTS: {drc_shorts}"
            font_size = max(18, canvas_px // 45)

            # Draw colored border (3px)
            cmd.extend([
                "-bordercolor", border_color, "-border", "3",
            ])

            # Draw DRC violation markers on the board image (all types)
            drc_violations = frame_info.get("drc_violations", [])
            if drc_violations:
                # Board origin offset (centered in canvas + 3px border)
                ox = (canvas_px - target_w) / 2 + 3
                oy = (canvas_px - target_h) / 2 + 3
                board_x0, board_y0 = _parse_board_origin_from_pcb(pcb_path)

                for v in drc_violations:
                    if v.get("x_mm") is None:
                        continue
                    px = ox + (v["x_mm"] - board_x0) * scale
                    py = oy + (v["y_mm"] - board_y0) * scale
                    r = max(6, int(scale * 1.2))
                    vtype = v.get("type", "")

                    if vtype == "shorting_items":
                        # Red X for shorts
                        cmd.extend([
                            "-fill", "none", "-stroke", "#E63946", "-strokewidth", "2",
                            "-draw", f"line {px-r},{py-r} {px+r},{py+r}",
                            "-draw", f"line {px-r},{py+r} {px+r},{py-r}",
                        ])
                    elif vtype == "unconnected_items":
                        # Orange circle for unconnected
                        cmd.extend([
                            "-fill", "none", "-stroke", "#FFA500", "-strokewidth", "1.5",
                            "-draw", f"circle {px},{py} {px+r*0.7},{py}",
                        ])
                    elif vtype in ("clearance", "hole_clearance", "copper_edge_clearance"):
                        # Yellow dot for clearance violations
                        cmd.extend([
                            "-fill", "rgba(255,255,0,0.5)", "-stroke", "none",
                            "-draw", f"circle {px},{py} {px+r*0.5},{py}",
                        ])
                    elif vtype == "courtyards_overlap":
                        # Magenta rectangle for courtyard overlaps
                        cmd.extend([
                            "-fill", "none", "-stroke", "#FF00FF", "-strokewidth", "1.5",
                            "-draw", f"rectangle {px-r},{py-r} {px+r},{py+r}",
                        ])

            # Draw semi-transparent black background band at bottom (85% opaque)
            # Account for border offset
            total_w = canvas_px + 6  # 3px border each side
            total_h = canvas_px + 6
            band_height = font_size + 16

            # Sub-score breakdown line (smaller text below main info)
            p_score = frame_info.get("placement_score", 0)
            d_score = frame_info.get("drc_score", 0)
            r_pct = frame_info.get("route_pct", 0)
            v_score = frame_info.get("via_score", 0)
            has_subscores = any([p_score, d_score, r_pct, v_score])
            if has_subscores:
                sub_font = max(12, font_size - 4)
                band_height = font_size + sub_font + 22
                sub_line = f"DRC:{d_score:.0f} | Place:{p_score:.0f} | Route:{r_pct:.0f} | Via:{v_score:.0f}"

            cmd.extend([
                "-fill", "rgba(0,0,0,0.85)",
                "-draw", f"rectangle 0,{total_h-band_height} {total_w} {total_h}",
                "-fill", status_color,
                "-gravity", "SouthWest",
                "-pointsize", str(font_size),
                "-font", "DejaVu-Sans-Bold",
                "-annotate", f"+{font_size//2}+{font_size//2+2}",
                info_line,
            ])
            if has_subscores:
                cmd.extend([
                    "-fill", "#AAAAAA",
                    "-gravity", "SouthWest",
                    "-pointsize", str(sub_font),
                    "-font", "DejaVu-Sans",
                    "-annotate", f"+{font_size//2}+{font_size + sub_font//2 + 6}",
                    sub_line,
                ])

        else:
            # Original border only
            cmd.extend([
                "-bordercolor", "#222", "-border", "3",
            ])

        cmd.append(output_png)

        subprocess.run(cmd, capture_output=True, check=True)
        os.remove(svg_path)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass  # non-fatal — skip snapshot if tools missing


def _parse_board_origin_from_pcb(pcb_path: str) -> tuple[float, float]:
    """Parse board outline origin from .kicad_pcb file."""
    try:
        with open(pcb_path) as f:
            text = f.read()
        m = re.search(r'\(gr_rect\s+\(start\s+([\d.\-]+)\s+([\d.\-]+)\)', text)
        if m:
            return float(m.group(1)), float(m.group(2))
    except OSError:
        pass
    return 0.0, 0.0


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


def _suppress_output():
    """Redirect fd 1+2 to /dev/null. Returns (saved_out_fd, saved_err_fd, old_stdout, old_stderr)."""
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    saved_out = os.dup(1)
    saved_err = os.dup(2)
    os.dup2(devnull_fd, 1)
    os.dup2(devnull_fd, 2)
    os.close(devnull_fd)
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = open(os.devnull, 'w')
    sys.stderr = open(os.devnull, 'w')
    return saved_out, saved_err, old_stdout, old_stderr


def _restore_output(saved_out, saved_err, old_stdout, old_stderr):
    """Restore fd 1+2 and Python streams."""
    sys.stdout.close()
    sys.stderr.close()
    sys.stdout, sys.stderr = old_stdout, old_stderr
    os.dup2(saved_out, 1)
    os.dup2(saved_err, 2)
    os.close(saved_out)
    os.close(saved_err)


def _worker_run(args: tuple) -> tuple[ExperimentScore, float, str]:
    """Top-level picklable worker for ProcessPoolExecutor.

    Each parallel experiment runs in its own process with its own work_pcb
    path so there are no file conflicts between concurrent workers.
    Returns (ExperimentScore, duration_seconds, work_pcb_path).
    """
    pcb_src, work_pcb, cfg, seed, score_weights, script_dir = args

    # Ensure autoplacer is importable (needed when using spawn context)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    shutil.copy2(pcb_src, work_pcb)
    saved = _suppress_output()
    t0 = time.monotonic()
    worker_log = None
    try:
        from autoplacer.pipeline import FullPipeline
        from autoplacer.brain.types import ExperimentScore as ES
        
        # Try to get logger in worker (may not have logging_config in worker process)
        try:
            import logging_config as lc
            lc.configure_logging("INFO", str(Path(pcb_src).parent / ".experiments"))
            worker_log = lc.get_logger("worker")
        except ImportError:
            pass
        
        pipeline = FullPipeline()
        result = pipeline.run(work_pcb, work_pcb, config=cfg, seed=seed)
        exp_score = result["experiment_score"]
        if score_weights:
            exp_score.compute(score_weights)
    except Exception as e:
        import traceback
        from autoplacer.brain.types import ExperimentScore as ES
        exp_score = ES()
        exp_score.total = -1.0
        # Capture traceback so failures are diagnosable
        exp_score._error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        if worker_log:
            worker_log.error("worker_failed", error=str(e), error_type=type(e).__name__)
    finally:
        duration = time.monotonic() - t0
        _restore_output(*saved)

    return exp_score, duration, work_pcb


def run_experiment(pcb_path: str, work_pcb: str, cfg: dict,
                   seed: int, quiet: bool = True) -> tuple[ExperimentScore, float]:
    """Run one full pipeline experiment in-process. Returns (score, duration_seconds)."""
    shutil.copy2(pcb_path, work_pcb)

    if quiet:
        saved = _suppress_output()

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
            _restore_output(*saved)

    return exp_score, duration


def _apply_shorts_penalty(score: ExperimentScore, shorts: int) -> None:
    """Apply additive shorts penalty in-place.

    Deducts up to 15 points (out of ~100 max) so the routing-completion
    signal is preserved even when shorts are present.
    """
    if shorts > 0:
        penalty = min(15.0, shorts * 0.5)
        score.total = max(0.0, score.total - penalty)


def _json_default(obj):
    """JSON serializer for objects not serializable by default."""
    if isinstance(obj, set):
        return sorted(obj)
    raise TypeError(f'Object of type {type(obj).__name__} is not JSON serializable')


def save_elite_config(work_dir: Path, best_cfg: dict, best_seed: int,
                      best_score: float) -> None:
    """Persist best config to checkpoint file for cross-run learning."""
    checkpoint = {
        "version": 1,
        "timestamp": time.time(),
        "best_cfg": best_cfg,
        "best_seed": best_seed,
        "best_score": best_score,
    }
    checkpoint_path = work_dir / "best_config.json"
    with open(checkpoint_path, "w") as f:
        json.dump(checkpoint, f, indent=2, default=_json_default)


def load_elite_config(work_dir: Path) -> tuple[dict, int, float] | None:
    """Load best config from checkpoint file if it exists."""
    checkpoint_path = work_dir / "best_config.json"
    if not checkpoint_path.exists():
        return None
    try:
        with open(checkpoint_path) as f:
            checkpoint = json.load(f)
        return (checkpoint["best_cfg"], checkpoint["best_seed"],
                checkpoint["best_score"])
    except (json.JSONDecodeError, KeyError):
        return None


def save_elite_archive(work_dir: Path, cfg: dict, seed: int, score: float,
                       max_elites: int = 5) -> None:
    """Append to top-N elite config archive for cross-run learning."""
    archive_path = work_dir / "elite_configs.json"
    archive = []
    if archive_path.exists():
        try:
            with open(archive_path) as f:
                archive = json.load(f)
        except (json.JSONDecodeError, ValueError):
            archive = []

    entry = {"score": score, "seed": seed, "config": cfg,
             "timestamp": time.time()}
    archive.append(entry)
    # Keep only top-N by score (deduplicated by seed)
    seen_seeds = set()
    unique = []
    for e in sorted(archive, key=lambda x: x["score"], reverse=True):
        if e["seed"] not in seen_seeds:
            seen_seeds.add(e["seed"])
            unique.append(e)
    archive = unique[:max_elites]

    with open(archive_path, "w") as f:
        json.dump(archive, f, indent=2, default=_json_default)


def load_elite_archive(work_dir: Path) -> list[dict]:
    """Load elite config archive for seeding new runs."""
    archive_path = work_dir / "elite_configs.json"
    if not archive_path.exists():
        return []
    try:
        with open(archive_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return []


def _log_and_record(exp: Experiment, experiments: list, log_path: Path) -> None:
    experiments.append(exp)
    with open(log_path, 'a') as f:
        f.write(json.dumps(asdict(exp), default=str) + '\n')


def _generate_html_report(report_script: Path, work_dir: Path, output_path: Path,
                          *, live: bool, refresh_seconds: int = 5,
                          quiet: bool = False) -> bool:
    """Generate an HTML report from the current experiment state."""
    if not report_script.exists():
        return False

    cmd = [
        "python3",
        str(report_script),
        str(work_dir),
        "--output",
        str(output_path),
    ]
    if live:
        cmd.extend(["--live", "--refresh-seconds", str(refresh_seconds)])

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        if not quiet:
            print(f"  Report saved: {output_path}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  Report generation failed: {e.stderr.decode()}",
              file=sys.stderr)
        return False


def _write_round_detail(
    rounds_dir: Path,
    round_num: int,
    score: ExperimentScore,
    config_used: dict,
    drc: dict,
    duration_s: float,
    kept: bool,
    mode: str,
    seed: int,
    net_failure_rates: dict[str, float] | None = None,
) -> None:
    """Write detailed per-round JSON with full routing/RRR/DRC data."""
    detail = {
        "round": round_num,
        "mode": mode,
        "seed": seed,
        "kept": kept,
        "score": round(score.total, 3),
        "duration_s": round(duration_s, 1),
        "config": config_used,
        "timing": {
            "placement_ms": round(score.placement_ms, 1),
            "routing_ms": round(score.routing_ms, 1),
        },
        "routing": {
            "routed": score.routed_nets,
            "total": score.total_nets,
            "failed": score.failed_nets,
            "failed_nets": score.failed_net_names,
            "traces": score.trace_count,
            "vias": score.via_count,
            "total_length_mm": round(score.total_trace_length_mm, 1),
        },
        "drc": {
            "shorts": drc.get("shorts", 0),
            "unconnected": drc.get("unconnected", 0),
            "clearance": drc.get("clearance", 0),
            "courtyard": drc.get("courtyard", 0),
            "total": drc.get("total", 0),
            "violations": drc.get("violations", []),
        },
        "placement": {
            "total": round(score.placement.total, 2),
            "net_distance": round(score.placement.net_distance, 2),
            "crossover_count": score.placement.crossover_count,
            "crossover_score": round(score.placement.crossover_score, 2),
            "compactness": round(score.placement.compactness, 2),
            "edge_compliance": round(score.placement.edge_compliance, 2),
            "board_containment": round(score.placement.board_containment, 2),
            "courtyard_overlap": round(score.placement.courtyard_overlap, 2),
        },
    }
    if net_failure_rates:
        detail["net_failure_rates"] = net_failure_rates
    out_path = rounds_dir / f"round_{round_num:04d}.json"
    with open(out_path, 'w') as f:
        json.dump(detail, f, indent=2, default=str)
        f.write('\n')


def _score_sub_fields(score: ExperimentScore) -> tuple[float, float, float]:
    """Return (route_pct, trace_eff, via_sc) for logging."""
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
    return route_pct, trace_eff, via_sc


def main():
    parser = argparse.ArgumentParser(
        description="Autonomous PCB layout experiment loop")
    parser.add_argument("pcb", help="Input .kicad_pcb file")
    parser.add_argument("--rounds", "-n", type=int, default=50,
                        help="Max experiment rounds (default: 50)")
    parser.add_argument("--workers", "-w", type=int, default=0,
                        help="Parallel workers (0=auto: cpu_count//2)")
    parser.add_argument("--batch-seeds", "-b", type=int, default=1,
                        help="Parallel seeds per round for exploration (default: 1)")
    parser.add_argument("--program", "-p", default="program.md",
                        help="Path to program.md search space definition")
    parser.add_argument("--output", "-o",
                        help="Output best .kicad_pcb (default: <input>_best.kicad_pcb)")
    parser.add_argument("--log", "-l", default="experiments.jsonl",
                        help="Experiment log file (JSONL)")
    parser.add_argument("--plateau", type=int, default=3,
                        help="Minor rounds without improvement before MAJOR (default: 3)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Master RNG seed (default: random)")
    parser.add_argument("--quiet", "-q", action="store_true", default=True,
                        help="Suppress pipeline output (default: on)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show pipeline output")
    parser.add_argument("--status-file", default="run_status.json",
                        help="Live run status JSON filename inside .experiments/")
    parser.add_argument("--log-level", default="INFO", choices=["INFO", "DEBUG"],
                        help="Logging level (default: INFO)")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from best config checkpoint if available")
    args = parser.parse_args()

    if args.verbose:
        args.quiet = False

    # Worker count: auto = all logical cores (no cap), user can override with --workers
    n_workers = args.workers or mp.cpu_count()

    # Setup
    master_seed = args.seed if args.seed is not None else random.randint(0, 2**31)
    rng = random.Random(master_seed)
    program = load_program(args.program)
    param_ranges = program.get("param_ranges", {})
    score_weights = program.get("score_weights", None)
    net_priority = program.get("net_priority", {})

    work_dir = Path(args.pcb).parent / ".experiments"
    work_dir.mkdir(exist_ok=True)
    
    # Initialize logging after work_dir is set
    global log
    if LOGGING_AVAILABLE:
        logging_config.configure_logging(args.log_level, str(work_dir))
        log = logging_config.get_logger("autoexperiment")
        log.info("experiment_started",
               pcb=args.pcb,
               rounds=args.rounds,
               workers=n_workers,
               seed=master_seed,
               log_level=args.log_level)
    
    best_dir = work_dir / "best"
    best_dir.mkdir(exist_ok=True)
    rounds_dir = work_dir / "rounds"
    rounds_dir.mkdir(exist_ok=True)
    frames_dir = work_dir / "frames"
    # Clear any frames from previous runs so the GIF doesn't include stale data
    if frames_dir.exists():
        import glob as _glob
        for f in _glob.glob(str(frames_dir / "frame_*.png")):
            os.remove(f)
    frames_dir.mkdir(exist_ok=True)

    # Per-worker scratch directories (avoid file conflicts in parallel mode)
    workers_dir = work_dir / "workers"
    workers_dir.mkdir(exist_ok=True)
    for i in range(n_workers):
        (workers_dir / f"w{i}").mkdir(exist_ok=True)
    # Baseline uses w0
    baseline_pcb = str(workers_dir / "w0" / "experiment.kicad_pcb")

    output_path = args.output or str(Path(args.pcb).with_suffix('')) + "_best.kicad_pcb"
    log_path = work_dir / args.log
    status_json_path = work_dir / args.status_file
    status_txt_path = work_dir / "run_status.txt"
    report_script = Path(__file__).parent / "generate_report.py"
    report_path = work_dir / "report.html"
    live_report_paths = [report_path, Path(args.pcb).parent / "report.html"]

    # Purge old log file so each run starts fresh
    if log_path.exists():
        log_path.unlink()

    # Also purge old dashboard and GIF from previous runs
    dashboard_path = work_dir / "experiments_dashboard.png"
    if dashboard_path.exists():
        dashboard_path.unlink()
    gif_path = work_dir / "progress.gif"
    if gif_path.exists():
        gif_path.unlink()
    if status_json_path.exists():
        status_json_path.unlink()
    if status_txt_path.exists():
        status_txt_path.unlink()

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

    # Start timing for GIF timestamps (before baseline run)
    loop_t0 = time.monotonic()

    print(f"=== Autonomous PCB Experiment Loop ===")
    print(f"PCB:         {args.pcb}")
    print(f"Rounds:      {args.rounds}")
    print(f"Workers:     {n_workers} parallel")
    print(f"Master seed: {master_seed}")
    print(f"Plateau:     {args.plateau} minor rounds -> MAJOR")
    print(f"Log:         {log_path}")
    print(f"Output:      {output_path}")
    print()

    # Merge project-specific overrides with engine defaults.
    # LLUPS_CONFIG is the current project; future: load from --project-config flag.
    BASE_CONFIG = {**DEFAULT_CONFIG, **LLUPS_CONFIG}

    # Run baseline or resume from checkpoint
    best_cfg = dict(BASE_CONFIG)
    if net_priority:
        best_cfg["net_priority"] = net_priority
    best_seed = 0
    best_total = None

    if args.resume:
        loaded = load_elite_config(work_dir)
        if loaded:
            best_cfg, best_seed, loaded_score = loaded
            if net_priority:
                best_cfg["net_priority"] = net_priority
            best_total = loaded_score
            print(f"Resumed from checkpoint: score={loaded_score:.2f}, seed={best_seed}")

    if best_total is None:
        print("Round   0/-- [BASE ] running baseline...", flush=True)
        best_score, base_dur = run_experiment(
            args.pcb, baseline_pcb, best_cfg, best_seed, quiet=args.quiet)
        base_drc = quick_drc(baseline_pcb)
        if score_weights:
            best_score.compute(score_weights, drc_dict=base_drc)
        else:
            best_score.compute(drc_dict=base_drc)

        print(f"  -> baseline score={best_score.total:6.2f} shorts={base_drc['shorts']} "
              f"drc={base_drc['total']} ({base_dur:.1f}s)", flush=True)

        shutil.copy2(baseline_pcb, str(best_dir / "best.kicad_pcb"))
        best_total = best_score.total
    else:
        base_drc = {"shorts": 0, "unconnected": 0, "clearance": 0, "courtyard": 0, "total": 0}
        base_dur = 0.0
        best_score = ExperimentScore()
        best_score.total = best_total

    _log_event("baseline_complete",
               score=best_score.total,
               shorts=base_drc["shorts"],
               drc=base_drc["total"],
               duration_s=base_dur)

    # Capture baseline frame for GIF
    baseline_elapsed = time.monotonic() - loop_t0
    snapshot_pcb(baseline_pcb, str(frames_dir / "frame_0000.png"),
                 board_mm=board_mm,
                 frame_info={"round_num": 0, "score": best_score.total,
                             "kept": False, "timestamp": baseline_elapsed})

    experiments: list[Experiment] = []
    minor_stagnant = 0
    kept_count = 0
    round_num = 0
    net_fail_counts: dict[str, int] = {}
    completed_durations: list[float] = [base_dur]
    last_completion_ts: float | None = time.monotonic()

    _write_live_status(
        status_json_path,
        status_txt_path,
        phase="running",
        args=args,
        start_ts=loop_t0,
        round_num=0,
        best_total=best_total,
        kept_count=kept_count,
        minor_stagnant=minor_stagnant,
        n_workers=n_workers,
        in_flight=0,
        completed_durations=completed_durations,
        last_completion_ts=last_completion_ts,
        latest_score=best_total,
        latest_marker="baseline complete",
    )

    # Seed from elite archive (cross-run learning)
    elite_archive = load_elite_archive(work_dir)
    elite_cfgs = []
    for entry in elite_archive:
        ecfg = dict(BASE_CONFIG)
        ecfg.update(entry.get("config", {}))
        elite_cfgs.append(ecfg)
    if elite_cfgs:
        _log_event("elite_archive_loaded", n_elites=len(elite_cfgs))

    # Use spawn context: each worker starts a clean Python process.
    # fork deadlocks because wx holds mutexes at fork time that children can't release.
    ctx = mp.get_context("spawn")

    with ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx) as pool:
        while round_num < args.rounds:
            # Check for graceful stop request
            if _check_stop_request(work_dir):
                _log_event("stop_requested", round_num=round_num)
                stop_file = work_dir / "stop.now"
                if stop_file.exists():
                    stop_file.unlink()
                break
            
            batch_size = min(n_workers, args.rounds - round_num, max(args.plateau, 1))
            batch_seeds = args.batch_seeds

            # Generate batch of candidates
            # batch_seeds > 1: 1 from best_cfg (exploit), rest from baseline (explore)
            batch: list[tuple[str, dict, int, dict]] = []  # (mode, cfg, seed, delta)
            
            # First candidate: exploit (mutate from best)
            if minor_stagnant >= args.plateau:
                mode = "major"
                minor_stagnant = 0
            else:
                mode = "minor"
            exp_seed = rng.randint(0, 2**31)
            if mode == "minor":
                candidate_cfg = mutate_config_minor(best_cfg, rng, param_ranges)
                candidate_seed = best_seed
            else:
                candidate_cfg = mutate_config_major(best_cfg, rng, param_ranges)
                candidate_seed = exp_seed
            delta = config_delta(BASE_CONFIG, candidate_cfg)
            batch.append((mode, candidate_cfg, candidate_seed, delta))
            
            # Additional seeds: explore from baseline
            for _ in range(1, min(batch_seeds, batch_size)):
                explore_seed = rng.randint(0, 2**31)
                explore_cfg = mutate_config_major(dict(BASE_CONFIG), rng, param_ranges)
                explore_cfg["scatter_mode"] = "random"  # explore always scatters
                explore_cfg["randomize_group_layout"] = True
                if net_priority:
                    explore_cfg["net_priority"] = net_priority
                explore_delta = config_delta(BASE_CONFIG, explore_cfg)
                batch.append(("explore", explore_cfg, explore_seed, explore_delta))

            # Fill remaining slots if batch_seeds < batch_size
            while len(batch) < batch_size:
                if minor_stagnant >= args.plateau:
                    mode = "major"
                    minor_stagnant = 0
                else:
                    mode = "minor"
                exp_seed = rng.randint(0, 2**31)
                if mode == "minor":
                    candidate_cfg = mutate_config_minor(best_cfg, rng, param_ranges)
                    candidate_seed = best_seed
                else:
                    candidate_cfg = mutate_config_major(best_cfg, rng, param_ranges)
                    candidate_seed = exp_seed
                delta = config_delta(BASE_CONFIG, candidate_cfg)
                batch.append((mode, candidate_cfg, candidate_seed, delta))

            # Reserve ~33% of batch for pure exploration (random config + seed)
            n_explore = max(1, batch_size // 3)
            # In early rounds, seed some explore slots from elite archive
            n_elite_inject = 0
            if elite_cfgs and round_num < 10:
                n_elite_inject = min(len(elite_cfgs), n_explore)
            for i in range(min(n_explore, len(batch))):
                idx = len(batch) - 1 - i  # replace from end
                if i < n_elite_inject:
                    # Use elite config with fresh seed
                    elite_cfg = dict(elite_cfgs[i % len(elite_cfgs)])
                    elite_seed = rng.randint(0, 2**31)
                    if net_priority:
                        elite_cfg["net_priority"] = net_priority
                    elite_delta = config_delta(BASE_CONFIG, elite_cfg)
                    batch[idx] = ("elite", elite_cfg, elite_seed, elite_delta)
                else:
                    explore_seed = rng.randint(0, 2**31)
                    explore_cfg = mutate_config_major(dict(BASE_CONFIG), rng, param_ranges)
                    explore_cfg["scatter_mode"] = "random"  # explore always scatters
                    explore_cfg["randomize_group_layout"] = True
                    if net_priority:
                        explore_cfg["net_priority"] = net_priority
                    explore_delta = config_delta(BASE_CONFIG, explore_cfg)
                    batch[idx] = ("explore", explore_cfg, explore_seed, explore_delta)

            if n_workers == 1:
                # Single-worker: run in-process (no subprocess overhead)
                mode, candidate_cfg, candidate_seed, delta = batch[0]
                work_pcb = str(workers_dir / "w0" / "experiment.kicad_pcb")
                delta_str = " ".join(f"{k}={v}" for k, v in delta.items()) or "(no delta)"
                round_num += 1
                t_label = f"Round {round_num:3d}/{args.rounds} [{mode[:5].upper():5s}]"
                print(f"{t_label} running... {delta_str[:80]}", flush=True)
                _write_live_status(
                    status_json_path,
                    status_txt_path,
                    phase="running",
                    args=args,
                    start_ts=loop_t0,
                    round_num=round_num,
                    best_total=best_total,
                    kept_count=kept_count,
                    minor_stagnant=minor_stagnant,
                    n_workers=n_workers,
                    in_flight=1,
                    completed_durations=completed_durations,
                    last_completion_ts=last_completion_ts,
                    latest_score=None,
                    latest_marker=f"round {round_num} started ({mode})",
                )
                score, duration = run_experiment(
                    args.pcb, work_pcb, candidate_cfg, candidate_seed,
                    quiet=args.quiet)
                drc = quick_drc(work_pcb)
                if score_weights:
                    score.compute(score_weights, drc_dict=drc)
                else:
                    score.compute(drc_dict=drc)
                results = [(score, duration, work_pcb, drc, mode, candidate_cfg,
                            candidate_seed, delta)]
            else:
                # Multi-worker: submit batch, announce, collect
                delta_strs = [
                    " ".join(f"{k}={v}" for k, v in d.items()) or "(no delta)"
                    for _, _, _, d in batch
                ]
                for i, (mode, _, _, delta) in enumerate(batch):
                    print(f"  W{i} [{mode[:5].upper():5s}] {delta_strs[i][:60]}",
                          flush=True)

                worker_args = [
                    (args.pcb,
                     str(workers_dir / f"w{i}" / "experiment.kicad_pcb"),
                     cfg, seed, score_weights, _SCRIPT_DIR)
                    for i, (_, cfg, seed, _) in enumerate(batch)
                ]
                futures = {
                    pool.submit(_worker_run, wa): i
                    for i, wa in enumerate(worker_args)
                }
                _write_live_status(
                    status_json_path,
                    status_txt_path,
                    phase="running",
                    args=args,
                    start_ts=loop_t0,
                    round_num=round_num,
                    best_total=best_total,
                    kept_count=kept_count,
                    minor_stagnant=minor_stagnant,
                    n_workers=n_workers,
                    in_flight=len(futures),
                    completed_durations=completed_durations,
                    last_completion_ts=last_completion_ts,
                    latest_score=None,
                    latest_marker=f"submitted batch of {len(futures)} workers",
                )

                results = []
                for future in as_completed(futures):
                    i = futures[future]
                    mode, candidate_cfg, candidate_seed, delta = batch[i]
                    work_pcb = str(workers_dir / f"w{i}" / "experiment.kicad_pcb")
                    try:
                        score, duration, _ = future.result()
                    except Exception as e:
                        print(f"  Worker {i} exception: {e}", flush=True)
                        score = ExperimentScore()
                        score.total = -1.0
                        duration = 0.0
                    drc = quick_drc(work_pcb)
                    if score.total == -1.0:
                        err_msg = getattr(score, '_error', 'unknown error')
                        print(f"  Worker {i} CRASHED: {err_msg[:200]}", flush=True)
                    if score_weights:
                        score.compute(score_weights, drc_dict=drc)
                    else:
                        score.compute(drc_dict=drc)
                    results.append((score, duration, work_pcb, drc, mode,
                                    candidate_cfg, candidate_seed, delta))

            # Process all results from this batch
            remaining_in_batch = len(results)
            for (score, duration, work_pcb, drc, mode,
                 candidate_cfg, candidate_seed, delta) in results:
                round_num_local = round_num if n_workers == 1 else (round_num + 1)
                if n_workers > 1:
                    round_num += 1

                kept = score.total > best_total
                if kept:
                    improvement = score.total - best_total
                    best_total = score.total
                    best_cfg = candidate_cfg
                    best_seed = candidate_seed
                    best_score = score
                    minor_stagnant = 0
                    kept_count += 1
                    shutil.copy2(work_pcb, str(best_dir / "best.kicad_pcb"))
                    save_elite_config(work_dir, best_cfg, best_seed, best_total)
                    save_elite_archive(work_dir, best_cfg, best_seed, best_total)
                    marker = f"NEW BEST +{improvement:.2f}"
                    _log_event("new_best",
                               round_num=round_num,
                               score=score.total,
                               improvement=improvement,
                               shorts=drc["shorts"])
                else:
                    minor_stagnant += 1
                    marker = f"discard (stagnant={minor_stagnant})"
                    _log_event("round_discarded",
                               round_num=round_num,
                               score=score.total,
                               stagnant_rounds=minor_stagnant)

                elapsed = time.monotonic() - loop_t0
                avg_round = elapsed / max(round_num, 1)
                eta_s = avg_round * (args.rounds - round_num)
                eta_str = f"{int(eta_s // 60)}m{int(eta_s % 60):02d}s"
                print(f"  -> score={score.total:6.2f} best={best_total:6.2f} "
                      f"shorts={drc['shorts']:3d} drc={drc['total']:4d} "
                      f"({duration:.1f}s) [{marker}]", flush=True)
                print(f"     [progress {round_num}/{args.rounds}  kept={kept_count}  "
                      f"elapsed={int(elapsed//60)}m{int(elapsed%60):02d}s  "
                      f"ETA={eta_str}]", flush=True)

                route_pct, trace_eff, via_sc = _score_sub_fields(score)
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
                    placement_ms=round(score.placement_ms, 1),
                    routing_ms=round(score.routing_ms, 1),
                    nets_routed=score.routed_nets,
                    failed_net_names=score.failed_net_names,
                )
                # Track per-net failure rates
                for net_name in score.failed_net_names:
                    net_fail_counts[net_name] = net_fail_counts.get(net_name, 0) + 1
                _log_and_record(exp, experiments, log_path)
                # Compute running failure rates for observability
                _net_failure_rates = (
                    {name: round(count / round_num, 3)
                     for name, count in net_fail_counts.items()}
                    if round_num > 0 else {}
                )
                _write_round_detail(
                    rounds_dir, round_num, score, candidate_cfg,
                    drc, duration, kept, mode, candidate_seed,
                    net_failure_rates=_net_failure_rates,
                )
                completed_durations.append(duration)
                last_completion_ts = time.monotonic()
                remaining_in_batch = max(0, remaining_in_batch - 1)
                in_flight = 0 if n_workers == 1 else remaining_in_batch
                _write_live_status(
                    status_json_path,
                    status_txt_path,
                    phase="running",
                    args=args,
                    start_ts=loop_t0,
                    round_num=round_num,
                    best_total=best_total,
                    kept_count=kept_count,
                    minor_stagnant=minor_stagnant,
                    n_workers=n_workers,
                    in_flight=in_flight,
                    completed_durations=completed_durations,
                    last_completion_ts=last_completion_ts,
                    latest_score=score.total,
                    latest_marker=marker,
                )

                frame_elapsed = time.monotonic() - loop_t0
                frame_png = str(frames_dir / f"frame_{round_num:04d}.png")
                # Snapshot the current round's layout (not just the best),
                # so the GIF shows what each round actually tried.
                frame_pcb = work_pcb if os.path.exists(work_pcb) else str(best_dir / "best.kicad_pcb")
                snapshot_pcb(frame_pcb, frame_png,
                             board_mm=board_mm,
                             frame_info={"round_num": round_num, "score": score.total,
                                         "kept": kept, "timestamp": frame_elapsed,
                                         "drc_shorts": drc["shorts"],
                                         "drc_violations": drc.get("violations", []),
                                         "placement_score": score.placement.total,
                                         "drc_score": score.drc_score.total,
                                         "route_pct": route_pct,
                                         "via_score": via_sc})
                seen_report_paths: set[Path] = set()
                for live_report_path in live_report_paths:
                    if live_report_path in seen_report_paths:
                        continue
                    seen_report_paths.add(live_report_path)
                    _generate_html_report(
                        report_script,
                        work_dir,
                        live_report_path,
                        live=True,
                        refresh_seconds=5,
                        quiet=True,
                    )

    # Assemble progress GIF from frames
    gif_path = str(work_dir / "progress.gif")
    assemble_gif(frames_dir, gif_path)

    # Regenerate dashboard PNG from the full experiments.jsonl history
    dashboard_path = work_dir / "experiments_dashboard.png"
    plot_script = Path(__file__).parent / "plot_experiments.py"
    if plot_script.exists():
        try:
            subprocess.run(
                ["python3", str(plot_script), str(log_path), str(dashboard_path)],
                check=True, capture_output=True,
            )
            print(f"  Dashboard saved: {dashboard_path}")
        except subprocess.CalledProcessError as e:
            print(f"  Dashboard regeneration failed: {e.stderr.decode()}",
                  file=sys.stderr)

    # Copy best result to output
    best_pcb = str(best_dir / "best.kicad_pcb")
    if os.path.exists(best_pcb):
        shutil.copy2(best_pcb, output_path)

    print()
    print(f"=== Done: {len(experiments)} experiments ===")
    print(f"Best score: {best_score.summary()}")
    print(f"Best config delta from default: "
          f"{json.dumps(config_delta(BASE_CONFIG, best_cfg), indent=2)}")
    print(f"Best seed: {best_seed}")
    print(f"Output: {output_path}")
    print(f"Log:    {log_path}")
    _write_live_status(
        status_json_path,
        status_txt_path,
        phase="done",
        args=args,
        start_ts=loop_t0,
        round_num=round_num,
        best_total=best_total,
        kept_count=kept_count,
        minor_stagnant=minor_stagnant,
        n_workers=n_workers,
        in_flight=0,
        completed_durations=completed_durations,
        last_completion_ts=last_completion_ts,
        latest_score=best_total,
        latest_marker="run complete",
    )

    if _generate_html_report(report_script, work_dir, report_path, live=False):
        for live_report_path in live_report_paths:
            if live_report_path == report_path:
                continue
            shutil.copy2(report_path, live_report_path)
            print(f"  Report copy:  {live_report_path}")

    _log_event("experiment_completed",
               total_rounds=len(experiments),
               best_score=best_total,
               kept_count=kept_count,
               total_elapsed_s=time.monotonic() - loop_t0)


if __name__ == "__main__":
    main()
