"""Pipeline orchestrators — PlacementEngine, RoutingEngine, FullPipeline.

Routing uses FreeRouting (Java) via DSN/SES file exchange.
Each engine: adapter.load() -> algorithm -> score.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

from .brain.group_placer import GroupPlacer
from .brain.groups import derive_signal_flow_order, resolve_groups
from .brain.placement import (
    PlacementScorer,
    PlacementSolver,
    _update_pad_positions,
    compute_min_board_size,
)
from .brain.types import (
    BoardState,
    DRCScore,
    ExperimentScore,
    PlacementScore,
    Point,
)
from .config import DEFAULT_CONFIG, LLUPS_CONFIG
from .freerouting_runner import count_board_tracks, route_with_freerouting
from .hardware.adapter import KiCadAdapter


def _override_board_outline(state: BoardState, cfg: dict):
    """Override board outline from config if board size search is active."""
    if cfg.get("enable_board_size_search", False):
        w = cfg.get("board_width_mm", 90.0)
        h = cfg.get("board_height_mm", 58.0)
        cx = (state.board_outline[0].x + state.board_outline[1].x) / 2
        cy = (state.board_outline[0].y + state.board_outline[1].y) / 2
        state.board_outline = (
            Point(cx - w / 2, cy - h / 2),
            Point(cx + w / 2, cy + h / 2),
        )


class PlacementEngine:
    """Run placement optimization.

    Supports two modes:
      - hierarchical (default): group-based placement — place within groups
        first, then arrange groups on the board as rigid blocks.
      - flat (legacy): global force-directed placement with clustering.
    """

    def run(
        self, pcb_path: str, output_path: str = None, config: dict = None, seed: int = 0
    ) -> dict:
        cfg = {**DEFAULT_CONFIG, **LLUPS_CONFIG, **(config or {})}
        adapter = KiCadAdapter(pcb_path, config=cfg)
        state = adapter.load()

        _override_board_outline(state, cfg)

        print(f"Loaded {len(state.components)} components, {len(state.nets)} nets")

        # Compute minimum viable board size for search bounds
        overhead = cfg.get("board_size_overhead_factor", 2.5)
        min_w, min_h = compute_min_board_size(state, overhead)
        print(
            f"  Min viable board: {min_w:.0f} x {min_h:.0f} mm "
            f"(overhead={overhead:.1f}x)"
        )

        # Choose placement strategy
        use_hierarchical = cfg.get("hierarchical_placement", True)

        if use_hierarchical:
            new_comps = self._run_hierarchical(pcb_path, adapter, state, cfg, seed)
        else:
            new_comps = self._run_flat(state, cfg, seed)

        # Score placement; if degenerate (score=0), retry once with flat fallback
        state.components = new_comps
        scorer = PlacementScorer(state, cfg)
        score = scorer.score()
        if score.total < 1.0:
            print("  Placement degenerate (score=0), retrying with flat placement...")
            state2 = adapter.load()
            _override_board_outline(state2, cfg)
            fallback_cfg = {**cfg}
            for k in (
                "force_attract_k",
                "force_repel_k",
                "cooling_factor",
                "placement_clearance_mm",
                "orderedness",
            ):
                if k in DEFAULT_CONFIG:
                    fallback_cfg[k] = DEFAULT_CONFIG[k]
            new_comps = self._run_flat(state2, fallback_cfg, seed + 1)
            state.components = new_comps
            score = PlacementScorer(state, cfg).score()

        out = output_path or pcb_path
        adapter.apply_placement(new_comps, out)

        # Count pads outside board boundary (hard metric, not percentage)
        tl, br = state.board_outline
        inset = cfg.get("pad_inset_margin_mm", 0.3)
        pads_outside = 0
        for comp in new_comps.values():
            for pad in comp.pads:
                if (
                    pad.pos.x < tl.x + inset
                    or pad.pos.x > br.x - inset
                    or pad.pos.y < tl.y + inset
                    or pad.pos.y > br.y - inset
                ):
                    pads_outside += 1

        return {
            "components_placed": len(new_comps),
            "score": score.total,
            "net_distance": score.net_distance,
            "crossovers": score.crossover_count,
            "crossover_score": score.crossover_score,
            "compactness": score.compactness,
            "edge_compliance": score.edge_compliance,
            "rotation_score": score.rotation_score,
            "board_containment": score.board_containment,
            "courtyard_overlap": score.courtyard_overlap,
            "pads_outside_board": pads_outside,
            "min_board_width_mm": min_w,
            "min_board_height_mm": min_h,
        }

    def _run_flat(
        self, state: BoardState, cfg: dict, seed: int
    ) -> dict[str, "Component"]:
        """Legacy flat placement: global force-directed with clustering."""
        solver = PlacementSolver(state, cfg, seed=seed)
        return solver.solve()

    def _run_hierarchical(
        self,
        pcb_path: str,
        adapter: "KiCadAdapter",
        state: BoardState,
        cfg: dict,
        seed: int,
    ) -> dict[str, "Component"]:
        """Hierarchical group-based placement.

        1. Extract functional groups
        2. Place components within each group (intra-group)
        3. Arrange groups on the board (inter-group)
        4. Apply global positions and run post-processing
        """
        import copy
        import os

        # --- Step 1: Extract functional groups ---
        project_dir = os.path.dirname(os.path.abspath(pcb_path))
        component_refs = list(state.components.keys())
        group_set = resolve_groups(
            project_dir, component_refs, state.nets, cfg, seed=seed
        )

        if not group_set.groups:
            print("  No functional groups found — falling back to flat placement")
            return self._run_flat(state, cfg, seed)

        # Derive signal flow order
        flow_order = cfg.get("signal_flow_order", [])
        if not flow_order:
            flow_order = derive_signal_flow_order(group_set, state.nets)
        print(f"  Signal flow: {' -> '.join(flow_order)}")

        # --- Step 2: Intra-group placement ---
        solver = PlacementSolver(state, cfg, seed=seed)
        placed_groups = []
        for group in group_set.groups:
            print(
                f"  Placing group '{group.name}' ({len(group.member_refs)} components)..."
            )
            pg = solver.solve_group(group, state.components, state.nets)
            placed_groups.append(pg)
            print(f"    -> {pg.width:.1f} x {pg.height:.1f} mm block")

        # --- Step 3: Inter-group placement ---
        print(f"  Arranging {len(placed_groups)} groups on board...")
        ungrouped_comps = {
            ref: state.components[ref]
            for ref in group_set.ungrouped_refs
            if ref in state.components
        }

        group_placer = GroupPlacer(state, cfg, seed=seed)
        global_positions = group_placer.place_groups(
            placed_groups, ungrouped_comps, state.nets, signal_flow_order=flow_order
        )

        # --- Step 4: Apply global positions to components ---
        new_comps = copy.deepcopy(state.components)
        for ref, (gx, gy, rot, layer) in global_positions.items():
            if ref not in new_comps:
                continue
            comp = new_comps[ref]
            old_pos = Point(comp.pos.x, comp.pos.y)
            old_rot = comp.rotation
            comp.pos = Point(gx, gy)
            comp.rotation = rot
            comp.layer = layer
            _update_pad_positions(comp, old_pos, old_rot)

        # --- Step 5: Post-processing (reuse existing solver infrastructure) ---
        # Run a short global refinement pass: overlap resolution, clamping,
        # edge pinning.  The solver's solve() method is too heavy — we just
        # need the cleanup steps.
        post_solver = PlacementSolver(state, cfg, seed=seed)

        # Assign layers (large THT to back)
        post_solver._assign_layers(new_comps)

        # Pin edge components (connectors, mounting holes)
        post_solver._pin_edge_components(new_comps)

        # Align large pairs
        post_solver._align_large_pairs(new_comps)

        # Resolve overlaps
        post_solver._resolve_overlaps(new_comps)
        post_solver._re_snap_aligned_pairs(new_comps)

        # Snap to grid
        post_solver._snap_to_grid(new_comps)
        post_solver._re_snap_aligned_pairs(new_comps)

        # Final overlap resolution
        post_solver._resolve_overlaps(new_comps)
        post_solver._re_snap_aligned_pairs(new_comps)

        # Hard clamp — nothing outside the board
        post_solver._clamp_to_board(new_comps)
        post_solver._clamp_pads_to_board(new_comps)

        # Validate pad containment
        tl, br = state.board_outline
        inset = cfg.get("pad_inset_margin_mm", 0.3)
        for clamp_pass in range(3):
            any_outside = False
            for comp in new_comps.values():
                for pad in comp.pads:
                    if (
                        pad.pos.x < tl.x + inset
                        or pad.pos.x > br.x - inset
                        or pad.pos.y < tl.y + inset
                        or pad.pos.y > br.y - inset
                    ):
                        any_outside = True
                        break
                if any_outside:
                    break
            if not any_outside:
                break
            post_solver._clamp_to_board(new_comps)
            post_solver._clamp_pads_to_board(new_comps)
            if clamp_pass == 2:
                print("  WARNING: some pads still outside board after 3 clamp passes")

        # Restore pinned positions
        post_solver._restore_pinned_positions(new_comps)
        post_solver._resolve_overlaps(new_comps)
        post_solver._restore_pinned_positions(new_comps)
        post_solver._clamp_pads_to_board(new_comps)

        # Final score
        state.components = new_comps
        final = PlacementScorer(state, cfg).score()
        print(
            f"  Final placement score: {final.total:.1f} "
            f"(nets={final.net_distance:.0f} "
            f"cross={final.crossover_score:.0f} "
            f"xovers={final.crossover_count})"
        )

        return new_comps


class RoutingEngine:
    """Run FreeRouting autorouter via DSN/SES file exchange."""

    def run(self, pcb_path: str, output_path: str = None, config: dict = None) -> dict:
        cfg = {**DEFAULT_CONFIG, **LLUPS_CONFIG, **(config or {})}
        out = output_path or pcb_path

        jar_path = cfg.get(
            "freerouting_jar", os.path.expanduser("~/.local/lib/freerouting-1.9.0.jar")
        )

        t0 = time.monotonic()
        stats = route_with_freerouting(pcb_path, out, jar_path, cfg)
        routing_ms = (time.monotonic() - t0) * 1000.0

        # Count actual traces/vias from the routed board
        track_counts = count_board_tracks(out)

        # Count nets from the board state
        adapter = KiCadAdapter(out, config=cfg)
        state = adapter.load()
        skip_gnd = cfg.get("skip_gnd_routing", True)
        ignore_nets = set(cfg.get("freerouting_ignore_nets", []))
        routable_nets = [
            n
            for n in state.nets.values()
            if len(n.pad_refs) >= 2
            and not (skip_gnd and n.name in ("GND", "/GND"))
            and n.name not in ignore_nets
        ]
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

    def run(
        self, pcb_path: str, output_path: str = None, config: dict = None, seed: int = 0
    ) -> dict:
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
        min_score = cfg.get("min_placement_score", 20.0)
        min_containment = cfg.get("min_board_containment", 90.0)
        min_courtyard = cfg.get("min_courtyard_overlap_score", 50.0)

        skip_reason = None
        p_score = placement.get("score", 0)
        p_contain = placement.get("board_containment", 100)
        p_courtyard = placement.get("courtyard_overlap", 100)
        p_pads_out = placement.get("pads_outside_board", 0)

        if p_pads_out > 0:
            skip_reason = (
                f"{p_pads_out} pads outside board boundary — placement invalid"
            )
        elif p_score < min_score:
            skip_reason = f"total score {p_score:.1f} < {min_score}"
        elif p_contain < min_containment:
            skip_reason = (
                f"board containment {p_contain:.1f}% < {min_containment}% "
                f"(pads/bodies outside board)"
            )
        elif p_courtyard < min_courtyard:
            skip_reason = (
                f"courtyard overlap score {p_courtyard:.1f} < {min_courtyard} "
                f"(major component overlaps)"
            )

        if skip_reason:
            print(f"  Placement REJECTED: {skip_reason} — skipping routing")
            exp_score = ExperimentScore(
                placement_ms=placement_ms,
                skipped_routing=True,
            )
            exp_score.placement = PlacementScore(
                total=placement.get("score", 0),
                net_distance=placement.get("net_distance", 0),
                crossover_count=placement.get("crossovers", 0),
                crossover_score=placement.get("crossover_score", 0),
                compactness=placement.get("compactness", 0),
                edge_compliance=placement.get("edge_compliance", 0),
                rotation_score=placement.get("rotation_score", 0),
                board_containment=placement.get("board_containment", 0),
                courtyard_overlap=placement.get("courtyard_overlap", 0),
            )
            _skip_drc = {
                "shorts": 0,
                "unconnected": 0,
                "clearance": 0,
                "courtyard": 0,
                "total": 0,
            }
            exp_score.pipeline_drc = _skip_drc
            exp_score.compute(
                drc_dict=_skip_drc,
                board_area_mm2=cfg.get("board_width_mm", 90.0)
                * cfg.get("board_height_mm", 58.0)
                if cfg.get("enable_board_size_search")
                else None,
            )
            return {
                "placement": placement,
                "routing": {
                    "traces": 0,
                    "vias": 0,
                    "failed_nets": [],
                    "total_nets": 0,
                    "total_length_mm": 0,
                    "routing_ms": 0,
                },
                "drc": {
                    "shorts": 0,
                    "unconnected": 0,
                    "clearance": 0,
                    "courtyard": 0,
                    "total": 0,
                },
                "experiment_score": exp_score,
                "skipped_routing": True,
            }

        print()
        print("=" * 50)
        print("Phase 1+2: FreeRouting Autorouter")
        print("=" * 50)
        # Strip pre-existing zones from source PCB, then add fresh GND zone.
        # Both run in subprocesses to avoid pcbnew SWIG corruption.
        strip_adapter = KiCadAdapter(out, config=cfg)
        strip_adapter.strip_zones()
        _ensure_gnd_zone_subprocess(out, cfg)

        re = RoutingEngine()
        routing = re.run(out, out, cfg)

        # Re-fill zones after routing so zone clearances are computed against
        # the final trace geometry (prevents stale zone-fill DRC violations).
        _refill_zones(out)

        # Phase 3: DRC analysis
        print()
        print("=" * 50)
        print("Phase 3: DRC Analysis")
        print("=" * 50)
        drc = _run_kicad_cli_drc(out)
        print(
            f"  DRC: {drc['total']} violations "
            f"(shorts={drc['shorts']} unconnected={drc['unconnected']} "
            f"clearance={drc['clearance']} courtyard={drc['courtyard']})"
        )

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
            compactness=placement.get("compactness", 0),
            edge_compliance=placement.get("edge_compliance", 0),
            rotation_score=placement.get("rotation_score", 0),
            board_containment=placement.get("board_containment", 0),
            courtyard_overlap=placement.get("courtyard_overlap", 0),
        )
        exp_score.pipeline_drc = drc
        exp_score.compute(
            drc_dict=drc,
            board_area_mm2=cfg.get("board_width_mm", 90.0)
            * cfg.get("board_height_mm", 58.0)
            if cfg.get("enable_board_size_search")
            else None,
        )

        return {
            "placement": placement,
            "routing": routing,
            "drc": drc,
            "experiment_score": exp_score,
        }


def _ensure_gnd_zone_subprocess(pcb_path: str, cfg: dict) -> None:
    """Create/update GND zone in a subprocess to avoid pcbnew SWIG corruption."""
    import subprocess

    zone_net = cfg.get("gnd_zone_net", "GND")
    if not zone_net:
        return
    layer = cfg.get("gnd_zone_layer", "B.Cu")
    margin_mm = cfg.get("gnd_zone_margin_mm", 0.5)
    target_layer = "pcbnew.B_Cu" if layer == "B.Cu" else "pcbnew.F_Cu"
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import pcbnew\n"
            f"board = pcbnew.LoadBoard({pcb_path!r})\n"
            f"zone_net_name = {zone_net!r}\n"
            f"target_layer = {target_layer}\n"
            f"margin = pcbnew.FromMM({margin_mm})\n"
            "gnd_net = board.GetNetInfo().GetNetItem(zone_net_name)\n"
            "if not gnd_net or gnd_net.GetNetCode() == 0:\n"
            "    print(f'WARNING: Net {zone_net_name!r} not found')\n"
            "    raise SystemExit(0)\n"
            "rect = board.GetBoardEdgesBoundingBox()\n"
            "x1 = rect.GetX() + margin\n"
            "y1 = rect.GetY() + margin\n"
            "x2 = x1 + rect.GetWidth() - 2 * margin\n"
            "y2 = y1 + rect.GetHeight() - 2 * margin\n"
            "existing = None\n"
            "for z in board.Zones():\n"
            "    if z.GetLayer() == target_layer and z.GetNetname() == zone_net_name and not z.GetIsRuleArea():\n"
            "        existing = z; break\n"
            "if existing:\n"
            "    ol = existing.Outline(); ol.RemoveAllContours(); ol.NewOutline()\n"
            "    ol.Append(x1,y1); ol.Append(x2,y1); ol.Append(x2,y2); ol.Append(x1,y2)\n"
            "else:\n"
            "    z = pcbnew.ZONE(board); z.SetNet(gnd_net); z.SetLayer(target_layer)\n"
            "    z.SetIsRuleArea(False); z.SetDoNotAllowTracks(False); z.SetDoNotAllowVias(False)\n"
            "    z.SetDoNotAllowPads(False); z.SetDoNotAllowCopperPour(False)\n"
            "    z.SetLocalClearance(pcbnew.FromMM(0.3))\n"
            "    z.SetMinThickness(pcbnew.FromMM(0.25))\n"
            "    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)\n"
            "    z.SetThermalReliefGap(pcbnew.FromMM(0.5))\n"
            "    z.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.5))\n"
            "    z.SetAssignedPriority(0)\n"
            "    ol = z.Outline(); ol.NewOutline()\n"
            "    ol.Append(x1,y1); ol.Append(x2,y1); ol.Append(x2,y2); ol.Append(x1,y2)\n"
            "    board.Add(z)\n"
            "filler = pcbnew.ZONE_FILLER(board)\n"
            "filler.Fill(board.Zones())\n"
            f"board.Save({pcb_path!r})\n"
            f"print('GND zone on {layer}: ensured and filled')\n",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _refill_zones(pcb_path: str) -> None:
    """Re-fill copper zones so they respect the final trace layout."""
    import subprocess

    subprocess.run(
        [
            sys.executable,
            "-c",
            "import pcbnew\n"
            f"board = pcbnew.LoadBoard({pcb_path!r})\n"
            "board.BuildConnectivity()\n"
            "filler = pcbnew.ZONE_FILLER(board)\n"
            "filler.Fill(board.Zones())\n"
            f"board.Save({pcb_path!r})\n",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )


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
            capture_output=True,
            text=True,
            timeout=60,
        )
        with open(report_path) as f:
            report = f.read()
        os.remove(report_path)

        for line in report.splitlines():
            m = re.match(r"^\[(\w+)\]:", line)
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
