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
from autoplacer.brain.types import BoardState, Component, PlacementScore
from autoplacer.config import DEFAULT_CONFIG, LLUPS_CONFIG, load_project_config
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
            "routing": dict(self.routing),
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
        return SubCircuitLayout(
            subcircuit_id=self.node.definition.id,
            components=copy.deepcopy(self.best_round.components),
            traces=[copy.deepcopy(trace) for trace in self.extraction.internal_traces],
            vias=[copy.deepcopy(via) for via in self.extraction.internal_vias],
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
                f"routing={json.dumps(self.best_round.routing, sort_keys=True)}",
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
    cfg["component_zones"] = {}
    cfg["ic_groups"] = {}
    cfg["group_labels"] = {}
    cfg["subcircuit_route_internal_nets"] = bool(
        base_cfg.get("subcircuit_route_internal_nets", False)
    )

    cfg["board_width_mm"] = extraction.local_state.board_width
    cfg["board_height_mm"] = extraction.local_state.board_height

    cfg.setdefault("placement_clearance_mm", 2.0)
    cfg.setdefault("edge_margin_mm", 2.0)
    cfg.setdefault("placement_grid_mm", 0.5)
    cfg.setdefault("max_placement_iterations", 180)
    cfg.setdefault("placement_convergence_threshold", 0.35)
    cfg.setdefault("orderedness", 0.25)
    cfg.setdefault("randomize_group_layout", True)
    cfg.setdefault("scatter_mode", "random")

    return cfg


def _score_local_components(
    local_state: BoardState,
    components: dict[str, Component],
    cfg: dict[str, Any],
) -> PlacementScore:
    work_state = copy.copy(local_state)
    work_state.components = components
    return PlacementScorer(work_state, cfg).score()


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
            "router": "lightweight_internal",
            "traces": 0,
            "vias": 0,
            "total_length_mm": 0.0,
            "routed_internal_nets": [],
            "failed_internal_nets": [],
            "failed": False,
        }

    from autoplacer.brain.subcircuit_solver import route_leaf_internal_nets

    routing = route_leaf_internal_nets(extraction, solved_components, cfg)
    return {
        "enabled": True,
        "skipped": False,
        "reason": "",
        "router": "lightweight_internal",
        "traces": routing.trace_count,
        "vias": routing.via_count,
        "total_length_mm": routing.total_length_mm,
        "routed_internal_nets": list(routing.routed_internal_nets),
        "failed_internal_nets": list(routing.failed_internal_nets),
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
            "failed": False,
        }
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
        margin_mm=float(cfg.get("subcircuit_margin_mm", 5.0)),
        include_power_externals=bool(
            cfg.get("subcircuit_include_power_externals", True)
        ),
        ignored_nets=set(cfg.get("subcircuit_ignored_nets", [])),
    )

    local_cfg = _local_solver_config(cfg, extraction)
    rng = random.Random(base_seed)

    round_results: list[SolveRoundResult] = []
    best: SolveRoundResult | None = None

    for round_index in range(rounds):
        seed = rng.randint(0, 2**31 - 1)
        result = _solve_one_round(extraction, local_cfg, seed, round_index, route)
        round_results.append(result)
        if best is None or result.score > best.score:
            best = result

    assert best is not None
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
    canonical_layout = solved.canonical_layout_artifact(cfg)
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
        ]
        + list(solved.extraction.notes),
    )

    metadata = build_artifact_metadata(
        extraction=extraction,
        config=cfg,
        solver_version="subcircuits-m3-placement",
    )

    artifact_paths = resolve_artifact_paths(
        extraction.project_dir,
        solved.node.definition.id,
    )
    mini_board_path = export_subcircuit_board(
        solved_layout,
        artifact_paths.mini_pcb,
        ExportOptions(
            title="Solved Leaf Subcircuit",
            comment="Generated by solve_subcircuits.py",
        ),
    )
    metadata.artifact_paths["mini_pcb"] = mini_board_path

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
            "best_round_routing": dict(solved.best_round.routing),
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
