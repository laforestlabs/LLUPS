"""KiCad pcbnew adapter — sole interface to .kicad_pcb files.

This is the ONLY module that imports pcbnew. All other modules operate
on pure-Python types from brain.types.
"""
import math
import pcbnew

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from brain.types import (
    Point, Pad, Component, Net, TraceSegment, Via, BoardState, Layer
)


# Nets that get wider traces
POWER_NETS = {
    "VBUS", "VBAT", "5V", "3V3", "3.3V", "+5V", "+3V3", "GND",
    "/VBUS", "/VBAT", "/5V", "/3V3", "/VSYS", "/VSYS_BOOST",
    "/CELL_NEG", "/EN",
}

SIGNAL_WIDTH_MM = 0.127
POWER_WIDTH_MM = 0.127
VIA_DRILL_MM = 0.3
VIA_SIZE_MM = 0.6


def _classify_component(ref: str, value: str) -> str:
    """Classify component by reference prefix."""
    r = ref.upper()
    if r.startswith("J"):
        return "connector"
    if r.startswith("H"):
        return "mounting_hole"
    if r.startswith("U"):
        return "ic"
    if r.startswith(("R", "C", "L", "D", "F")):
        return "passive"
    if r.startswith("BT"):
        return "battery"
    return "misc"


def _layer_to_enum(kicad_layer: int) -> Layer:
    if kicad_layer == pcbnew.B_Cu:
        return Layer.BACK
    return Layer.FRONT


def _enum_to_layer(layer: Layer) -> int:
    return pcbnew.B_Cu if layer == Layer.BACK else pcbnew.F_Cu


