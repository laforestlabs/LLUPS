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
import json
import os
import random
import shutil
import sys
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
        "force_attract_k": (0.01, 0.5, 0.15),
        "force_repel_k":   (5.0, 200.0, 0.15),
        "cooling_factor":  (0.90, 0.995, 0.05),
        "edge_margin_mm":  (1.0, 5.0, 0.1),
        "clearance_mm":    (0.15, 1.0, 0.1),
        "existing_trace_cost": (1.0, 50.0, 0.2),
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
        "force_attract_k": (0.01, 0.5, 0.4),
        "force_repel_k":   (5.0, 200.0, 0.4),
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


def run_experiment(pcb_path: str, work_dir: Path, cfg: dict,
                   seed: int, quiet: bool = True) -> tuple[ExperimentScore, float]:
    """Run one full pipeline experiment. Returns (score, duration_seconds)."""
    # Work on a copy so we don't corrupt the original
    work_pcb = str(work_dir / "experiment.kicad_pcb")
    shutil.copy2(pcb_path, work_pcb)

    # Suppress stdout during experiment if quiet
    if quiet:
        old_stdout = sys.stdout
        sys.stdout = open(os.devnull, 'w')

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
            sys.stdout = old_stdout

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

    output_path = args.output or str(Path(args.pcb).with_suffix('')) + "_best.kicad_pcb"
    log_path = work_dir / args.log

    print(f"=== Autonomous PCB Experiment Loop ===")
    print(f"PCB:         {args.pcb}")
    print(f"Rounds:      {args.rounds}")
    print(f"Master seed: {master_seed}")
    print(f"Plateau:     {args.plateau} minor rounds -> MAJOR")
    print(f"Log:         {log_path}")
    print(f"Output:      {output_path}")
    print()

    # Run baseline
    print("Round 0: baseline...")
    best_cfg = dict(DEFAULT_CONFIG)
    best_seed = 0
    best_score, base_dur = run_experiment(
        args.pcb, work_dir, best_cfg, best_seed, quiet=args.quiet)
    if score_weights:
        best_score.compute(score_weights)

    print(f"  Baseline: {best_score.summary()} ({base_dur:.1f}s)")

    # Save baseline as current best
    shutil.copy2(str(work_dir / "experiment.kicad_pcb"),
                 str(best_dir / "best.kicad_pcb"))
    best_total = best_score.total

    experiments: list[Experiment] = []
    minor_stagnant = 0

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

        # Run
        t_label = f"Round {round_num}/{args.rounds} [{mode.upper()}]"
        score, duration = run_experiment(
            args.pcb, work_dir, candidate_cfg, candidate_seed, quiet=args.quiet)

        if score_weights:
            score.compute(score_weights)

        # Keep or discard
        kept = score.total > best_total
        if kept:
            improvement = score.total - best_total
            best_total = score.total
            best_cfg = candidate_cfg
            best_seed = candidate_seed
            best_score = score
            minor_stagnant = 0
            # Save best PCB
            shutil.copy2(str(work_dir / "experiment.kicad_pcb"),
                         str(best_dir / "best.kicad_pcb"))
            marker = f"+{improvement:.1f} NEW BEST"
        else:
            minor_stagnant += 1
            marker = f"discard (stagnant={minor_stagnant})"

        print(f"  {t_label}: {score.summary()} [{marker}] ({duration:.1f}s)")

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
        )
        experiments.append(exp)

        with open(log_path, 'a') as f:
            f.write(json.dumps(asdict(exp), default=str) + '\n')

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
