#!/usr/bin/env python3
"""Compose solved subcircuits into a parent composition state.

This CLI is the first parent-composition entrypoint for the subcircuits
redesign. It loads solved leaf artifacts from `.experiments/subcircuits`,
instantiates them as rigid modules, applies translation/rotation transforms,
and emits a machine-readable composition snapshot.

Current scope:
- load canonical solved subcircuit artifacts
- instantiate rigid child modules
- apply translation + rotation transforms
- build a parent composition state summary
- emit JSON and optional saved composition snapshot
- support simple placement modes for initial composition experiments

This command does NOT yet:
- optimize parent placement
- route inter-subcircuit nets
- stamp the composition back into a real KiCad board
- recurse through non-leaf schematic hierarchy automatically

It is intended as a composition-side scaffold so later milestones can build:
- parent-level placement optimization
- interconnect routing
- recursive upward propagation
- final top-level board assembly
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from autoplacer.brain.hierarchy_parser import parse_hierarchy

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from autoplacer.brain.subcircuit_composer import (
    ChildArtifactPlacement,
    build_parent_composition,
)
from autoplacer.brain.subcircuit_instances import (
    artifact_debug_dict,
    artifact_summary,
    load_solved_artifacts,
    transform_loaded_artifact,
    transformed_debug_dict,
    transformed_summary,
)
from autoplacer.brain.types import Point, SubCircuitDefinition, SubCircuitId


@dataclass(slots=True)
class CompositionEntry:
    """One rigid child instance inside a parent composition."""

    artifact_dir: str
    sheet_name: str
    instance_path: str
    origin: Point
    rotation: float
    transformed_bbox: tuple[float, float]
    component_count: int
    trace_count: int
    via_count: int
    anchor_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_dir": self.artifact_dir,
            "sheet_name": self.sheet_name,
            "instance_path": self.instance_path,
            "origin": {
                "x": self.origin.x,
                "y": self.origin.y,
            },
            "rotation": self.rotation,
            "transformed_bbox": {
                "width_mm": self.transformed_bbox[0],
                "height_mm": self.transformed_bbox[1],
            },
            "component_count": self.component_count,
            "trace_count": self.trace_count,
            "via_count": self.via_count,
            "anchor_count": self.anchor_count,
        }


@dataclass(slots=True)
class ParentCompositionState:
    """Machine-readable parent composition snapshot."""

    project_dir: str
    mode: str
    spacing_mm: float
    entries: list[CompositionEntry] = field(default_factory=list)
    bounding_box: tuple[Point, Point] = field(
        default_factory=lambda: (Point(0.0, 0.0), Point(0.0, 0.0))
    )
    parent_sheet_name: str = "COMPOSED_PARENT"
    parent_instance_path: str = "/COMPOSED_PARENT"
    component_count: int = 0
    trace_count: int = 0
    via_count: int = 0
    interconnect_net_count: int = 0
    inferred_interconnect_net_count: int = 0
    routed_interconnect_net_count: int = 0
    failed_interconnect_net_count: int = 0
    score_total: float = 0.0
    score_breakdown: dict[str, float] = field(default_factory=dict)
    score_notes: list[str] = field(default_factory=list)
    composition_notes: list[str] = field(default_factory=list)

    @property
    def width_mm(self) -> float:
        tl, br = self.bounding_box
        return max(0.0, br.x - tl.x)

    @property
    def height_mm(self) -> float:
        tl, br = self.bounding_box
        return max(0.0, br.y - tl.y)

    def to_dict(self) -> dict[str, Any]:
        tl, br = self.bounding_box
        return {
            "project_dir": self.project_dir,
            "mode": self.mode,
            "spacing_mm": self.spacing_mm,
            "parent_sheet_name": self.parent_sheet_name,
            "parent_instance_path": self.parent_instance_path,
            "entry_count": len(self.entries),
            "component_count": self.component_count,
            "trace_count": self.trace_count,
            "via_count": self.via_count,
            "interconnect_net_count": self.interconnect_net_count,
            "inferred_interconnect_net_count": self.inferred_interconnect_net_count,
            "routed_interconnect_net_count": self.routed_interconnect_net_count,
            "failed_interconnect_net_count": self.failed_interconnect_net_count,
            "score_total": self.score_total,
            "score_breakdown": dict(self.score_breakdown),
            "score_notes": list(self.score_notes),
            "composition_notes": list(self.composition_notes),
            "bounding_box": {
                "top_left": {"x": tl.x, "y": tl.y},
                "bottom_right": {"x": br.x, "y": br.y},
                "width_mm": self.width_mm,
                "height_mm": self.height_mm,
            },
            "entries": [entry.to_dict() for entry in self.entries],
        }


def _discover_artifact_dirs(project_dir: Path) -> list[Path]:
    """Find solved subcircuit artifact directories under a project."""
    root = project_dir / ".experiments" / "subcircuits"
    if not root.exists():
        return []

    artifact_dirs: list[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        metadata = child / "metadata.json"
        debug = child / "debug.json"
        if metadata.exists() and debug.exists():
            artifact_dirs.append(child)
    return artifact_dirs


def _resolve_artifact_dirs(
    project_dir: Path | None,
    artifact_args: list[str],
) -> list[str | Path]:
    """Resolve artifact directories from CLI inputs."""
    resolved: list[str | Path] = []

    for artifact in artifact_args:
        path = Path(artifact).resolve()
        if path not in resolved:
            resolved.append(path)

    if project_dir is not None:
        for path in _discover_artifact_dirs(project_dir.resolve()):
            if path not in resolved:
                resolved.append(path)

    return resolved


def _filter_loaded_artifacts(loaded_artifacts, only: list[str]) -> list:
    """Filter loaded artifacts by sheet name, file name, or instance path."""
    if not only:
        return list(loaded_artifacts)

    only_set = {item.strip().lower() for item in only if item.strip()}
    filtered = []
    for artifact in loaded_artifacts:
        candidates = {
            artifact.layout.subcircuit_id.sheet_name.lower(),
            artifact.layout.subcircuit_id.sheet_file.lower(),
            artifact.layout.subcircuit_id.instance_path.lower(),
        }
        if candidates & only_set:
            filtered.append(artifact)
    return filtered


def _select_parent_definition(
    project_dir: Path | None,
    parent_selector: str | None,
) -> SubCircuitDefinition | None:
    """Resolve a real parent definition from schematic hierarchy."""
    if project_dir is None or not parent_selector:
        return None

    graph = parse_hierarchy(project_dir=project_dir.resolve())
    selector = parent_selector.strip().lower()
    if not selector:
        return None

    root_candidates = {
        graph.root.id.sheet_name.lower(),
        graph.root.id.sheet_file.lower(),
        graph.root.id.instance_path.lower(),
    }
    if selector in root_candidates:
        return graph.root.definition

    for node in graph.non_leaf_nodes():
        if node.id.instance_path == "/":
            continue
        candidates = {
            node.id.sheet_name.lower(),
            node.id.sheet_file.lower(),
            node.id.instance_path.lower(),
        }
        if selector in candidates:
            return node.definition

    raise ValueError(f"Unknown parent subcircuit: {parent_selector}")


def _filter_artifacts_for_parent(
    loaded_artifacts,
    parent_definition: SubCircuitDefinition | None,
) -> list:
    """Restrict artifacts to direct children of the selected parent."""
    if parent_definition is None:
        return list(loaded_artifacts)

    child_paths = {child_id.instance_path for child_id in parent_definition.child_ids}
    return [
        artifact
        for artifact in loaded_artifacts
        if artifact.layout.subcircuit_id.instance_path in child_paths
    ]


def _compose_artifacts(
    loaded_artifacts,
    *,
    mode: str,
    spacing_mm: float,
    rotation_step_deg: float,
    parent_definition: SubCircuitDefinition | None = None,
) -> tuple[ParentCompositionState, list[dict[str, Any]]]:
    """Compose loaded artifacts into a parent composition snapshot."""
    entries: list[CompositionEntry] = []
    transformed_payloads: list[dict[str, Any]] = []
    child_artifact_placements: list[ChildArtifactPlacement] = []

    if mode == "row":
        cursor_x = 0.0
        cursor_y = 0.0

        for index, artifact in enumerate(loaded_artifacts):
            rotation = (index * rotation_step_deg) % 360.0
            origin = Point(cursor_x, cursor_y)
            transformed = transform_loaded_artifact(
                artifact,
                origin=origin,
                rotation=rotation,
            )

            entry = CompositionEntry(
                artifact_dir=artifact.artifact_dir,
                sheet_name=artifact.sheet_name,
                instance_path=artifact.instance_path,
                origin=origin,
                rotation=rotation,
                transformed_bbox=transformed.instance.transformed_bbox,
                component_count=len(transformed.transformed_components),
                trace_count=len(transformed.transformed_traces),
                via_count=len(transformed.transformed_vias),
                anchor_count=len(transformed.transformed_anchors),
            )
            entries.append(entry)
            child_artifact_placements.append(
                ChildArtifactPlacement(
                    artifact=artifact,
                    origin=origin,
                    rotation=rotation,
                )
            )
            transformed_payloads.append(
                {
                    "artifact": artifact_debug_dict(artifact),
                    "transformed": transformed_debug_dict(transformed),
                    "summary": transformed_summary(transformed),
                }
            )

            cursor_x += transformed.instance.transformed_bbox[0] + spacing_mm

    elif mode == "column":
        cursor_x = 0.0
        cursor_y = 0.0

        for index, artifact in enumerate(loaded_artifacts):
            rotation = (index * rotation_step_deg) % 360.0
            origin = Point(cursor_x, cursor_y)
            transformed = transform_loaded_artifact(
                artifact,
                origin=origin,
                rotation=rotation,
            )

            entry = CompositionEntry(
                artifact_dir=artifact.artifact_dir,
                sheet_name=artifact.sheet_name,
                instance_path=artifact.instance_path,
                origin=origin,
                rotation=rotation,
                transformed_bbox=transformed.instance.transformed_bbox,
                component_count=len(transformed.transformed_components),
                trace_count=len(transformed.transformed_traces),
                via_count=len(transformed.transformed_vias),
                anchor_count=len(transformed.transformed_anchors),
            )
            entries.append(entry)
            child_artifact_placements.append(
                ChildArtifactPlacement(
                    artifact=artifact,
                    origin=origin,
                    rotation=rotation,
                )
            )
            transformed_payloads.append(
                {
                    "artifact": artifact_debug_dict(artifact),
                    "transformed": transformed_debug_dict(transformed),
                    "summary": transformed_summary(transformed),
                }
            )

            cursor_y += transformed.instance.transformed_bbox[1] + spacing_mm

    elif mode == "grid":
        count = len(loaded_artifacts)
        cols = max(1, math.ceil(math.sqrt(count)))

        max_width = 0.0
        max_height = 0.0
        for artifact in loaded_artifacts:
            max_width = max(max_width, artifact.layout.width)
            max_height = max(max_height, artifact.layout.height)

        cell_w = max_width + spacing_mm
        cell_h = max_height + spacing_mm

        for index, artifact in enumerate(loaded_artifacts):
            row = index // cols
            col = index % cols
            rotation = (index * rotation_step_deg) % 360.0
            origin = Point(col * cell_w, row * cell_h)
            transformed = transform_loaded_artifact(
                artifact,
                origin=origin,
                rotation=rotation,
            )

            entry = CompositionEntry(
                artifact_dir=artifact.artifact_dir,
                sheet_name=artifact.sheet_name,
                instance_path=artifact.instance_path,
                origin=origin,
                rotation=rotation,
                transformed_bbox=transformed.instance.transformed_bbox,
                component_count=len(transformed.transformed_components),
                trace_count=len(transformed.transformed_traces),
                via_count=len(transformed.transformed_vias),
                anchor_count=len(transformed.transformed_anchors),
            )
            entries.append(entry)
            child_artifact_placements.append(
                ChildArtifactPlacement(
                    artifact=artifact,
                    origin=origin,
                    rotation=rotation,
                )
            )
            transformed_payloads.append(
                {
                    "artifact": artifact_debug_dict(artifact),
                    "transformed": transformed_debug_dict(transformed),
                    "summary": transformed_summary(transformed),
                }
            )

    else:
        raise ValueError(f"Unsupported composition mode: {mode}")

    project_dir = (
        str(Path(loaded_artifacts[0].artifact_dir).resolve().parents[2])
        if loaded_artifacts
        else ""
    )
    parent_subcircuit = parent_definition or SubCircuitDefinition(
        id=SubCircuitId(
            sheet_name="COMPOSED_PARENT",
            sheet_file="COMPOSED_PARENT.kicad_sch",
            instance_path="/COMPOSED_PARENT",
            parent_instance_path=None,
        ),
        schematic_path="",
        component_refs=[],
        ports=[],
        child_ids=[artifact.layout.subcircuit_id for artifact in loaded_artifacts],
        parent_id=None,
        is_leaf=False,
        sheet_uuid="",
        notes=[
            "synthetic_parent=true",
            f"mode={mode}",
            f"artifact_count={len(loaded_artifacts)}",
        ],
    )
    composition = build_parent_composition(
        parent_subcircuit,
        child_artifact_placements=child_artifact_placements,
    )

    state = ParentCompositionState(
        project_dir=project_dir,
        mode=mode,
        spacing_mm=spacing_mm,
        entries=entries,
        bounding_box=composition.board_state.board_outline,
        parent_sheet_name=composition.hierarchy_state.subcircuit.id.sheet_name,
        parent_instance_path=composition.hierarchy_state.subcircuit.id.instance_path,
        component_count=composition.component_count,
        trace_count=composition.trace_count,
        via_count=composition.via_count,
        interconnect_net_count=len(composition.hierarchy_state.interconnect_nets),
        inferred_interconnect_net_count=len(composition.inferred_interconnect_nets),
        routed_interconnect_net_count=len(composition.routed_interconnect_nets),
        failed_interconnect_net_count=len(composition.failed_interconnect_nets),
        score_total=composition.score.total if composition.score else 0.0,
        score_breakdown=dict(composition.score.breakdown) if composition.score else {},
        score_notes=list(composition.score.notes) if composition.score else [],
        composition_notes=list(composition.notes),
    )
    return state, transformed_payloads


def _entries_bbox(
    entries: list[CompositionEntry],
    *,
    max_row_height: float = 0.0,
    max_col_width: float = 0.0,
) -> tuple[Point, Point]:
    """Compute a simple composition bbox from entry origins and transformed sizes."""
    if not entries:
        return (Point(0.0, 0.0), Point(0.0, 0.0))

    min_x = min(entry.origin.x for entry in entries)
    min_y = min(entry.origin.y for entry in entries)
    max_x = max(entry.origin.x + entry.transformed_bbox[0] for entry in entries)
    max_y = max(entry.origin.y + entry.transformed_bbox[1] for entry in entries)

    if max_row_height > 0.0:
        max_y = max(max_y, min_y + max_row_height)
    if max_col_width > 0.0:
        max_x = max(max_x, min_x + max_col_width)

    return (Point(min_x, min_y), Point(max_x, max_y))


def _save_composition_snapshot(
    output_path: Path,
    state: ParentCompositionState,
    transformed_payloads: list[dict[str, Any]],
) -> str:
    """Write a composition snapshot JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    composition_payload = {
        "summary": (
            f"{state.parent_sheet_name} "
            f"[{state.parent_instance_path}] "
            f"children={len(state.entries)} "
            f"components={state.component_count} "
            f"traces={state.trace_count} "
            f"vias={state.via_count} "
            f"interconnects={state.interconnect_net_count} "
            f"score={state.score_total:.1f} "
            f"size={state.width_mm:.1f}x{state.height_mm:.1f}mm"
        ),
        "debug": {
            "parent": {
                "sheet_name": state.parent_sheet_name,
                "instance_path": state.parent_instance_path,
            },
            "child_count": len(state.entries),
            "component_count": state.component_count,
            "trace_count": state.trace_count,
            "via_count": state.via_count,
            "interconnect_net_count": state.interconnect_net_count,
            "inferred_interconnect_net_count": state.inferred_interconnect_net_count,
            "routed_interconnect_net_count": state.routed_interconnect_net_count,
            "failed_interconnect_net_count": state.failed_interconnect_net_count,
            "score": {
                "total": state.score_total,
                "breakdown": dict(state.score_breakdown),
                "notes": list(state.score_notes),
            },
            "notes": list(state.composition_notes),
            "board_outline": state.to_dict()["bounding_box"],
        },
    }
    payload = {
        "composition": composition_payload,
        "state": state.to_dict(),
        "artifacts": transformed_payloads,
    }
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return str(output_path)