class KiCadAdapter:
    """Reads and writes KiCad board state via pcbnew API."""

    def __init__(self, pcb_path: str, config: dict = None):
        self.pcb_path = pcb_path
        self.board = None
        self.cfg = config or {}

    def _ensure_loaded(self):
        if self.board is None:
            self.board = pcbnew.LoadBoard(self.pcb_path)

    def reload(self):
        """Force fresh board load."""
        self.board = None
        self._ensure_loaded()

    def load(self) -> BoardState:
        """Extract full BoardState from .kicad_pcb."""
        self._ensure_loaded()
        board = self.board

        # --- Board outline ---
        bbox = board.GetBoardEdgesBoundingBox()
        tl = Point(pcbnew.ToMM(bbox.GetLeft()), pcbnew.ToMM(bbox.GetTop()))
        br = Point(pcbnew.ToMM(bbox.GetRight()), pcbnew.ToMM(bbox.GetBottom()))

        # --- Components + Pads ---
        components: dict[str, Component] = {}
        net_pads: dict[str, list[tuple[str, str]]] = {}  # net_name -> [(ref, pad_id)]

        for fp in board.Footprints():
            ref = fp.GetReferenceAsString()
            val = fp.GetFieldText("Value")
            pos = fp.GetPosition()
            # Use courtyard bbox for physical size — it represents the keep-out
            # area on the PCB plane (excludes battery tube space above board).
            # Fall back to copper bounding box if no courtyard is defined.
            try:
                cy = fp.GetCourtyard(
                    pcbnew.F_CrtYd if fp.GetLayer() == pcbnew.F_Cu
                    else pcbnew.B_CrtYd)
                cbox = cy.BBox()
                if cbox.GetWidth() > 0 and cbox.GetHeight() > 0:
                    w_mm = pcbnew.ToMM(cbox.GetWidth())
                    h_mm = pcbnew.ToMM(cbox.GetHeight())
                else:
                    raise ValueError("empty courtyard")
            except Exception:
                fp_bbox = fp.GetBoundingBox(False, False)
                w_mm = pcbnew.ToMM(fp_bbox.GetWidth())
                h_mm = pcbnew.ToMM(fp_bbox.GetHeight())
            # Sanity cap at board size — prevents degenerate courtyard bboxes
            w_mm = min(w_mm, 150.0)
            h_mm = min(h_mm, 150.0)

            kind = _classify_component(ref, val)
            # Detect through-hole: any pad with PTH attribute means THT footprint
            has_pth = any(
                p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH
                for p in fp.Pads()
            )
            # Lock mechanically-fixed parts unless unlock_all_footprints is set.
            # Battery holders have fixed positions by default.
            if self.cfg.get("unlock_all_footprints", False):
                is_locked = fp.IsLocked()
            else:
                is_locked = fp.IsLocked() or kind in ("battery",)
            comp = Component(
                ref=ref,
                value=val,
                pos=Point(pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)),
                rotation=fp.GetOrientationDegrees(),
                layer=_layer_to_enum(fp.GetLayer()),
                width_mm=w_mm,
                height_mm=h_mm,
                pads=[],
                locked=is_locked,
                kind=kind,
                is_through_hole=has_pth,
            )

            for pad in fp.Pads():
                net_name = pad.GetNetname()
                if not net_name or net_name.startswith("unconnected-"):
                    continue
                ppos = pad.GetPosition()
                p = Pad(
                    ref=ref,
                    pad_id=pad.GetNumber(),
                    pos=Point(pcbnew.ToMM(ppos.x), pcbnew.ToMM(ppos.y)),
                    net=net_name,
                    layer=_layer_to_enum(pad.GetLayer()),
                )
                comp.pads.append(p)
                net_pads.setdefault(net_name, []).append((ref, pad.GetNumber()))

            components[ref] = comp

        # --- Nets ---
        nets: dict[str, Net] = {}
        for net_name, pads in net_pads.items():
            is_power = net_name in POWER_NETS or net_name.lstrip("/") in POWER_NETS
            nets[net_name] = Net(
                name=net_name,
                pad_refs=pads,
                width_mm=POWER_WIDTH_MM if is_power else SIGNAL_WIDTH_MM,
                is_power=is_power,
            )

        # --- Existing traces ---
        traces: list[TraceSegment] = []
        vias: list[Via] = []
        for track in board.GetTracks():
            if isinstance(track, pcbnew.PCB_VIA):
                vpos = track.GetPosition()
                # KiCad 9: GetWidth requires layer arg for vias
                try:
                    via_size = pcbnew.ToMM(track.GetWidth(pcbnew.F_Cu))
                except TypeError:
                    via_size = pcbnew.ToMM(track.GetWidth())
                vias.append(Via(
                    pos=Point(pcbnew.ToMM(vpos.x), pcbnew.ToMM(vpos.y)),
                    net=track.GetNetname(),
                    drill_mm=pcbnew.ToMM(track.GetDrill()),
                    size_mm=via_size,
                ))
            else:
                s = track.GetStart()
                e = track.GetEnd()
                traces.append(TraceSegment(
                    start=Point(pcbnew.ToMM(s.x), pcbnew.ToMM(s.y)),
                    end=Point(pcbnew.ToMM(e.x), pcbnew.ToMM(e.y)),
                    layer=_layer_to_enum(track.GetLayer()),
                    net=track.GetNetname(),
                    width_mm=pcbnew.ToMM(track.GetWidth()),
                ))

        return BoardState(
            components=components,
            nets=nets,
            traces=traces,
            vias=vias,
            board_outline=(tl, br),
        )

    def apply_placement(self, components: dict[str, Component],
                        output_path: str = None):
        """Move footprints to new positions/rotations. Preserves existing traces."""
        self._ensure_loaded()
        board = self.board

        # Apply board outline change if config specifies board dimensions
        if self.cfg.get("enable_board_size_search", False):
            w_mm = self.cfg.get("board_width_mm", 90.0)
            h_mm = self.cfg.get("board_height_mm", 58.0)
            self._apply_board_outline(w_mm, h_mm)

        for fp in board.Footprints():
            ref = fp.GetReferenceAsString()
            if ref not in components:
                continue
            comp = components[ref]
            # Only skip components explicitly locked by the user in KiCad.
            # The solver's locked flag (set for connectors/mounting_holes/
            # batteries by _pin_edge_components) is for the force simulation
            # only — their solver-computed positions must still be written.
            if fp.IsLocked():
                continue
            # Flip to correct layer if solver assigned a different side
            current_layer = _layer_to_enum(fp.GetLayer())
            if comp.layer != current_layer:
                fp.Flip(fp.GetPosition(), False)
            fp.SetPosition(pcbnew.VECTOR2I(
                pcbnew.FromMM(comp.pos.x),
                pcbnew.FromMM(comp.pos.y),
            ))
            fp.SetOrientationDegrees(comp.rotation)

        out = output_path or self.pcb_path
        board.Save(out)
        print(f"Placement saved to {out}")

    def _apply_board_outline(self, width_mm: float, height_mm: float):
        """Rewrite the Edge.Cuts rectangle to the given dimensions, centered."""
        board = self.board
        bbox = board.GetBoardEdgesBoundingBox()
        # Keep the center of the original board
        cx = (bbox.GetLeft() + bbox.GetRight()) // 2
        cy = (bbox.GetTop() + bbox.GetBottom()) // 2
        half_w = pcbnew.FromMM(width_mm / 2)
        half_h = pcbnew.FromMM(height_mm / 2)

        new_left = cx - half_w
        new_top = cy - half_h
        new_right = cx + half_w
        new_bottom = cy + half_h

        # Remove existing Edge.Cuts lines
        to_remove = []
        for dwg in board.GetDrawings():
            if dwg.GetLayer() == pcbnew.Edge_Cuts:
                to_remove.append(dwg)
        for dwg in to_remove:
            board.Remove(dwg)

        # Draw new rectangle
        corners = [
            (new_left, new_top), (new_right, new_top),
            (new_right, new_bottom), (new_left, new_bottom),
        ]
        for i in range(4):
            seg = pcbnew.PCB_SHAPE(board)
            seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
            seg.SetLayer(pcbnew.Edge_Cuts)
            seg.SetWidth(pcbnew.FromMM(0.05))
            x1, y1 = corners[i]
            x2, y2 = corners[(i + 1) % 4]
            seg.SetStart(pcbnew.VECTOR2I(x1, y1))
            seg.SetEnd(pcbnew.VECTOR2I(x2, y2))
            board.Add(seg)
