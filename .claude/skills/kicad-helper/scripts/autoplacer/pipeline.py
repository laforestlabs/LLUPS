"""Pipeline orchestrators — PlacementEngine, RoutingEngine, FullPipeline.

Each engine: adapter.load() -> brain algorithm -> adapter.apply() -> score.
"""
from __future__ import annotations
import os
import time
from typing import Any

from .brain.types import BoardState, PlacementScore, ExperimentScore
from .brain.placement import PlacementSolver, PlacementScorer
from .freerouting_runner import route_with_freerouting
from .hardware.adapter import KiCadAdapter
from .config import DEFAULT_CONFIG

# Optional debug logging
def _get_log() -> Any:
    """Get debug logger if available."""
    try:
        import logging_config
        return logging_config.get_logger("pipeline")
    except ImportError:
        return None

_pipeline_log = None  # Lazy init


class PlacementEngine:
    """Run placement optimization: edge-first + clustering + force-directed."""

    def run(self, pcb_path: str, output_path: str = None,
            config: dict = None, seed: int = 0) -> dict:
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        adapter = KiCadAdapter(pcb_path)
        state = adapter.load()

        print(f"Loaded {len(state.components)} components, {len(state.nets)} nets")

        solver = PlacementSolver(state, cfg, seed=seed)
        new_comps = solver.solve()

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
    """Run FreeRouting autorouter via DSN/SES file exchange."""

    def run(self, pcb_path: str, output_path: str = None,
            config: dict = None, rip_up: bool = True) -> dict:
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        out = output_path or pcb_path

        jar_path = cfg.get("freerouting_jar",
                           os.path.expanduser("~/.local/lib/freerouting-2.1.0.jar"))

        t0 = time.monotonic()
        stats = route_with_freerouting(pcb_path, out, jar_path, cfg)
        routing_ms = (time.monotonic() - t0) * 1000.0

        # Count nets from the board state
        adapter = KiCadAdapter(out)
        state = adapter.load()
        skip_gnd = cfg.get("skip_gnd_routing", True)
        routable_nets = [n for n in state.nets.values()
                         if len(n.pad_refs) >= 2 and
                         not (skip_gnd and n.name in ("GND", "/GND"))]
        n_total = len(routable_nets)

        # FreeRouting reports unrouted count; derive failed nets
        unrouted = stats.get("unrouted", 0)
        # Clamp to total in case FreeRouting counts differently
        unrouted = max(0, min(unrouted, n_total))

        return {
            "traces": 0,  # exact count not available from FreeRouting
            "vias": 0,
            "failed_nets": [f"unrouted_{i}" for i in range(unrouted)],
            "total_nets": n_total,
            "total_length_mm": 0.0,
            "routing_ms": routing_ms,
            "rrr_ms": 0.0,
            "rrr_summary": None,
            "per_net_results": [],
            "freerouting_stats": stats,
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
        placement_t0 = time.monotonic()
        pe = PlacementEngine()
        placement = pe.run(pcb_path, out, cfg, seed=seed)
        placement_ms = (time.monotonic() - placement_t0) * 1000.0

        print()
        print("=" * 50)
        print("Phase 1+2: FreeRouting Autorouter")
        print("=" * 50)
        re = RoutingEngine()
        routing = re.run(out, out, cfg)

        # Build unified experiment score
        failed = routing["failed_nets"]
        n_failed = len(failed) if isinstance(failed, list) else 0
        n_total = routing["total_nets"]

        exp_score = ExperimentScore(
            routed_nets=max(0, n_total - n_failed),
            total_nets=n_total,
            failed_nets=n_failed,
            trace_count=routing["traces"],
            via_count=routing["vias"],
            total_trace_length_mm=routing["total_length_mm"],
            placement_ms=placement_ms,
            routing_ms=routing.get("routing_ms", 0.0),
            rrr_ms=0.0,
            per_net_results=[],
            rrr_summary=None,
            failed_net_names=list(failed) if isinstance(failed, list) else [],
            total_a_star_expansions=0,
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
