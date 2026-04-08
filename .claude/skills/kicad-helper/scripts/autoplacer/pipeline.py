"""Pipeline orchestrators — PlacementEngine, RoutingEngine, FullPipeline.

Each engine: adapter.load() -> brain algorithm -> adapter.apply() -> score.
"""
from __future__ import annotations
import json
import os
import sys

from .brain.types import BoardState, PlacementScore, ExperimentScore
from .brain.placement import PlacementSolver, PlacementScorer
from .brain.router import RoutingSolver
from .brain.conflict import RipUpRerouter
from .brain.drc_sweep import find_clearance_violations, nudge_traces_apart
from .hardware.adapter import KiCadAdapter
from .config import DEFAULT_CONFIG


class PlacementEngine:
    """Run placement optimization: edge-first + clustering + force-directed."""

    def run(self, pcb_path: str, output_path: str = None,
            config: dict = None, max_iterations: int = 300,
            seed: int = 0) -> dict:
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        adapter = KiCadAdapter(pcb_path)
        state = adapter.load()

        print(f"Loaded {len(state.components)} components, {len(state.nets)} nets")

        solver = PlacementSolver(state, cfg, seed=seed)
        new_comps = solver.solve(max_iterations=max_iterations)

        out = output_path or pcb_path
        adapter.apply_placement(new_comps, out)

        # Score final placement
        state.components = new_comps
        scorer = PlacementScorer(state)
        score = scorer.score()

        return {
            "components_placed": len(new_comps),
            "score": score.total,
            "net_distance": score.net_distance,
            "crossovers": score.crossover_count,
            "crossover_score": score.crossover_score,
            "edge_compliance": score.edge_compliance,
            "rotation_score": score.rotation_score,
            "board_containment": score.board_containment,
            "courtyard_overlap": score.courtyard_overlap,
        }


class RoutingEngine:
    """Run A* routing with optional rip-up and re-route."""

    def run(self, pcb_path: str, output_path: str = None,
            config: dict = None, rip_up: bool = True) -> dict:
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        adapter = KiCadAdapter(pcb_path)
        state = adapter.load()

        print(f"Routing {len(state.nets)} nets on {len(state.components)} components")

        solver = RoutingSolver(state, cfg)
        traces, vias, failed = solver.solve()

        if rip_up and failed:
            print(f"Running RRR for {len(failed)} failed nets...")
            rrr = RipUpRerouter(state, cfg)
            traces, vias, failed = rrr.solve(traces, vias, failed)

        # Post-route geometric DRC sweep: nudge traces apart where clearance violated
        clearance = cfg.get("clearance_mm", 0.2)
        violations = find_clearance_violations(traces, vias, clearance)
        if violations:
            print(f"  DRC sweep: {len(violations)} clearance violations, nudging...")
            traces, n_nudged = nudge_traces_apart(traces, vias, clearance)
            print(f"  DRC sweep: nudged {n_nudged} segments")

        out = output_path or pcb_path
        adapter.apply_routing(
            traces, vias,
            clear_existing=True,
            preserve_thermal_vias=True,
            thermal_refs=cfg.get("thermal_refs", []),
            thermal_radius_mm=cfg.get("thermal_radius_mm", 3.0),
            output_path=out,
        )

        # Count routable nets from the already-loaded state (avoids an extra board load)
        skip_gnd = cfg.get("skip_gnd_routing", True)
        n_total = len([n for n in state.nets.values()
                       if len(n.pad_refs) >= 2 and
                       not (skip_gnd and n.name in ("GND", "/GND"))])

        return {
            "traces": len(traces),
            "vias": len(vias),
            "failed_nets": failed,
            "total_nets": n_total,
            "total_length_mm": sum(s.length for s in traces),
        }


class FullPipeline:
    """Run placement + routing + scoring in sequence."""

    def run(self, pcb_path: str, output_path: str = None,
            config: dict = None, seed: int = 0) -> dict:
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        out = output_path or pcb_path

        print("=" * 50)
        print("Phase 0: Placement Optimization")
        print("=" * 50)
        pe = PlacementEngine()
        placement = pe.run(pcb_path, out, cfg, seed=seed)

        print()
        print("=" * 50)
        print("Phase 1+2: A* Routing + RRR")
        print("=" * 50)
        re = RoutingEngine()
        routing = re.run(out, out, cfg)

        # Build unified experiment score
        failed = routing["failed_nets"]
        n_failed = len(failed) if isinstance(failed, list) else 0
        n_total = routing["total_nets"]  # returned by RoutingEngine, no extra load

        exp_score = ExperimentScore(
            routed_nets=max(0, n_total - n_failed),
            total_nets=n_total,
            failed_nets=n_failed,
            trace_count=routing["traces"],
            via_count=routing["vias"],
            total_trace_length_mm=routing["total_length_mm"],
        )
        # Attach placement score
        exp_score.placement = PlacementScore(
            total=placement.get("score", 0),
            net_distance=placement.get("net_distance", 0),
            crossover_count=placement.get("crossovers", 0),
            crossover_score=placement.get("crossover_score", 0),
            edge_compliance=placement.get("edge_compliance", 0),
            rotation_score=placement.get("rotation_score", 0),
            board_containment=placement.get("board_containment", 0),
            courtyard_overlap=placement.get("courtyard_overlap", 0),
        )
        exp_score.compute()

        return {
            "placement": placement,
            "routing": routing,
            "experiment_score": exp_score,
        }
