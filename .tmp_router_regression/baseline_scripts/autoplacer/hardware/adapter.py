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

SIGNAL_WIDTH_MM = 0.25
POWER_WIDTH_MM = 1.0
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

    def __init__(self, pcb_path: str):
        self.pcb_path = pcb_path
        self.board = None

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
            # Lock mechanically-fixed parts regardless of KiCad lock flag.
            # Battery holders have fixed positions; connectors are edge-pinned.
            is_locked = fp.IsLocked() or kind in ("connector", "mounting_hole", "battery")
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

        for fp in board.Footprints():
            ref = fp.GetReferenceAsString()
            if ref not in components:
                continue
            comp = components[ref]
            if comp.locked:
                continue
            fp.SetPosition(pcbnew.VECTOR2I(
                pcbnew.FromMM(comp.pos.x),
                pcbnew.FromMM(comp.pos.y),
            ))
            fp.SetOrientationDegrees(comp.rotation)

        out = output_path or self.pcb_path
        board.Save(out)
        print(f"Placement saved to {out}")

    def apply_routing(self, traces: list[TraceSegment], vias: list[Via],
                      clear_existing: bool = True,
                      preserve_thermal_vias: bool = True,
                      thermal_refs: list[str] = None,
                      thermal_radius_mm: float = 3.0,
                      output_path: str = None):
        """Write traces and vias to board via subprocess (avoids SWIG reload bugs)."""
        import subprocess, json, tempfile

        out = output_path or self.pcb_path

        # Serialize routing data to JSON
        routing_data = {
            "pcb_path": out,
            "clear_existing": clear_existing,
            "preserve_thermal": preserve_thermal_vias,
            "thermal_refs": thermal_refs or [],
            "thermal_radius_mm": thermal_radius_mm,
            "traces": [
                {"sx": s.start.x, "sy": s.start.y, "ex": s.end.x, "ey": s.end.y,
                 "layer": int(s.layer), "net": s.net, "width": s.width_mm}
                for s in traces
            ],
            "vias": [
                {"x": v.pos.x, "y": v.pos.y, "net": v.net,
                 "drill": v.drill_mm, "size": v.size_mm}
                for v in vias
            ],
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(routing_data, f)
            tmp_path = f.name

        # Run writer in separate process to get clean pcbnew state
        script = os.path.join(os.path.dirname(__file__), "..", "_apply_routing.py")
        result = subprocess.run(
            ["python3", script, tmp_path],
            capture_output=True, text=True
        )
        os.unlink(tmp_path)

        if result.returncode != 0:
            print(f"Routing write failed: {result.stderr[-500:]}")
            raise RuntimeError("apply_routing subprocess failed")

        print(f"Routing saved: {len(traces)} traces, {len(vias)} vias -> {out}")

    def _clear_tracks_on(self, board, preserve_thermal: bool,
                         thermal_refs: list[str], thermal_radius_mm: float):
        """Remove tracks/vias on given board object."""
        thermal_centers = []
        if preserve_thermal:
            for ref in thermal_refs:
                fp = board.FindFootprintByReference(ref)
                if fp:
                    pos = fp.GetPosition()
                    thermal_centers.append(
                        (pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)))

        to_remove = []
        for track in board.GetTracks():
            if isinstance(track, pcbnew.PCB_VIA) and preserve_thermal:
                vpos = track.GetPosition()
                vx, vy = pcbnew.ToMM(vpos.x), pcbnew.ToMM(vpos.y)
                if any(math.hypot(vx - tx, vy - ty) <= thermal_radius_mm
                       for tx, ty in thermal_centers):
                    continue
            to_remove.append(track)

        for t in to_remove:
            board.Remove(t)
