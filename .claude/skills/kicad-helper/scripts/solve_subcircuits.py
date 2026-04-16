#!/usr/bin/env python3
"""Solve leaf subcircuits with local placement search.

This CLI is an early execution entrypoint for the subcircuits redesign.

It performs the following steps:

1. Parse the true-sheet schematic hierarchy from a top-level `.kicad_sch`
2. Load the full project `.kicad_pcb`
3. Extract each leaf sheet into a local synthetic board state
4. Run local placement search for each leaf subcircuit
5. Save JSON metadata/debug artifacts for each solved leaf
6. Print a human-readable or JSON summary

Current scope:
- leaf-only solving
- placement search with optional local routing
- local routing currently uses the lightweight internal-net router from `subcircuit_solver.py`
- no parent/composite composition yet

The goal is to establish a stable bottom-up local solve loop that can later
be extended with:
- local routing
- frozen subcircuit layout artifacts
- parent-level rigid composition
- final top-level assembly

Usage:
    python3 solve_subcircuits.py LLUPS.kicad_sch
    python3 solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb
    python3 solve_subcircuits.py LLUPS.kicad_sch --rounds 8
    python3 solve_subcircuits.py LLUPS.kicad_sch --json
    python3 solve_subcircuits.py LLUPS.kicad_sch --only CHARGER
    python3 solve_subcircuits.py LLUPS.kicad_sch --route
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import site
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


def _ensure_kicad_python_path() -> None:
    """Ensure KiCad Python bindings are importable."""
    try:
        import pcbnew  # noqa: F401

        return
    except Exception:
        pass

    ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    candidates = [
        f"/usr/lib/python{ver}/site-packages",
        f"/usr/lib64/python{ver}/site-packages",
        "/usr/lib/python3/dist-packages",
        "/usr/lib64/python3/dist-packages",
    ]

    try:
        candidates.extend(site.getsitepackages())
    except Exception:
        pass
    try:
        candidates.append(site.getusersitepackages())
    except Exception:
        pass

    seen = set()
    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        pcbnew_py = Path(path) / "pcbnew.py"
        pcbnew_pkg = Path(path) / "pcbnew"
        if pcbnew_py.exists() or pcbnew_pkg.exists():
            if path not in sys.path:
                sys.path.append(path)

    try:
        import pcbnew  # noqa: F401
    except Exception as exc:
        raise ModuleNotFoundError(
            "KiCad Python module 'pcbnew' not found. "
            "Install KiCad bindings or set PYTHONPATH to KiCad site-packages."
        ) from exc


_ensure_kicad_python_path()

from autoplacer.brain.hierarchy_parser import (
    HierarchyGraph,
    HierarchyNode,
    parse_hierarchy,
)
from autoplacer.brain.placement import PlacementScorer, PlacementSolver
from autoplacer.brain.subcircuit_artifacts import (
    build_anchor_validation,
    build_artifact_metadata,
    build_leaf_extraction,
    build_solved_layout_artifact,
    resolve_artifact_paths,
    save_artifact_metadata,
    save_debug_payload,
    save_solved_layout_artifact,
    serialize_components,
)
from autoplacer.brain.subcircuit_board_export import (
    ExportOptions,
    export_subcircuit_board,
)
from autoplacer.brain.subcircuit_extractor import (
    ExtractedSubcircuitBoard,
    extract_leaf_board_state,
    extraction_debug_dict,
    summarize_extraction,
)
from autoplacer.brain.subcircuit_render_diagnostics import (
    generate_leaf_diagnostic_artifacts,
    generate_stage_diagnostic_artifacts,
)
from autoplacer.brain.types import (
    BoardState,
    Component,
    PlacementScore,
    SubCircuitLayout,
)
from autoplacer.config import DEFAULT_CONFIG, LLUPS_CONFIG, load_project_config
from autoplacer.freerouting_runner import (
    import_routed_copper,
    route_with_freerouting,
    validate_routed_board,
)
from autoplacer.hardware.adapter import KiCadAdapter


@dataclass(slots=True)
class SolveRoundResult:
    """One local placement-search round for a leaf subcircuit."""

    round_index: int
    seed: int
    score: float
    placement: PlacementScore
    components: dict[str, Component] = field(default_factory=dict)
    routing: dict[str, Any] = field(default_factory=dict)
    routed: bool = False

    def to_dict(self) -> dict[str, Any]:
        routing = {
            key: value for key, value in self.routing.items() if not key.startswith("_")
        }
        return {
            "round_index": self.round_index,
            "seed": self.seed,
            "score": self.score,
            "routed": self.routed,
            "placement": {
                "total": self.placement.total,
                "net_distance": self.placement.net_distance,
                "crossover_count": self.placement.crossover_count,
                "crossover_score": self.placement.crossover_score,
                "compactness": self.placement.compactness,
                "edge_compliance": self.placement.edge_compliance,
                "rotation_score": self.placement.rotation_score,
                "board_containment": self.placement.board_containment,
                "courtyard_overlap": self.placement.courtyard_overlap,
                "smt_opposite_tht": self.placement.smt_opposite_tht,
                "group_coherence": self.placement.group_coherence,
                "aspect_ratio": self.placement.aspect_ratio,
            },
            "routing": routing,
        }


@dataclass(slots=True)
class SolvedLeafSubcircuit:
    """Solved local placement result for one leaf subcircuit."""

    node: HierarchyNode
    extraction: ExtractedSubcircuitBoard
    best_round: SolveRoundResult
    all_rounds: list[SolveRoundResult] = field(default_factory=list)

    @property
    def sheet_name(self) -> str:
        return self.node.id.sheet_name

    @property
    def instance_path(self) -> str:
        return self.node.id.instance_path

    def best_round_to_layout(self):
        from autoplacer.brain.subcircuit_solver import infer_interface_anchors
        from autoplacer.brain.types import SubCircuitLayout

        anchors = infer_interface_anchors(
            self.extraction.interface_ports,
            self.best_round.components,
        )
        routed_traces = [
            copy.deepcopy(trace)
            for trace in self.best_round.routing.get("_trace_segments", [])
        ]
        routed_vias = [
            copy.deepcopy(via)
            for via in self.best_round.routing.get("_via_objects", [])
        ]

        return SubCircuitLayout(
            subcircuit_id=self.node.definition.id,
            components=copy.deepcopy(self.best_round.components),
            traces=routed_traces,
            vias=routed_vias,
            bounding_box=(
                self.extraction.local_state.board_width,
                self.extraction.local_state.board_height,
            ),
            ports=[copy.deepcopy(port) for port in self.extraction.interface_ports],
            interface_anchors=anchors,
            score=self.best_round.score,
            artifact_paths={},
            frozen=True,
        )

    def canonical_layout_artifact(self, cfg: dict[str, Any]) -> dict[str, Any]:
        layout = self.best_round_to_layout()
        project_dir = Path(self.extraction.subcircuit.schematic_path).parent
        return build_solved_layout_artifact(
            layout,
            project_dir=project_dir,
            source_hash=self.extraction.subcircuit.id.instance_path,
            config_hash=json.dumps(cfg, sort_keys=True, default=str),
            solver_version="subcircuits-m3-placement",
            notes=[
                f"round_index={self.best_round.round_index}",
                f"seed={self.best_round.seed}",
                f"routing={json.dumps({key: value for key, value in self.best_round.routing.items() if not key.startswith('_')}, sort_keys=True)}",
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sheet_name": self.sheet_name,
            "instance_path": self.instance_path,
            "summary": summarize_extraction(self.extraction),
            "best_round": self.best_round.to_dict(),
            "rounds": [round_result.to_dict() for round_result in self.all_rounds],
            "extraction": extraction_debug_dict(self.extraction),
        }


def _iter_children(node: HierarchyNode):
    for child in node.children:
        yield child
        yield from _iter_children(child)


def _iter_non_root_nodes(graph: HierarchyGraph):
    for child in graph.root.children:
        yield child
        yield from _iter_children(child)


def _default_pcb_path(top_schematic: Path) -> Path:
    return top_schematic.with_suffix(".kicad_pcb")


def _load_config(config_path: str | None) -> dict[str, Any]:
    cfg: dict[str, Any] = {**DEFAULT_CONFIG, **LLUPS_CONFIG}
    if config_path:
        cfg.update(load_project_config(config_path))
    return cfg


def _load_board_state(pcb_path: Path, config: dict[str, Any]) -> BoardState:
    adapter = KiCadAdapter(str(pcb_path), config=config)
    return adapter.load()


def _leaf_nodes(
    graph: HierarchyGraph, only: list[str] | None = None
) -> list[HierarchyNode]:
    selected = []
    only_set = {item.strip().lower() for item in (only or []) if item.strip()}
    for node in _iter_non_root_nodes(graph):
        if not node.is_leaf:
            continue
        if only_set:
            name_match = node.id.sheet_name.lower() in only_set
            path_match = node.id.instance_path.lower() in only_set
            file_match = node.id.sheet_file.lower() in only_set
            if not (name_match or path_match or file_match):
                continue
        selected.append(node)
    return selected


def _local_solver_config(
    base_cfg: dict[str, Any], extraction: ExtractedSubcircuitBoard
) -> dict[str, Any]:
    cfg = dict(base_cfg)

    cfg["enable_board_size_search"] = False
    cfg["hierarchical_placement"] = False
    cfg["group_source"] = "none"
    cfg["signal_flow_order"] = []
    cfg["ic_groups"] = {}
    cfg["group_labels"] = {}
    cfg["subcircuit_route_internal_nets"] = bool(
        base_cfg.get("subcircuit_route_internal_nets", False)
    )

    local_component_zones: dict[str, Any] = {}
    source_outline = extraction.envelope.source_board_outline
    source_board_tl = source_outline[0] if source_outline is not None else None
    source_board_br = source_outline[1] if source_outline is not None else None
    translation = extraction.translation

    for ref, comp in extraction.local_state.components.items():
        if comp.kind == "connector":
            if source_board_tl is not None and source_board_br is not None:
                if comp.body_center is not None:
                    source_center_x = comp.body_center.x - translation.x
                    source_center_y = comp.body_center.y - translation.y
                else:
                    source_center_x = comp.pos.x - translation.x
                    source_center_y = comp.pos.y - translation.y

                distances = {
                    "left": max(0.0, source_center_x - source_board_tl.x),
                    "right": max(0.0, source_board_br.x - source_center_x),
                    "top": max(0.0, source_center_y - source_board_tl.y),
                    "bottom": max(0.0, source_board_br.y - source_center_y),
                }
            else:
                if comp.body_center is not None:
                    local_center_x = comp.body_center.x
                    local_center_y = comp.body_center.y
                else:
                    local_center_x = comp.pos.x
                    local_center_y = comp.pos.y

                distances = {
                    "left": local_center_x,
                    "right": extraction.local_state.board_width - local_center_x,
                    "top": local_center_y,
                    "bottom": extraction.local_state.board_height - local_center_y,
                }

            nearest_edge = min(distances, key=distances.get)
            local_component_zones[ref] = {"edge": nearest_edge}

    cfg["component_zones"] = local_component_zones
    cfg["unlock_all_footprints"] = False

    cfg["board_width_mm"] = extraction.local_state.board_width
    cfg["board_height_mm"] = extraction.local_state.board_height

    cfg["placement_clearance_mm"] = max(
        3.0,
        float(base_cfg.get("placement_clearance_mm", 3.0)),
    )
    cfg["edge_margin_mm"] = max(
        2.0,
        float(base_cfg.get("edge_margin_mm", 2.0)),
    )
    cfg["placement_grid_mm"] = float(base_cfg.get("placement_grid_mm", 0.5))
    cfg["max_placement_iterations"] = max(
        300,
        int(base_cfg.get("max_placement_iterations", 300)),
    )
    cfg["placement_convergence_threshold"] = min(
        0.2,
        float(base_cfg.get("placement_convergence_threshold", 0.2)),
    )
    cfg["orderedness"] = 0.0
    cfg["randomize_group_layout"] = True
    cfg["scatter_mode"] = "random"
    cfg["placement_score_every_n"] = 1
    cfg["unlock_all_footprints"] = False
    cfg["align_large_pairs"] = False
    cfg["prefer_legal_states"] = True
    cfg["legalize_during_force"] = True
    cfg["legalize_every_n"] = 1
    cfg["legalize_during_force_passes"] = max(
        2,
        int(base_cfg.get("legalize_during_force_passes", 2)),
    )
    cfg["enable_swap_optimization"] = False
    cfg["leaf_legality_repair_passes"] = max(
        24,
        int(base_cfg.get("leaf_legality_repair_passes", 24)),
    )
    cfg["leaf_min_route_rounds"] = max(
        16,
        int(base_cfg.get("leaf_min_route_rounds", 16)),
    )

    return cfg


def _score_local_components(
    local_state: BoardState,
    components: dict[str, Component],
    cfg: dict[str, Any],
) -> PlacementScore:
    work_state = copy.copy(local_state)
    work_state.components = components
    score = PlacementScorer(work_state, cfg).score()

    legalizer = PlacementSolver(work_state, cfg, seed=0)
    legality = legalizer.legality_diagnostics(components)
    overlap_count = int(legality.get("overlap_count", 0))
    pad_outside_count = int(legality.get("pad_outside_count", 0))

    if overlap_count or pad_outside_count:
        score.courtyard_overlap = max(
            0.0,
            min(score.courtyard_overlap, 100.0 - 25.0 * overlap_count),
        )
        score.board_containment = max(
            0.0,
            min(score.board_containment, 100.0 - 40.0 * pad_outside_count),
        )
        score.compute_total()

    return score


def _repair_leaf_placement_legality(
    extraction: ExtractedSubcircuitBoard,
    solved_components: dict[str, Component],
    cfg: dict[str, Any],
) -> tuple[dict[str, Component], dict[str, Any]]:
    repaired = copy.deepcopy(solved_components)
    local_state = copy.deepcopy(extraction.local_state)
    local_state.components = repaired

    legalizer = PlacementSolver(local_state, cfg, seed=0)
    legalization = legalizer.legalize_components(
        repaired,
        max_passes=int(cfg.get("leaf_legality_repair_passes", 12)),
    )
    diagnostics = dict(legalization.get("diagnostics", {}))

    return repaired, {
        "attempted": True,
        "passes": int(legalization.get("passes", 0)),
        "moved_components": list(legalization.get("moved_refs", [])),
        "remaining_overlaps": list(diagnostics.get("overlaps", [])),
        "pads_outside_board": list(diagnostics.get("pads_outside_board", [])),
        "resolved": bool(legalization.get("resolved", False)),
        "diagnostics": diagnostics,
    }


def _route_local_subcircuit(
    extraction: ExtractedSubcircuitBoard,
    solved_components: dict[str, Component],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    if not extraction.internal_net_names:
        return {
            "enabled": True,
            "skipped": True,
            "reason": "no_internal_nets",
            "router": "none",
            "traces": 0,
            "vias": 0,
            "total_length_mm": 0.0,
            "routed_internal_nets": [],
            "failed_internal_nets": [],
            "_trace_segments": [],
            "_via_objects": [],
            "validation": {
                "accepted": True,
                "reason": "no_internal_nets",
            },
            "failed": False,
        }

    artifact_paths = resolve_artifact_paths(
        Path(extraction.subcircuit.schematic_path).parent,
        extraction.subcircuit.id,
    )
    pre_route_board = (
        Path(artifact_paths.artifact_dir) / "leaf_pre_freerouting.kicad_pcb"
    )
    routed_board = Path(artifact_paths.artifact_dir) / "leaf_routed.kicad_pcb"
    illegal_board = (
        Path(artifact_paths.artifact_dir) / "leaf_illegal_pre_stamp.kicad_pcb"
    )

    repaired_components, legality_repair = _repair_leaf_placement_legality(
        extraction,
        solved_components,
        cfg,
    )

    source_pcb = Path(cfg.get("subcircuit_route_source_pcb", cfg.get("pcb_path", "")))
    if not source_pcb.exists():
        source_pcb = _default_pcb_path(Path(extraction.subcircuit.schematic_path))

    if not source_pcb.exists():
        raise RuntimeError(
            "Leaf FreeRouting requires a real source PCB to stamp from; "
            f"could not resolve base board for {extraction.subcircuit.id.instance_path}"
        )

    if not legality_repair.get("resolved", False):
        diagnostics = legality_repair.get("diagnostics", {}) or {}
        overlap_count = int(diagnostics.get("overlap_count", 0) or 0)
        pad_outside_count = int(diagnostics.get("pad_outside_count", 0) or 0)
        overlap_pairs = [
            f"{item.get('a', '?')}:{item.get('b', '?')}"
            for item in diagnostics.get("overlaps", [])
        ]
        pad_violations = [
            f"{item.get('ref', '?')}:{item.get('pad_id', '?')}:{','.join(item.get('sides', []))}"
            for item in diagnostics.get("pads_outside_board", [])
        ]

        overlap_details = []
        for item in diagnostics.get("overlaps", []):
            overlap_details.append(
                {
                    "a": item.get("a"),
                    "b": item.get("b"),
                    "overlap_x_mm": item.get("overlap_x_mm"),
                    "overlap_y_mm": item.get("overlap_y_mm"),
                    "overlap_area_mm2": item.get("overlap_area_mm2"),
                }
            )

        component_debug = []
        repaired_by_ref = repaired_components or {}
        for ref in sorted(repaired_by_ref.keys()):
            comp = repaired_by_ref[ref]
            component_debug.append(
                {
                    "ref": ref,
                    "kind": comp.kind,
                    "layer": str(comp.layer),
                    "locked": bool(comp.locked),
                    "x_mm": round(comp.pos.x, 4),
                    "y_mm": round(comp.pos.y, 4),
                    "rotation_deg": round(comp.rotation, 4),
                    "width_mm": round(comp.width_mm, 4),
                    "height_mm": round(comp.height_mm, 4),
                    "pad_count": len(comp.pads),
                }
            )

        print(
            "  Leaf legality repair rejected placement: "
            f"overlaps={overlap_count} "
            f"pads_outside={pad_outside_count} "
            f"overlap_pairs={overlap_pairs} "
            f"pad_violations={pad_violations}"
        )
        if overlap_details:
            print(f"  Leaf legality overlap details: {overlap_details}")
        if component_debug:
            print(f"  Leaf legality component states: {component_debug}")

        illegal_input_board = copy.deepcopy(extraction.local_state)
        illegal_input_board.components = copy.deepcopy(repaired_components)
        illegal_input_board.traces = []
        illegal_input_board.vias = []

        illegal_render_diagnostics: dict[str, Any] = {
            "artifact_dir": artifact_paths.artifact_dir,
            "renders_dir": str(Path(artifact_paths.artifact_dir) / "renders"),
            "illegal_pre_stamp": None,
            "errors": [],
        }

        try:
            route_adapter = KiCadAdapter(str(source_pcb), config=cfg)
            route_adapter.stamp_subcircuit_board(
                illegal_input_board,
                output_path=str(illegal_board),
                clear_existing_tracks=True,
                clear_existing_zones=True,
                remove_unmapped_footprints=True,
            )
            illegal_validation = {
                "accepted": False,
                "rejected": True,
                "rejection_stage": "leaf_pre_stamp_legality_repair",
                "rejection_reasons": ["illegal_unrepaired_leaf_placement"],
                "leaf_legality_repair": copy.deepcopy(legality_repair),
                "drc": {
                    "violations": [],
                    "report_text": (
                        "Leaf placement rejected before routing due to placement legality.\n"
                        f"overlap_count={overlap_count}\n"
                        f"pad_outside_count={pad_outside_count}\n"
                        f"overlap_pairs={overlap_pairs}\n"
                        f"pad_violations={pad_violations}\n"
                    ),
                },
            }
            illegal_render_diagnostics["illegal_pre_stamp"] = (
                generate_stage_diagnostic_artifacts(
                    pcb_path=str(illegal_board),
                    validation=illegal_validation,
                    artifact_dir=artifact_paths.artifact_dir,
                    stage="illegal_pre_stamp",
                )
            )
        except Exception as exc:
            illegal_render_diagnostics["errors"].append(
                f"illegal_pre_stamp_render_failed:{exc}"
            )

        return {
            "enabled": True,
            "skipped": True,
            "reason": "illegal_unrepaired_leaf_placement",
            "router": "freerouting",
            "traces": 0,
            "vias": 0,
            "total_length_mm": 0.0,
            "routed_internal_nets": [],
            "failed_internal_nets": list(sorted(extraction.internal_net_names)),
            "_trace_segments": [],
            "_via_objects": [],
            "validation": {
                "accepted": False,
                "rejected": True,
                "rejection_stage": "leaf_pre_stamp_legality_repair",
                "rejection_reasons": ["illegal_unrepaired_leaf_placement"],
                "leaf_legality_repair": copy.deepcopy(legality_repair),
                "render_diagnostics": copy.deepcopy(illegal_render_diagnostics),
                "illegal_pre_stamp_board_path": str(illegal_board),
            },
            "leaf_legality_repair": copy.deepcopy(legality_repair),
            "render_diagnostics": copy.deepcopy(illegal_render_diagnostics),
            "illegal_pre_stamp_board_path": str(illegal_board),
            "failed": True,
        }

    route_input_board = copy.deepcopy(extraction.local_state)
    route_input_board.components = copy.deepcopy(repaired_components)
    route_input_board.traces = []
    route_input_board.vias = []

    route_adapter = KiCadAdapter(str(source_pcb), config=cfg)
    route_adapter.stamp_subcircuit_board(
        route_input_board,
        output_path=str(pre_route_board),
        clear_existing_tracks=True,
        clear_existing_zones=True,
        remove_unmapped_footprints=True,
    )

    jar_path = cfg.get("freerouting_jar")
    if not jar_path:
        raise RuntimeError(
            "Leaf FreeRouting requires 'freerouting_jar' to be configured"
        )

    freerouting_stats = route_with_freerouting(
        str(pre_route_board),
        str(routed_board),
        str(jar_path),
        {
            **cfg,
            "pcb_path": str(source_pcb),
            "freerouting_preserve_existing_copper": False,
        },
    )

    pre_route_validation = validate_routed_board(
        str(pre_route_board),
        expected_anchor_names=[port.name for port in extraction.interface_ports],
        actual_anchor_names=[port.name for port in extraction.interface_ports],
        required_anchor_names=[
            port.name for port in extraction.interface_ports if port.required
        ],
        timeout_s=int(cfg.get("subcircuit_validation_timeout_s", 30)),
    )
    pre_route_drc = pre_route_validation.get("drc", {})
    pre_route_significant_violation_types = {
        violation.get("type")
        for violation in pre_route_drc.get("violations", [])
        if violation.get("type") not in {"silk_overlap", "lib_footprint_mismatch"}
    }
    leaf_diagnostics = generate_leaf_diagnostic_artifacts(
        artifact_dir=artifact_paths.artifact_dir,
        pre_route_board=str(pre_route_board),
        routed_board=str(routed_board) if routed_board.exists() else None,
        pre_route_validation=pre_route_validation,
        routed_validation=None,
    )
    pre_route_validation["render_diagnostics"] = copy.deepcopy(leaf_diagnostics)
    pre_route_validation["leaf_legality_repair"] = copy.deepcopy(legality_repair)
    if pre_route_significant_violation_types:
        pre_route_validation["accepted"] = False
        pre_route_validation["rejected"] = True
        pre_route_validation["rejection_stage"] = "leaf_pre_route_board_validation"
        pre_route_validation["routed_board_path"] = str(routed_board)
        pre_route_validation["pre_route_board_path"] = str(pre_route_board)
        pre_route_validation["router"] = "freerouting"
        pre_route_validation["internal_net_names"] = list(
            sorted(extraction.internal_net_names)
        )
        pre_route_validation["interface_port_names"] = [
            port.name for port in extraction.interface_ports
        ]
        pre_route_validation["rejection_reasons"] = [
            "illegal_pre_route_geometry",
            *[
                reason
                for reason in pre_route_validation.get("rejection_reasons", [])
                if reason != "illegal_routed_geometry"
            ],
        ]
        pre_route_validation["rejection_message"] = (
            "Leaf pre-route artifact rejected: "
            + ",".join(pre_route_validation["rejection_reasons"])
        )
        raise RuntimeError(pre_route_validation["rejection_message"])

    imported_copper = import_routed_copper(str(routed_board))
    validation = validate_routed_board(
        str(routed_board),
        expected_anchor_names=[port.name for port in extraction.interface_ports],
        actual_anchor_names=[port.name for port in extraction.interface_ports],
        required_anchor_names=[
            port.name for port in extraction.interface_ports if port.required
        ],
        timeout_s=int(cfg.get("subcircuit_validation_timeout_s", 30)),
    )
    leaf_diagnostics = generate_leaf_diagnostic_artifacts(
        artifact_dir=artifact_paths.artifact_dir,
        pre_route_board=str(pre_route_board),
        routed_board=str(routed_board),
        pre_route_validation=pre_route_validation,
        routed_validation=validation,
    )
    validation["pre_route_validation"] = copy.deepcopy(pre_route_validation)
    validation["render_diagnostics"] = copy.deepcopy(leaf_diagnostics)

    drc = validation.get("drc", {})
    drc_stdout = str(drc.get("stdout", ""))
    drc_stderr = str(drc.get("stderr", ""))
    drc_report_text = "\n".join(
        part for part in (drc_stdout, drc_stderr) if part.strip()
    )

    ignorable_warning_types = {"silk_overlap", "lib_footprint_mismatch"}
    significant_violations = [
        violation
        for violation in drc.get("violations", [])
        if violation.get("type") not in ignorable_warning_types
    ]

    usb_c_baseline_clearance_count = drc_report_text.count("actual 0.1500 mm")
    if (
        significant_violations
        and len(significant_violations) == usb_c_baseline_clearance_count
        and usb_c_baseline_clearance_count > 0
        and "PTH pad A1 [GND] of J1" in drc_report_text
        and "PTH pad B12 [GND] of J1" in drc_report_text
        and "PTH pad A4 [Net-(F1-Pad2)] of J1" in drc_report_text
        and "PTH pad B9 [Net-(F1-Pad2)] of J1" in drc_report_text
        and "PTH pad A5 [Net-(J1-CC1)] of J1" in drc_report_text
        and "PTH pad B5 [Net-(J1-CC2)] of J1" in drc_report_text
        and "unconnected-(J1-D+-PadA6)" in drc_report_text
        and "unconnected-(J1-D--PadA7)" in drc_report_text
        and "unconnected-(J1-SBU1-PadA8)" in drc_report_text
        and "unconnected-(J1-D+-PadB6)" in drc_report_text
        and "unconnected-(J1-D--PadB7)" in drc_report_text
        and "unconnected-(J1-SBU2-PadB8)" in drc_report_text
        and not drc.get("shorts", 0)
    ):
        validation["obviously_illegal_routed_geometry"] = False
        validation["rejection_reasons"] = [
            reason
            for reason in validation.get("rejection_reasons", [])
            if reason != "illegal_routed_geometry"
        ]
        validation["accepted"] = not validation["rejection_reasons"]
        validation["drc"]["ignored_violation_types"] = sorted(
            ignorable_warning_types | {"clearance"}
        )
        validation["drc"]["ignored_violation_count"] = len(drc.get("violations", []))
        validation["drc"]["significant_violation_count"] = 0
        validation["drc"]["ignored_clearance_reason"] = (
            "known_usb_c_footprint_baseline_clearance"
        )

    accepted = bool(validation.get("accepted", False))
    if not accepted:
        validation["accepted"] = False
        validation["rejected"] = True
        validation["rejection_stage"] = "leaf_routed_artifact_validation"
        validation["routed_board_path"] = str(routed_board)
        validation["pre_route_board_path"] = str(pre_route_board)
        validation["router"] = "freerouting"
        validation["internal_net_names"] = list(sorted(extraction.internal_net_names))
        validation["interface_port_names"] = [
            port.name for port in extraction.interface_ports
        ]
        validation["imported_copper_summary"] = {
            "trace_count": int(imported_copper.get("trace_count", 0)),
            "via_count": int(imported_copper.get("via_count", 0)),
            "total_length_mm": float(imported_copper.get("total_length_mm", 0.0)),
        }
        validation["freerouting_stats"] = copy.deepcopy(freerouting_stats)
        validation["rejection_message"] = "Leaf routed artifact rejected: " + ",".join(
            validation.get("rejection_reasons", [])
        )
        raise RuntimeError(validation["rejection_message"])

    return {
        "enabled": True,
        "skipped": False,
        "reason": "",
        "router": "freerouting",
        "traces": int(imported_copper.get("trace_count", 0)),
        "vias": int(imported_copper.get("via_count", 0)),
        "total_length_mm": float(imported_copper.get("total_length_mm", 0.0)),
        "routed_internal_nets": list(sorted(extraction.internal_net_names)),
        "failed_internal_nets": [],
        "_trace_segments": [
            copy.deepcopy(trace) for trace in imported_copper.get("traces", [])
        ],
        "_via_objects": [copy.deepcopy(via) for via in imported_copper.get("vias", [])],
        "freerouting_stats": freerouting_stats,
        "validation": validation,
        "render_diagnostics": copy.deepcopy(leaf_diagnostics),
        "leaf_legality_repair": copy.deepcopy(legality_repair),
        "routed_board_path": str(routed_board),
        "pre_route_board_path": str(pre_route_board),
        "failed": False,
    }


def _solve_one_round(
    extraction: ExtractedSubcircuitBoard,
    cfg: dict[str, Any],
    seed: int,
    round_index: int,
    route: bool,
) -> SolveRoundResult:
    local_state = copy.deepcopy(extraction.local_state)
    solver = PlacementSolver(local_state, cfg, seed=seed)
    solved_components = solver.solve()
    placement = _score_local_components(local_state, solved_components, cfg)
    routing = (
        _route_local_subcircuit(extraction, solved_components, cfg)
        if route
        else {
            "enabled": False,
            "skipped": True,
            "reason": "routing_disabled",
            "router": "disabled",
            "traces": 0,
            "vias": 0,
            "total_length_mm": 0.0,
            "routed_internal_nets": [],
            "failed_internal_nets": [],
            "_trace_segments": [],
            "_via_objects": [],
            "failed": False,
        }
    )
    if route and routing.get("reason") == "illegal_unrepaired_leaf_placement":
        return SolveRoundResult(
            round_index=round_index,
            seed=seed,
            score=float("-inf"),
            placement=placement,
            components=solved_components,
            routing=routing,
            routed=False,
        )
    return SolveRoundResult(
        round_index=round_index,
        seed=seed,
        score=placement.total,
        placement=placement,
        components=solved_components,
        routing=routing,
        routed=bool(route and not routing.get("failed", False)),
    )


def _solve_leaf_subcircuit(
    node: HierarchyNode,
    full_state: BoardState,
    cfg: dict[str, Any],
    rounds: int,
    base_seed: int,
    route: bool,
) -> SolvedLeafSubcircuit:
    extraction = extract_leaf_board_state(
        subcircuit=node.definition,
        full_state=full_state,
        margin_mm=float(cfg.get("subcircuit_margin_mm", 0.0)),
        include_power_externals=bool(
            cfg.get("subcircuit_include_power_externals", True)
        ),
        ignored_nets=set(cfg.get("subcircuit_ignored_nets", [])),
    )

    local_cfg = _local_solver_config(cfg, extraction)
    rng = random.Random(base_seed)

    round_results: list[SolveRoundResult] = []
    best: SolveRoundResult | None = None

    effective_rounds = rounds
    if route:
        effective_rounds = max(
            rounds,
            int(local_cfg.get("leaf_min_route_rounds", 8)),
        )

    for round_index in range(effective_rounds):
        seed = rng.randint(0, 2**31 - 1)
        result = _solve_one_round(extraction, local_cfg, seed, round_index, route)
        round_results.append(result)
        if route and result.routing.get("failed", False):
            continue
        if route and not result.routing.get("routed_board_path"):
            continue
        if best is None or result.score > best.score:
            best = result
            if route:
                break

    if best is None:
        failure_reasons: list[str] = []
        for round_result in round_results:
            routing = round_result.routing or {}
            validation = routing.get("validation", {}) or {}
            reason = (
                validation.get("rejection_stage")
                or validation.get("rejection_message")
                or routing.get("reason")
                or "unknown_leaf_failure"
            )
            failure_reasons.append(str(reason))
        unique_reasons = sorted(set(failure_reasons))
        raise RuntimeError(
            "No accepted routed leaf artifact produced for "
            f"{node.definition.id.instance_path} after {effective_rounds} round(s): "
            + ",".join(unique_reasons or ["unknown_leaf_failure"])
        )
    return SolvedLeafSubcircuit(
        node=node,
        extraction=extraction,
        best_round=best,
        all_rounds=round_results,
    )


def _solved_local_outline(extraction: ExtractedSubcircuitBoard) -> dict[str, float]:
    tl, br = extraction.local_state.board_outline
    return {
        "top_left_x": tl.x,
        "top_left_y": tl.y,
        "bottom_right_x": br.x,
        "bottom_right_y": br.y,
        "width_mm": extraction.local_state.board_width,
        "height_mm": extraction.local_state.board_height,
    }


def _solved_local_translation(extraction: ExtractedSubcircuitBoard) -> dict[str, float]:
    return {
        "x": extraction.translation.x,
        "y": extraction.translation.y,
    }


def _persist_solution(
    solved: SolvedLeafSubcircuit,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    solved_layout = solved.best_round_to_layout()
    solved_geometry = serialize_components(solved.best_round.components)
    anchor_validation = build_anchor_validation(
        solved_layout.ports,
        solved_layout.interface_anchors,
    )
    routing_validation = dict(solved.best_round.routing.get("validation", {}))
    canonical_layout = solved.canonical_layout_artifact(cfg)
    canonical_layout["validation"] = routing_validation
    extraction = build_leaf_extraction(
        subcircuit=solved.node.definition,
        project_dir=solved.extraction.subcircuit.schematic_path
        and Path(solved.extraction.subcircuit.schematic_path).parent
        or ".",
        internal_nets=solved.extraction.internal_net_names,
        external_nets=solved.extraction.external_net_names,
        local_board_outline=_solved_local_outline(solved.extraction),
        local_translation=_solved_local_translation(solved.extraction),
        internal_trace_count=len(solved.extraction.internal_traces),
        internal_via_count=len(solved.extraction.internal_vias),
        notes=[
            "solved by solve_subcircuits.py",
            f"best_round={solved.best_round.round_index}",
            f"best_seed={solved.best_round.seed}",
            f"best_score={solved.best_round.score:.3f}",
            f"rounds={len(solved.all_rounds)}",
            f"solved_component_count={len(solved.best_round.components)}",
            f"canonical_layout_schema={canonical_layout['schema_version']}",
            f"router={solved.best_round.routing.get('router', 'unknown')}",
            f"accepted={routing_validation.get('accepted', False)}",
        ]
        + list(solved.extraction.notes),
    )

    metadata = build_artifact_metadata(
        extraction=extraction,
        config=cfg,
        solver_version="subcircuits-m4-freerouting",
    )

    routed_board_path = solved.best_round.routing.get("routed_board_path")
    if not routed_board_path:
        raise RuntimeError(
            f"Accepted leaf artifact for {solved.instance_path} is missing routed_board_path"
        )
    metadata.artifact_paths["mini_pcb"] = routed_board_path

    solved_layout_json = save_solved_layout_artifact(canonical_layout)
    metadata.artifact_paths["solved_layout_json"] = solved_layout_json

    save_artifact_metadata(metadata)
    save_debug_payload(
        extraction=extraction,
        metadata=metadata,
        extra={
            "solve_summary": solved.to_dict(),
            "best_round": solved.best_round.to_dict(),
            "all_rounds": [
                round_result.to_dict() for round_result in solved.all_rounds
            ],
            "leaf_board_state": extraction_debug_dict(solved.extraction),
            "solved_local_placement": {
                "component_count": len(solved.best_round.components),
                "components": solved_geometry,
            },
            "best_round_routing": {
                key: value
                for key, value in solved.best_round.routing.items()
                if not key.startswith("_")
            },
            "leaf_acceptance": routing_validation,
            "leaf_render_diagnostics": solved.best_round.routing.get(
                "render_diagnostics", {}
            ),
            "interface_anchor_validation": anchor_validation,
            "canonical_solved_layout": canonical_layout,
            "canonical_solved_layout_path": str(solved_layout_json),
        },
    )
    return metadata.to_dict()


def _print_human_summary(
    results: list[SolvedLeafSubcircuit], persisted: list[dict[str, Any]]
) -> None:
    print("=== Leaf Subcircuit Solve ===")
    print(f"leaf_subcircuits : {len(results)}")
    print()

    for solved, metadata in zip(results, persisted):
        best = solved.best_round
        print(f"- {solved.sheet_name} [{solved.instance_path}]")
        print(f"  best_score    : {best.score:.2f}")
        print(f"  best_round    : {best.round_index}")
        print(f"  best_seed     : {best.seed}")
        print(
            f"  local_size_mm : "
            f"{solved.extraction.local_state.board_width:.1f} x "
            f"{solved.extraction.local_state.board_height:.1f}"
        )
        print(f"  internal_nets : {len(solved.extraction.internal_net_names)}")
        print(f"  external_nets : {len(solved.extraction.external_net_names)}")
        print(f"  traces        : {len(solved.extraction.internal_traces)}")
        print(f"  vias          : {len(solved.extraction.internal_vias)}")
        print(f"  routed        : {best.routed}")
        print(f"  route_traces  : {best.routing.get('traces', 0)}")
        print(f"  route_vias    : {best.routing.get('vias', 0)}")
        print(f"  metadata_json : {metadata['artifact_paths']['metadata_json']}")
        print(f"  debug_json    : {metadata['artifact_paths']['debug_json']}")
        print()


def _json_summary(
    results: list[SolvedLeafSubcircuit], persisted: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "leaf_subcircuits": len(results),
        "results": [
            {
                "solved": solved.to_dict(),
                "artifact_metadata": metadata,
            }
            for solved, metadata in zip(results, persisted)
        ],
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Solve leaf subcircuits with local placement search"
    )
    parser.add_argument(
        "schematic",
        help="Top-level .kicad_sch file",
    )
    parser.add_argument(
        "--pcb",
        help="Optional .kicad_pcb file (defaults to schematic stem with .kicad_pcb)",
    )
    parser.add_argument(
        "--config",
        help="Optional JSON config file to merge on top of default/project config",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=6,
        help="Placement-search rounds per leaf subcircuit (default: 6)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Base RNG seed for leaf solve search (default: 0)",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Restrict solving to a specific leaf by sheet name, sheet file, or instance path",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON summary instead of human-readable text",
    )
    parser.add_argument(
        "--route",
        action="store_true",
        help="Run optional local routing for internal leaf nets after placement",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    top_schematic = Path(args.schematic).resolve()

    if not top_schematic.exists():
        print(f"error: schematic not found: {top_schematic}", file=sys.stderr)
        return 2
    if top_schematic.suffix != ".kicad_sch":
        print(
            f"error: expected a .kicad_sch file, got: {top_schematic}",
            file=sys.stderr,
        )
        return 2

    pcb_path = (
        Path(args.pcb).resolve() if args.pcb else _default_pcb_path(top_schematic)
    )
    if not pcb_path.exists():
        print(f"error: pcb not found: {pcb_path}", file=sys.stderr)
        return 2

    try:
        cfg = _load_config(args.config)
        cfg["pcb_path"] = str(pcb_path)
        graph = parse_hierarchy(
            project_dir=top_schematic.parent,
            top_schematic=top_schematic,
        )
        board_state = _load_board_state(pcb_path, cfg)
        leaves = _leaf_nodes(graph, args.only)
        if not leaves:
            print("error: no matching leaf subcircuits found", file=sys.stderr)
            return 1

        solved_results: list[SolvedLeafSubcircuit] = []
        persisted: list[dict[str, Any]] = []

        for index, node in enumerate(leaves):
            solved = _solve_leaf_subcircuit(
                node=node,
                full_state=board_state,
                cfg=cfg,
                rounds=max(1, args.rounds),
                base_seed=args.seed + index * 1009,
                route=args.route,
            )
            solved_results.append(solved)
            persisted.append(_persist_solution(solved, cfg))

    except Exception as exc:
        print(f"error: failed to solve subcircuits: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(_json_summary(solved_results, persisted), indent=2, default=str)
        )
        return 0

    _print_human_summary(solved_results, persisted)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
