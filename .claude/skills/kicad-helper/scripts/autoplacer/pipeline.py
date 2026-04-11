"""Pipeline orchestrators — PlacementEngine, RoutingEngine, FullPipeline.

Routing uses FreeRouting (Java) via DSN/SES file exchange.
Each engine: adapter.load() -> algorithm -> score.
"""
from __future__ import annotations
import os
import time
from typing import Any

from .brain.types import BoardState, PlacementScore, ExperimentScore, DRCScore
from .brain.placement import PlacementSolver, PlacementScorer
from .freerouting_runner import route_with_freerouting, count_board_tracks
from .hardware.adapter import KiCadAdapter
from .config import DEFAULT_CONFIG, LLUPS_CONFIG


class PlacementEngine:
    """Run placement optimization: edge-first + clustering + force-directed."""

    def run(self, pcb_path: str, output_path: str = None,
            config: dict = None, seed: int = 0) -> dict:
        cfg = {**DEFAULT_CONFIG, **LLUPS_CONFIG, **(config or {})}
        adapter = KiCadAdapter(pcb_path)
        state = adapter.load()

        print(f"Loaded {len(state.components)} components, {len(state.nets)} nets")

        solver = PlacementSolver(state, cfg, seed=seed)
        new_comps = solver.solve()

        out = output_path or pcb_path
        adapter.apply_placement(new_comps, out)

        # Score final placement
        state.components = new_comps
        scorer = PlacementScorer(state, cfg)
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
            config: dict = None) -> dict:
        cfg = {**DEFAULT_CONFIG, **LLUPS_CONFIG, **(config or {})}
        out = output_path or pcb_path

        jar_path = cfg.get("freerouting_jar",
                           os.path.expanduser("~/.local/lib/freerouting-1.9.0.jar"))

        t0 = time.monotonic()
        stats = route_with_freerouting(pcb_path, out, jar_path, cfg)
        routing_ms = (time.monotonic() - t0) * 1000.0

        # Count actual traces/vias from the routed board
        track_counts = count_board_tracks(out)

        # Count nets from the board state
        adapter = KiCadAdapter(out)
        state = adapter.load()
        skip_gnd = cfg.get("skip_gnd_routing", True)
        ignore_nets = set(cfg.get("freerouting_ignore_nets", []))
        routable_nets = [n for n in state.nets.values()
                         if len(n.pad_refs) >= 2 and
                         not (skip_gnd and n.name in ("GND", "/GND")) and
                         n.name not in ignore_nets]
        n_total = len(routable_nets)

        # FreeRouting reports unrouted count; derive failed nets
        unrouted = stats.get("unrouted", 0)
        # Clamp to total in case FreeRouting counts differently
        unrouted = max(0, min(unrouted, n_total))

        return {
            "traces": track_counts["traces"],
            "vias": track_counts["vias"],
            "failed_nets": [f"unrouted_{i}" for i in range(unrouted)],
            "total_nets": n_total,
            "total_length_mm": track_counts["total_length_mm"],
            "routing_ms": routing_ms,
            "freerouting_stats": stats,
        }


class FullPipeline:
    """Run placement + routing + scoring in sequence."""

    def run(self, pcb_path: str, output_path: str = None,
            config: dict = None, seed: int = 0) -> dict:
        cfg = {**DEFAULT_CONFIG, **LLUPS_CONFIG, **(config or {})}
        out = output_path or pcb_path

        print("=" * 50)
        print("Phase 0: Placement Optimization")
        print("=" * 50)
        placement_t0 = time.monotonic()
        pe = PlacementEngine()
        placement = pe.run(pcb_path, out, cfg, seed=seed)
        placement_ms = (time.monotonic() - placement_t0) * 1000.0

        # Placement validation gate: skip routing if placement is degenerate
        min_score = cfg.get("min_placement_score", 30.0)
        if placement.get("score", 0) < min_score:
            print(f"  Placement score {placement.get('score', 0):.1f} < {min_score} — "
                  f"skipping routing (degenerate layout)")
            exp_score = ExperimentScore(
                placement_ms=placement_ms,
            )
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
            exp_score.compute(drc_dict={"shorts": 0, "unconnected": 0,
                                        "clearance": 0, "courtyard": 0, "total": 0})
            return {
                "placement": placement,
                "routing": {"traces": 0, "vias": 0, "failed_nets": [],
                            "total_nets": 0, "total_length_mm": 0, "routing_ms": 0},
                "drc": {"shorts": 0, "unconnected": 0, "clearance": 0,
                        "courtyard": 0, "total": 0},
                "experiment_score": exp_score,
                "skipped_routing": True,
            }

        print()
        print("=" * 50)
        print("Phase 1+2: FreeRouting Autorouter")
        print("=" * 50)
        re = RoutingEngine()
        routing = re.run(out, out, cfg)

        # Phase 3: DRC analysis
        print()
        print("=" * 50)
        print("Phase 3: DRC Analysis")
        print("=" * 50)
        drc = _run_kicad_cli_drc(out)
        print(f"  DRC: {drc['total']} violations "
              f"(shorts={drc['shorts']} unconnected={drc['unconnected']} "
              f"clearance={drc['clearance']} courtyard={drc['courtyard']})")

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
            failed_net_names=list(failed) if isinstance(failed, list) else [],
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
        exp_score.compute(drc_dict=drc)

        return {
            "placement": placement,
            "routing": routing,
            "drc": drc,
            "experiment_score": exp_score,
        }


def _run_kicad_cli_drc(pcb_path: str) -> dict:
    """Run kicad-cli DRC and parse violation counts."""
    import re
    import subprocess
    import tempfile

    counts = {"shorts": 0, "unconnected": 0, "clearance": 0, "courtyard": 0, "total": 0}
    try:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            report_path = f.name
        subprocess.run(
            ["kicad-cli", "pcb", "drc", "-o", report_path, pcb_path],
            capture_output=True, text=True, timeout=60,
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
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        counts["error"] = str(exc)
    return counts
