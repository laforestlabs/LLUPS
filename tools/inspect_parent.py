#!/usr/bin/env python3
"""inspect_parent.py — read a stamped/routed parent .kicad_pcb and report
geometry diagnostics that the renders alone don't make obvious.

Usage:
    python3 tools/inspect_parent.py [parent_pcb_path]

Default path is .experiments/subcircuits/subcircuit__8a5edab282/parent_routed.kicad_pcb

Reports:
  - Board outline (Edge.Cuts bbox)
  - Per-footprint world position, courtyard bbox
  - Edge-constrained refs from LLUPS_autoplacer.json: their position
    relative to the board edge, and whether they overhang
  - Edge marker (PCB Edge silkscreen on Dwgs.User) world position vs.
    expected board edge -- the load-bearing check for "is the marker
    aligned with the board edge so the connector physically overhangs?"
  - Empty-area summary: how much board area sits with NO front-side
    copper on top of NO back-side copper (i.e. wasted board real
    estate that could host more leaves)

Emit JSON when --json is passed; otherwise human-readable text.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import pcbnew


@dataclass
class Bbox:
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    def to_dict(self) -> dict:
        return {
            "min_x": self.min_x,
            "min_y": self.min_y,
            "max_x": self.max_x,
            "max_y": self.max_y,
            "width": self.width,
            "height": self.height,
        }


def _to_mm(nm: int) -> float:
    return nm / 1e6


def _bbox_from_kibbox(kb) -> Bbox:
    return Bbox(
        min_x=_to_mm(kb.GetLeft()),
        min_y=_to_mm(kb.GetTop()),
        max_x=_to_mm(kb.GetRight()),
        max_y=_to_mm(kb.GetBottom()),
    )


def _board_outline_bbox(board) -> Bbox:
    return _bbox_from_kibbox(board.GetBoardEdgesBoundingBox())


def _edge_marker_position(footprint) -> tuple[float, float] | None:
    """Find a 'PCB Edge' marker in the footprint's Dwgs.User layer.

    The marker is typically an fp_text or fp_line. Its world position
    tells us where the footprint expects the actual PCB edge to land.
    """
    pcb_edge_layer = pcbnew.Dwgs_User
    for item in footprint.GraphicalItems():
        try:
            if item.GetLayer() != pcb_edge_layer:
                continue
        except Exception:
            continue
        try:
            text = item.GetText() if hasattr(item, "GetText") else ""
        except Exception:
            text = ""
        if "edge" in text.lower():
            pos = item.GetPosition()
            return _to_mm(pos.x), _to_mm(pos.y)
        if hasattr(item, "GetStart") and hasattr(item, "GetEnd"):
            s, e = item.GetStart(), item.GetEnd()
            return (
                _to_mm((s.x + e.x) / 2),
                _to_mm((s.y + e.y) / 2),
            )
    return None


def _load_zone_constraints(project_dir: Path) -> dict[str, dict]:
    cfg_path = project_dir / "LLUPS_autoplacer.json"
    if not cfg_path.is_file():
        return {}
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    return cfg.get("component_zones", {})


def _footprint_courtyard_bbox(footprint) -> Bbox:
    layer = pcbnew.F_CrtYd if footprint.GetLayer() == pcbnew.F_Cu else pcbnew.B_CrtYd
    try:
        c = footprint.GetCourtyard(layer)
        bb = c.BBox()
        if bb.GetWidth() > 0 and bb.GetHeight() > 0:
            return _bbox_from_kibbox(bb)
    except Exception:
        pass
    return _bbox_from_kibbox(footprint.GetBoundingBox(False, False))


def _bboxes_overlap(a: Bbox, b: Bbox) -> bool:
    return (
        a.min_x < b.max_x
        and a.max_x > b.min_x
        and a.min_y < b.max_y
        and a.max_y > b.min_y
    )


def _bbox_overlap_area(a: Bbox, b: Bbox) -> float:
    ox = max(0.0, min(a.max_x, b.max_x) - max(a.min_x, b.min_x))
    oy = max(0.0, min(a.max_y, b.max_y) - max(a.min_y, b.min_y))
    return ox * oy


def inspect(pcb_path: Path, project_dir: Path) -> dict:
    board = pcbnew.LoadBoard(str(pcb_path))
    if board is None:
        raise RuntimeError(f"Could not load {pcb_path}")

    outline = _board_outline_bbox(board)
    zones = _load_zone_constraints(project_dir)

    footprints: list[dict] = []
    edge_findings: list[dict] = []
    front_courtyards: list[Bbox] = []
    back_courtyards: list[Bbox] = []

    for fp in board.GetFootprints():
        ref = fp.GetReferenceAsString()
        layer = "back" if fp.GetLayer() == pcbnew.B_Cu else "front"
        cb = _footprint_courtyard_bbox(fp)
        if layer == "front":
            front_courtyards.append(cb)
        else:
            back_courtyards.append(cb)
        marker = _edge_marker_position(fp)
        fp_info = {
            "ref": ref,
            "layer": layer,
            "pos": (_to_mm(fp.GetPosition().x), _to_mm(fp.GetPosition().y)),
            "courtyard": cb.to_dict(),
            "edge_marker": marker,
        }
        footprints.append(fp_info)

        zone_cfg = zones.get(ref)
        if zone_cfg is None:
            continue
        edge = zone_cfg.get("edge")
        if not edge or marker is None:
            continue
        # Compute how far the marker is from the relevant board edge.
        if edge == "left":
            distance = marker[0] - outline.min_x
            outboard = cb.min_x < outline.min_x
        elif edge == "right":
            distance = outline.max_x - marker[0]
            outboard = cb.max_x > outline.max_x
        elif edge == "top":
            distance = marker[1] - outline.min_y
            outboard = cb.min_y < outline.min_y
        else:  # bottom
            distance = outline.max_y - marker[1]
            outboard = cb.max_y > outline.max_y
        edge_findings.append(
            {
                "ref": ref,
                "edge": edge,
                "marker_world": marker,
                "marker_distance_from_edge_mm": distance,
                "courtyard_overhangs": outboard,
                "interpretation": (
                    "OK: marker at edge, body overhangs"
                    if abs(distance) < 0.5 and outboard
                    else "BUG: marker not at edge"
                    if abs(distance) >= 0.5
                    else "OK-ish: marker at edge, body fully inside"
                ),
            }
        )

    # Wasted-area heuristic: scan the board on a 5 mm grid and count
    # cells with neither front nor back courtyard occupancy. That's
    # board real estate that *could* host another leaf if our placer
    # were doing dual-layer stacking properly.
    grid_mm = 5.0
    nx = max(1, int(outline.width / grid_mm))
    ny = max(1, int(outline.height / grid_mm))
    occupied_front = 0
    occupied_back = 0
    occupied_either = 0
    occupied_both = 0
    total_cells = nx * ny
    for ix in range(nx):
        for iy in range(ny):
            cx = outline.min_x + (ix + 0.5) * grid_mm
            cy = outline.min_y + (iy + 0.5) * grid_mm
            cell = Bbox(
                cx - grid_mm / 2,
                cy - grid_mm / 2,
                cx + grid_mm / 2,
                cy + grid_mm / 2,
            )
            on_front = any(_bboxes_overlap(cell, fc) for fc in front_courtyards)
            on_back = any(_bboxes_overlap(cell, bc) for bc in back_courtyards)
            occupied_front += int(on_front)
            occupied_back += int(on_back)
            occupied_either += int(on_front or on_back)
            occupied_both += int(on_front and on_back)
    empty_cells = total_cells - occupied_either
    wasted_area_mm2 = empty_cells * grid_mm * grid_mm
    board_area_mm2 = outline.width * outline.height
    stacked_area_mm2 = occupied_both * grid_mm * grid_mm

    return {
        "pcb_path": str(pcb_path),
        "board_outline": outline.to_dict(),
        "board_area_mm2": board_area_mm2,
        "footprints": footprints,
        "edge_findings": edge_findings,
        "wasted_area": {
            "empty_cells": empty_cells,
            "total_cells": total_cells,
            "wasted_area_mm2": wasted_area_mm2,
            "wasted_fraction": (
                wasted_area_mm2 / board_area_mm2 if board_area_mm2 > 0 else 0.0
            ),
            "stacked_area_mm2": stacked_area_mm2,
            "stacked_fraction": (
                stacked_area_mm2 / board_area_mm2 if board_area_mm2 > 0 else 0.0
            ),
            "front_only_area_mm2": (occupied_front - occupied_both) * grid_mm * grid_mm,
            "back_only_area_mm2": (occupied_back - occupied_both) * grid_mm * grid_mm,
        },
    }


def print_report(report: dict) -> None:
    bo = report["board_outline"]
    print("=== Parent PCB Inspection ===")
    print(f"path : {report['pcb_path']}")
    print(
        f"board: ({bo['min_x']:.2f}, {bo['min_y']:.2f}) - "
        f"({bo['max_x']:.2f}, {bo['max_y']:.2f}) "
        f"= {bo['width']:.2f} x {bo['height']:.2f} mm "
        f"({report['board_area_mm2']:.0f} mm²)"
    )
    print()
    print("--- Edge-constrained findings ---")
    if not report["edge_findings"]:
        print("(none)")
    for f in report["edge_findings"]:
        marker = f["marker_world"]
        print(
            f"{f['ref']:6s} edge={f['edge']:6s} "
            f"marker=({marker[0]:.2f},{marker[1]:.2f}) "
            f"distance_from_edge={f['marker_distance_from_edge_mm']:.3f} mm  "
            f"courtyard_overhangs={f['courtyard_overhangs']}  "
            f"=> {f['interpretation']}"
        )
    print()
    wa = report["wasted_area"]
    print("--- Area utilization (5 mm grid) ---")
    print(f"  empty cells          : {wa['empty_cells']}/{wa['total_cells']}")
    print(
        f"  wasted area          : {wa['wasted_area_mm2']:.0f} mm² "
        f"({wa['wasted_fraction'] * 100:.1f}% of board)"
    )
    print(
        f"  stacked (front+back) : {wa['stacked_area_mm2']:.0f} mm² "
        f"({wa['stacked_fraction'] * 100:.1f}% of board)"
    )
    print(f"  front-only           : {wa['front_only_area_mm2']:.0f} mm²")
    print(f"  back-only            : {wa['back_only_area_mm2']:.0f} mm²")
    print()
    print("--- Footprint summary ---")
    for fp in report["footprints"]:
        if fp["ref"].startswith(("FID", "TP", "")):
            pass
        c = fp["courtyard"]
        print(
            f"{fp['ref']:6s} {fp['layer']:5s} "
            f"pos=({fp['pos'][0]:7.2f},{fp['pos'][1]:7.2f}) "
            f"courtyard=({c['min_x']:7.2f},{c['min_y']:7.2f})-"
            f"({c['max_x']:7.2f},{c['max_y']:7.2f})"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "pcb",
        nargs="?",
        default=".experiments/subcircuits/subcircuit__8a5edab282/parent_routed.kicad_pcb",
    )
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    pcb_path = Path(args.pcb).resolve()
    if not pcb_path.is_file():
        print(f"error: {pcb_path} not found", file=sys.stderr)
        return 2
    report = inspect(pcb_path, Path(args.project_dir).resolve())
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