def _print_human_summary(
    loaded_artifacts,
    state: ParentCompositionState,
    transformed_payloads: list[dict[str, Any]],
    output_path: str | None,
) -> None:
    print("=== Subcircuit Composition ===")
    print(f"artifacts              : {len(loaded_artifacts)}")
    print(f"mode                   : {state.mode}")
    print(f"spacing_mm             : {state.spacing_mm:.2f}")
    print(f"parent                 : {state.parent_sheet_name}")
    print(f"parent_instance_path   : {state.parent_instance_path}")
    print(f"composition_mm         : {state.width_mm:.2f} x {state.height_mm:.2f}")
    print(f"components             : {state.component_count}")
    print(f"traces                 : {state.trace_count}")
    print(f"vias                   : {state.via_count}")
    print(f"interconnect_nets      : {state.interconnect_net_count}")
    print(f"inferred_interconnects : {state.inferred_interconnect_net_count}")
    print(f"routed_interconnects   : {state.routed_interconnect_net_count}")
    print(f"failed_interconnects   : {state.failed_interconnect_net_count}")
    print(f"score_total            : {state.score_total:.2f}")
    if output_path:
        print(f"output_json            : {output_path}")
    print()

    for artifact, transformed in zip(loaded_artifacts, transformed_payloads):
        print(f"- {artifact_summary(artifact)}")
        print(f"  artifact_dir : {artifact.artifact_dir}")
        print(f"  transformed  : {transformed['summary']}")
        print()

    if state.score_breakdown:
        print("score_breakdown:")
        for key, value in sorted(state.score_breakdown.items()):
            print(f"  - {key}: {value:.2f}")
        print()

    if state.score_notes:
        print("score_notes:")
        for note in state.score_notes:
            print(f"  - {note}")
        print()

    if state.composition_notes:
        print("composition_notes:")
        for note in state.composition_notes:
            print(f"  - {note}")
        print()


