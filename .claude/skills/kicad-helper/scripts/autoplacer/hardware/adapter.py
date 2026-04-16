"""KiCad pcbnew adapter — sole interface to .kicad_pcb files.

This is the ONLY module that imports pcbnew. All other modules operate
on pure-Python types from brain.types.
"""

import math
import os
import sys

import pcbnew

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from brain.types import BoardState, Component, Layer, Net, Pad, Point, TraceSegment, Via

# Nets that get wider traces
POWER_NETS = {
    "VBUS",
    "VBAT",
    "5V",
    "3V3",
    "3.3V",
    "+5V",
    "+3V3",
    "GND",
    "/VBUS",
    "/VBAT",
    "/5V",
    "/3V3",
    "/VSYS",
    "/VSYS_BOOST",
    "/CELL_NEG",
    "/EN",
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


def detect_opening_direction(fp) -> float | None:
    """Detect which direction the connector opening faces, in LOCAL coords.

    Detects the board-space opening direction by comparing pad bbox to body
    bbox (courtyard + fab graphics) — all in board-space coords straight from
    pcbnew, no rotation math.  Then converts to local with one addition:
    local_angle = (board_angle + rotation) % 360.

    Returns 0/90/180/270 in local coords, or None.
    """
    # --- Board-space pad bbox ---
    pad_xs = [pcbnew.ToMM(p.GetPosition().x) for p in fp.Pads()]
    pad_ys = [pcbnew.ToMM(p.GetPosition().y) for p in fp.Pads()]
    if not pad_xs:
        return None

    # --- Board-space body bbox from courtyard + fab ---
    body_xs, body_ys = [], []
    cy_layer = pcbnew.F_CrtYd if fp.GetLayer() == pcbnew.F_Cu else pcbnew.B_CrtYd
    fab_layer = pcbnew.F_Fab if fp.GetLayer() == pcbnew.F_Cu else pcbnew.B_Fab
    for item in fp.GraphicalItems():
        if item.GetLayer() not in (cy_layer, fab_layer):
            continue
        try:
            body_xs.append(pcbnew.ToMM(item.GetStart().x))
            body_xs.append(pcbnew.ToMM(item.GetEnd().x))
            body_ys.append(pcbnew.ToMM(item.GetStart().y))
            body_ys.append(pcbnew.ToMM(item.GetEnd().y))
        except Exception:
            continue
    if not body_xs:
        return None

    # --- How far body extends beyond pads on each side ---
    extensions = {
        0: max(body_xs) - max(pad_xs),  # +X (right)
        180: min(pad_xs) - min(body_xs),  # -X (left)
        90: max(body_ys) - max(pad_ys),  # +Y (down)
        270: min(pad_ys) - min(body_ys),  # -Y (up)
    }

    ranked = sorted(extensions.items(), key=lambda kv: kv[1], reverse=True)
    best_dir, best_ext = ranked[0]
    _, second_ext = ranked[1]

    opening_board = None
    if best_ext >= 1.0 and (best_ext - second_ext) >= 0.5:
        opening_board = best_dir
    else:
        # Fallback: "PCB Edge" / "Board Edge" text on Dwgs.User
        pad_cx = (min(pad_xs) + max(pad_xs)) / 2
        pad_cy = (min(pad_ys) + max(pad_ys)) / 2
        for item in fp.GraphicalItems():
            if item.GetLayer() != pcbnew.Dwgs_User:
                continue
            try:
                text = item.GetText()
            except Exception:
                continue
            if not text or "edge" not in text.lower():
                continue
            tp = item.GetPosition()
            off_x = pcbnew.ToMM(tp.x) - pad_cx
            off_y = pcbnew.ToMM(tp.y) - pad_cy
            if abs(off_x) > abs(off_y):
                opening_board = 0 if off_x > 0 else 180
            else:
                opening_board = 90 if off_y > 0 else 270
            break

    if opening_board is None:
        return None

    # Convert board-space → local with one addition (no trig)
    rotation = fp.GetOrientationDegrees() % 360
    return (opening_board + rotation) % 360


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
            body_ctr = None
            try:
                cy = fp.GetCourtyard(
                    pcbnew.F_CrtYd if fp.GetLayer() == pcbnew.F_Cu else pcbnew.B_CrtYd
                )
                cbox = cy.BBox()
                if cbox.GetWidth() > 0 and cbox.GetHeight() > 0:
                    w_mm = pcbnew.ToMM(cbox.GetWidth())
                    h_mm = pcbnew.ToMM(cbox.GetHeight())
                    cc = cbox.GetCenter()
                    body_ctr = Point(pcbnew.ToMM(cc.x), pcbnew.ToMM(cc.y))
                else:
                    raise ValueError("empty courtyard")
            except Exception:
                fp_bbox = fp.GetBoundingBox(False, False)
                w_mm = pcbnew.ToMM(fp_bbox.GetWidth())
                h_mm = pcbnew.ToMM(fp_bbox.GetHeight())
                fc = fp_bbox.GetCenter()
                body_ctr = Point(pcbnew.ToMM(fc.x), pcbnew.ToMM(fc.y))
            # Sanity cap at board size — prevents degenerate courtyard bboxes
            w_mm = min(w_mm, 150.0)
            h_mm = min(h_mm, 150.0)

            kind = _classify_component(ref, val)
            # Detect through-hole: any pad with PTH attribute means THT footprint
            has_pth = any(p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH for p in fp.Pads())
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
                body_center=body_ctr,
                opening_direction=(
                    detect_opening_direction(fp) if kind == "connector" else None
                ),
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
            power_nets = self.cfg.get("power_nets", set())
            is_power = net_name in power_nets or net_name.lstrip("/") in power_nets
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
                vias.append(
                    Via(
                        pos=Point(pcbnew.ToMM(vpos.x), pcbnew.ToMM(vpos.y)),
                        net=track.GetNetname(),
                        drill_mm=pcbnew.ToMM(track.GetDrill()),
                        size_mm=via_size,
                    )
                )
            else:
                s = track.GetStart()
                e = track.GetEnd()
                traces.append(
                    TraceSegment(
                        start=Point(pcbnew.ToMM(s.x), pcbnew.ToMM(s.y)),
                        end=Point(pcbnew.ToMM(e.x), pcbnew.ToMM(e.y)),
                        layer=_layer_to_enum(track.GetLayer()),
                        net=track.GetNetname(),
                        width_mm=pcbnew.ToMM(track.GetWidth()),
                    )
                )

        return BoardState(
            components=components,
            nets=nets,
            traces=traces,
            vias=vias,
            board_outline=(tl, br),
        )

    def apply_placement(
        self, components: dict[str, Component], output_path: str = None
    ):
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
            fp.SetPosition(
                pcbnew.VECTOR2I(
                    pcbnew.FromMM(comp.pos.x),
                    pcbnew.FromMM(comp.pos.y),
                )
            )
            fp.SetOrientationDegrees(comp.rotation)

        out = output_path or self.pcb_path
        board.Save(out)
        print(f"Placement saved to {out}")

    def stamp_board_state(
        self,
        state: BoardState,
        output_path: str | None = None,
        *,
        clear_existing_tracks: bool = True,
        clear_existing_zones: bool = True,
    ):
        """Stamp a pure-Python BoardState onto the current KiCad board.

        Intended for hierarchical composition demos where a parent board should
        visibly contain already-routed child subcircuits plus parent-level
        interconnect routing before exporting DSN / launching FreeRouting.

        Behavior:
        - moves footprints to match `state.components`
        - optionally clears existing tracks/vias
        - optionally clears existing copper zones
        - recreates traces/vias from `state.traces` / `state.vias`
        - preserves the existing board outline unless board-size search is enabled
        """
        self._ensure_loaded()
        board = self.board

        if self.cfg.get("enable_board_size_search", False):
            w_mm = self.cfg.get("board_width_mm", state.board_width)
            h_mm = self.cfg.get("board_height_mm", state.board_height)
            self._apply_board_outline(w_mm, h_mm)

        component_map = state.components or {}
        for fp in board.Footprints():
            ref = fp.GetReferenceAsString()
            comp = component_map.get(ref)
            if comp is None:
                continue
            if fp.IsLocked():
                continue
            current_layer = _layer_to_enum(fp.GetLayer())
            if comp.layer != current_layer:
                fp.Flip(fp.GetPosition(), False)
            fp.SetPosition(
                pcbnew.VECTOR2I(
                    pcbnew.FromMM(comp.pos.x),
                    pcbnew.FromMM(comp.pos.y),
                )
            )
            fp.SetOrientationDegrees(comp.rotation)

        if clear_existing_tracks:
            to_remove = [track for track in board.GetTracks()]
            for track in to_remove:
                board.Remove(track)

        if clear_existing_zones:
            to_remove = [zone for zone in board.Zones() if not zone.GetIsRuleArea()]
            for zone in to_remove:
                board.Remove(zone)

        netinfo = board.GetNetInfo()

        def _resolve_net_code(net_name: str) -> int:
            if not net_name:
                return 0
            net_item = netinfo.GetNetItem(net_name)
            if net_item is None:
                return 0
            try:
                return int(net_item.GetNetCode())
            except Exception:
                return 0

        for trace in state.traces:
            seg = pcbnew.PCB_TRACK(board)
            seg.SetStart(
                pcbnew.VECTOR2I(
                    pcbnew.FromMM(trace.start.x),
                    pcbnew.FromMM(trace.start.y),
                )
            )
            seg.SetEnd(
                pcbnew.VECTOR2I(
                    pcbnew.FromMM(trace.end.x),
                    pcbnew.FromMM(trace.end.y),
                )
            )
            seg.SetLayer(_enum_to_layer(trace.layer))
            seg.SetWidth(pcbnew.FromMM(trace.width_mm))
            net_code = _resolve_net_code(trace.net)
            if net_code > 0:
                seg.SetNetCode(net_code)
            board.Add(seg)

        for via in state.vias:
            track_via = pcbnew.PCB_VIA(board)
            track_via.SetPosition(
                pcbnew.VECTOR2I(
                    pcbnew.FromMM(via.pos.x),
                    pcbnew.FromMM(via.pos.y),
                )
            )
            track_via.SetDrill(pcbnew.FromMM(via.drill_mm))
            try:
                track_via.SetWidth(pcbnew.FromMM(via.size_mm))
            except TypeError:
                track_via.SetWidth(pcbnew.F_Cu, pcbnew.FromMM(via.size_mm))
            net_code = _resolve_net_code(via.net)
            if net_code > 0:
                track_via.SetNetCode(net_code)
            board.Add(track_via)

        board.BuildConnectivity()
        out = output_path or self.pcb_path
        board.Save(out)
        print(f"Board state stamped to {out}")

    def stamp_subcircuit_board(
        self,
        state: BoardState,
        output_path: str | None = None,
        *,
        clear_existing_tracks: bool = True,
        clear_existing_zones: bool = True,
        remove_unmapped_footprints: bool = True,
    ):
        """Stamp a leaf/subcircuit board onto a real KiCad board.

        This helper is intended for routed leaf subcircuits where the exported
        board must be loadable by pcbnew/FreeRouting as a real KiCad board, not
        just a synthetic text snapshot.

        Behavior:
        - rewrites the board outline to match the subcircuit-local board size
        - moves footprints that exist in `state.components`
        - optionally removes footprints not present in the subcircuit state
        - strips non-outline board drawings/text from the source board
        - optionally clears existing tracks/vias and copper zones
        - recreates traces/vias from the provided `BoardState`
        """
        self._ensure_loaded()
        board = self.board

        component_map = state.components or {}

        outline_left_mm = state.board_outline[0].x
        outline_top_mm = state.board_outline[0].y
        outline_right_mm = state.board_outline[1].x
        outline_bottom_mm = state.board_outline[1].y

        self._apply_board_outline(
            max(1.0, outline_right_mm - outline_left_mm),
            max(1.0, outline_bottom_mm - outline_top_mm),
            left_mm=outline_left_mm,
            top_mm=outline_top_mm,
        )

        component_map = state.components or {}
        footprints = list(board.Footprints())

        for fp in footprints:
            ref = fp.GetReferenceAsString()
            comp = component_map.get(ref)
            if comp is None:
                if remove_unmapped_footprints:
                    board.Remove(fp)
                continue

            if fp.IsLocked():
                continue

            current_layer = _layer_to_enum(fp.GetLayer())
            if comp.layer != current_layer:
                fp.Flip(fp.GetPosition(), False)
            fp.SetPosition(
                pcbnew.VECTOR2I(
                    pcbnew.FromMM(comp.pos.x),
                    pcbnew.FromMM(comp.pos.y),
                )
            )
            fp.SetOrientationDegrees(comp.rotation)

        to_remove = []
        for drawing in board.GetDrawings():
            try:
                if drawing.GetLayer() == pcbnew.Edge_Cuts:
                    continue
            except Exception:
                pass
            to_remove.append(drawing)
        for drawing in to_remove:
            board.Remove(drawing)

        if clear_existing_tracks:
            to_remove = [track for track in board.GetTracks()]
            for track in to_remove:
                board.Remove(track)

        if clear_existing_zones:
            to_remove = [zone for zone in board.Zones() if not zone.GetIsRuleArea()]
            for zone in to_remove:
                board.Remove(zone)

        netinfo = board.GetNetInfo()

        def _resolve_net_code(net_name: str) -> int:
            if not net_name:
                return 0
            net_item = netinfo.GetNetItem(net_name)
            if net_item is None:
                return 0
            try:
                return int(net_item.GetNetCode())
            except Exception:
                return 0

        for trace in state.traces:
            seg = pcbnew.PCB_TRACK(board)
            seg.SetStart(
                pcbnew.VECTOR2I(
                    pcbnew.FromMM(trace.start.x),
                    pcbnew.FromMM(trace.start.y),
                )
            )
            seg.SetEnd(
                pcbnew.VECTOR2I(
                    pcbnew.FromMM(trace.end.x),
                    pcbnew.FromMM(trace.end.y),
                )
            )
            seg.SetLayer(_enum_to_layer(trace.layer))
            seg.SetWidth(pcbnew.FromMM(trace.width_mm))
            net_code = _resolve_net_code(trace.net)
            if net_code > 0:
                seg.SetNetCode(net_code)
            board.Add(seg)

        for via in state.vias:
            track_via = pcbnew.PCB_VIA(board)
            track_via.SetPosition(
                pcbnew.VECTOR2I(
                    pcbnew.FromMM(via.pos.x),
                    pcbnew.FromMM(via.pos.y),
                )
            )
            track_via.SetDrill(pcbnew.FromMM(via.drill_mm))
            try:
                track_via.SetWidth(pcbnew.FromMM(via.size_mm))
            except TypeError:
                track_via.SetWidth(pcbnew.F_Cu, pcbnew.FromMM(via.size_mm))
            net_code = _resolve_net_code(via.net)
            if net_code > 0:
                track_via.SetNetCode(net_code)
            board.Add(track_via)

        board.BuildConnectivity()
        out = output_path or self.pcb_path
        board.Save(out)
        print(f"Subcircuit board stamped to {out}")

    def _apply_board_outline(
        self,
        width_mm: float,
        height_mm: float,
        *,
        left_mm: float = 0.0,
        top_mm: float = 0.0,
    ):
        """Rewrite the Edge.Cuts rectangle to the given dimensions at a chosen origin."""
        board = self.board

        new_left = pcbnew.FromMM(left_mm)
        new_top = pcbnew.FromMM(top_mm)
        new_right = pcbnew.FromMM(left_mm + width_mm)
        new_bottom = pcbnew.FromMM(top_mm + height_mm)

        # Remove existing Edge.Cuts lines
        to_remove = []
        for dwg in board.GetDrawings():
            if dwg.GetLayer() == pcbnew.Edge_Cuts:
                to_remove.append(dwg)
        for dwg in to_remove:
            board.Remove(dwg)

        # Draw new rectangle
        corners = [
            (new_left, new_top),
            (new_right, new_top),
            (new_right, new_bottom),
            (new_left, new_bottom),
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

    def strip_zones(self):
        """Remove all non-rule-area copper zones from the board.

        Called before routing to remove pre-existing zones (e.g. F.Cu GND
        zone from the source PCB) that would interfere with the autoplacer's
        zone management.  Rule areas are preserved.

        Runs in a subprocess to avoid pcbnew SWIG corruption.
        """
        import subprocess

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import pcbnew\n"
                f"board = pcbnew.LoadBoard({self.pcb_path!r})\n"
                "to_remove = [z for z in board.Zones() if not z.GetIsRuleArea()]\n"
                "for z in to_remove:\n"
                "    board.Remove(z)\n"
                f"board.Save({self.pcb_path!r})\n"
                "print(len(to_remove))\n",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            # Take first line only — SWIG may print memory leak warnings after
            n = result.stdout.strip().split("\n")[0].strip()
            if n and n.isdigit() and int(n) > 0:
                print(f"  Stripped {n} pre-existing copper zone(s)")
        # Force reload on next access since file changed
        self.board = None

    def ensure_gnd_zone(self):
        """Create or update a GND copper pour zone covering the full board.

        Idempotent: if a zone already exists on the target layer with the
        target net, its outline is updated to match the current board
        dimensions. Otherwise a new zone is created.

        Controlled by config keys:
          gnd_zone_net (str): Net name, e.g. "GND". Empty string disables.
          gnd_zone_layer (str): "B.Cu" or "F.Cu".
          gnd_zone_margin_mm (float): Inset from board edge.
        """
        self._ensure_loaded()
        board = self.board

        zone_net_name = self.cfg.get("gnd_zone_net", "GND")
        if not zone_net_name:
            return  # Disabled

        layer_name = self.cfg.get("gnd_zone_layer", "B.Cu")
        target_layer = pcbnew.B_Cu if layer_name == "B.Cu" else pcbnew.F_Cu
        margin = pcbnew.FromMM(self.cfg.get("gnd_zone_margin_mm", 0.5))

        # Find the net
        gnd_net = board.GetNetInfo().GetNetItem(zone_net_name)
        if not gnd_net or gnd_net.GetNetCode() == 0:
            print(
                f"  WARNING: Net '{zone_net_name}' not found — skipping zone creation"
            )
            return

        # Compute board outline rectangle
        rect = board.GetBoardEdgesBoundingBox()
        x1 = rect.GetX() + margin
        y1 = rect.GetY() + margin
        x2 = x1 + rect.GetWidth() - 2 * margin
        y2 = y1 + rect.GetHeight() - 2 * margin

        # Look for existing zone on target layer with matching net
        existing_zone = None
        for zone in board.Zones():
            if (
                zone.GetLayer() == target_layer
                and zone.GetNetname() == zone_net_name
                and not zone.GetIsRuleArea()
            ):
                existing_zone = zone
                break

        if existing_zone:
            # Update outline to match current board size
            outline = existing_zone.Outline()
            outline.RemoveAllContours()
            outline.NewOutline()
            outline.Append(x1, y1)
            outline.Append(x2, y1)
            outline.Append(x2, y2)
            outline.Append(x1, y2)
        else:
            # Create new zone
            zone = pcbnew.ZONE(board)
            zone.SetNet(gnd_net)
            zone.SetLayer(target_layer)
            zone.SetIsRuleArea(False)
            zone.SetDoNotAllowTracks(False)
            zone.SetDoNotAllowVias(False)
            zone.SetDoNotAllowPads(False)
            zone.SetDoNotAllowCopperPour(False)
            zone.SetLocalClearance(pcbnew.FromMM(0.3))
            zone.SetMinThickness(pcbnew.FromMM(0.25))
            zone.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
            zone.SetThermalReliefGap(pcbnew.FromMM(0.5))
            zone.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.5))
            zone.SetAssignedPriority(0)
            outline = zone.Outline()
            outline.NewOutline()
            outline.Append(x1, y1)
            outline.Append(x2, y1)
            outline.Append(x2, y2)
            outline.Append(x1, y2)
            board.Add(zone)

        # Fill all zones
        filler = pcbnew.ZONE_FILLER(board)
        filler.Fill(board.Zones())
        print(f"  GND zone on {layer_name}: ensured and filled")
