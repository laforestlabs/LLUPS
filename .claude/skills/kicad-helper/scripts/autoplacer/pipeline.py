"""Pipeline orchestrators — PlacementEngine, RoutingEngine, FullPipeline.

Each engine: adapter.load() -> brain algorithm -> adapter.apply() -> score.
"""
from __future__ import annotations
import json
import os
import sys

from .brain.types import BoardState, PlacementScore
from .brain.placement import PlacementSolver, PlacementScorer
from .brain.router import RoutingSolver
from .brain.conflict import RipUpRerouter
from .hardware.adapter import KiCadAdapter
from .config import DEFAULT_CONFIG


class PlacementEngine:
    """Run placement optimization: edge-first + clustering + force-directed."""

    def run(self, pcb_path: str, output_path: str = None,
            config: dict = None, max_iterations: int = 300) -> dict:
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        adapter = KiCadAdapter(pcb_path)
        state = adapter.load()

        print(f"Loaded {len(state.components)} components, {len(state.nets)} nets")

        solver = PlacementSolver(state, cfg)
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

        out = output_path or pcb_path
        adapter.apply_routing(
            traces, vias,
            clear_existing=True,
            preserve_thermal_vias=True,
            thermal_refs=cfg.get("thermal_refs", []),
            thermal_radius_mm=cfg.get("thermal_radius_mm", 3.0),
            output_path=out,
        )

        return {
            "traces": len(traces),
            "vias": len(vias),
            "failed_nets": failed,
            "total_length_mm": sum(s.length for s in traces),
        }


class FullPipeline:
    """Run placement + routing + scoring in sequence."""

    def run(self, pcb_path: str, output_path: str = None,
            config: dict = None) -> dict:
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        out = output_path or pcb_path

        print("=" * 50)
        print("Phase 0: Placement Optimization")
        print("=" * 50)
        pe = PlacementEngine()
        placement = pe.run(pcb_path, out, cfg)

        print()
        print("=" * 50)
        print("Phase 1+2: A* Routing + RRR")
        print("=" * 50)
        re = RoutingEngine()
        routing = re.run(out, out, cfg)

        return {
            "placement": placement,
            "routing": routing,
        }