def _json_payload(
    loaded_artifacts,
    state: ParentCompositionState,
    transformed_payloads: list[dict[str, Any]],
    output_path: str | None,
) -> dict[str, Any]:
    composition_payload = {
        "summary": (
            f"{state.parent_sheet_name} "
            f"[{state.parent_instance_path}] "
            f"children={len(state.entries)} "
            f"components={state.component_count} "
            f"traces={state.trace_count} "
            f"vias={state.via_count} "
            f"interconnects={state.interconnect_net_count} "
            f"score={state.score_total:.1f} "
            f"size={state.width_mm:.1f}x{state.height_mm:.1f}mm"
        ),
        "debug": {
            "parent": {
                "sheet_name": state.parent_sheet_name,
                "instance_path": state.parent_instance_path,
            },
            "child_count": len(state.entries),
            "component_count": state.component_count,
            "trace_count": state.trace_count,
            "via_count": state.via_count,
            "interconnect_net_count": state.interconnect_net_count,
            "inferred_interconnect_net_count": state.inferred_interconnect_net_count,
            "routed_interconnect_net_count": state.routed_interconnect_net_count,
            "failed_interconnect_net_count": state.failed_interconnect_net_count,
            "score": {
                "total": state.score_total,
                "breakdown": dict(state.score_breakdown),
                "notes": list(state.score_notes),
            },
            "notes": list(state.composition_notes),
            "board_outline": state.to_dict()["bounding_box"],
        },
    }
    return {
        "artifact_count": len(loaded_artifacts),
        "composition": composition_payload,
        "state": state.to_dict(),
        "output_json": output_path,
        "artifacts": transformed_payloads,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compose solved subcircuits into a parent composition state"
    )
    parser.add_argument(
        "--project",
        help="Project directory containing .experiments/subcircuits",
    )
    parser.add_argument(
        "--artifact",
        action="append",
        default=[],
        help="Specific solved artifact directory to include (repeatable)",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Restrict composition to sheet name, sheet file, or instance path",
    )
    parser.add_argument(
        "--mode",
        choices=("row", "column", "grid"),
        default="row",
        help="Initial rigid composition mode (default: row)",
    )
    parser.add_argument(
        "--parent",
        help="Compose a real parent by sheet name, sheet file, or instance path (including root)",
    )
    parser.add_argument(
        "--spacing-mm",
        type=float,
        default=10.0,
        help="Spacing between rigid child modules in mm (default: 10)",
    )
    parser.add_argument(
        "--rotation-step-deg",
        type=float,
        default=0.0,
        help="Per-artifact rotation increment in degrees (default: 0)",
    )
    parser.add_argument(
        "--output",
        help="Optional JSON file path to save the composition snapshot",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of human-readable text",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    project_dir = Path(args.project).resolve() if args.project else None
    artifact_dirs = _resolve_artifact_dirs(project_dir, args.artifact)

    if not artifact_dirs:
        print(
            "error: no solved subcircuit artifacts found; provide --artifact or --project",
            file=sys.stderr,
        )
        return 2

    try:
        loaded_artifacts = load_solved_artifacts(list(artifact_dirs))
        loaded_artifacts = _filter_loaded_artifacts(loaded_artifacts, args.only)
        parent_definition = _select_parent_definition(project_dir, args.parent)
        loaded_artifacts = _filter_artifacts_for_parent(
            loaded_artifacts,
            parent_definition,
        )
        if not loaded_artifacts:
            if args.parent:
                print(
                    "error: no solved child artifacts found for selected parent",
                    file=sys.stderr,
                )
            else:
                print(
                    "error: no matching solved artifacts after filtering",
                    file=sys.stderr,
                )
            return 1

        state, transformed_payloads = _compose_artifacts(
            loaded_artifacts,
            mode=args.mode,
            spacing_mm=max(0.0, args.spacing_mm),
            rotation_step_deg=args.rotation_step_deg,
            parent_definition=parent_definition,
        )

        output_path = None
        if args.output:
            output_path = _save_composition_snapshot(
                Path(args.output).resolve(),
                state,
                transformed_payloads,
            )

    except Exception as exc:
        print(f"error: failed to compose subcircuits: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                _json_payload(
                    loaded_artifacts, state, transformed_payloads, output_path
                ),
                indent=2,
            )
        )
        return 0

    _print_human_summary(loaded_artifacts, state, transformed_payloads, output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
