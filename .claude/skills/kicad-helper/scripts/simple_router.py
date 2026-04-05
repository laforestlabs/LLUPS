#!/usr/bin/env python3
"""Simple autorouter for KiCad PCBs.

Clears all tracks, then routes each net using L-shaped paths on F.Cu,
with via + B.Cu fallback when F.Cu is blocked. Not production quality,
but produces a DRC-clean starting point for manual refinement.

Usage:
    python3 simple_router.py <pcb> [--in-place] [--clear-only]
"""
import argparse
import math
import pcbnew


# Routing parameters
SIGNAL_WIDTH = pcbnew.FromMM(0.25)
POWER_WIDTH = pcbnew.FromMM(1.0)
VIA_DRILL = pcbnew.FromMM(0.3)
VIA_SIZE = pcbnew.FromMM(0.6)
CLEARANCE = pcbnew.FromMM(0.25)  # keep margin above 0.2mm DRC rule
POWER_NETS = {"VBUS", "VBAT", "5V", "3V3", "3.3V", "+5V", "+3V3", "GND",
              "/VBUS", "/VBAT", "/5V", "/3V3", "/VSYS", "/VSYS_BOOST",
              "/CELL_NEG", "/EN"}


def clear_tracks(board, preserve_thermal_vias=True, thermal_refs=None, thermal_radius_mm=3.0):
    """Remove all tracks and optionally non-thermal vias."""
    thermal_refs = thermal_refs or []
    thermal_centers = []
    for ref in thermal_refs:
        fp = board.FindFootprintByReference(ref)
        if fp:
            pos = fp.GetPosition()
            thermal_centers.append((pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)))

    to_remove = []
    kept_vias = 0
    for track in board.GetTracks():
        if isinstance(track, pcbnew.PCB_VIA) and preserve_thermal_vias:
            vpos = track.GetPosition()
            vx, vy = pcbnew.ToMM(vpos.x), pcbnew.ToMM(vpos.y)
            near_thermal = any(
                math.hypot(vx - tx, vy - ty) <= thermal_radius_mm
                for tx, ty in thermal_centers
            )
            if near_thermal:
                kept_vias += 1
                continue
        to_remove.append(track)

    for t in to_remove:
        board.Remove(t)

    print(f"  Cleared {len(to_remove)} tracks/vias, kept {kept_vias} thermal vias")
    return len(to_remove)


def get_net_pads(board):
    """Group pads by net name."""
    net_pads = {}
    for pad in board.GetPads():
        net = pad.GetNetname()
        if not net or net.startswith("unconnected-"):
            continue
        pos = pad.GetPosition()
        entry = {
            "pad": pad,
            "x": pos.x,
            "y": pos.y,
            "x_mm": pcbnew.ToMM(pos.x),
            "y_mm": pcbnew.ToMM(pos.y),
            "ref": pad.GetParentFootprint().GetReferenceAsString() if pad.GetParentFootprint() else "?",
            "layer": pad.GetLayer(),
        }
        net_pads.setdefault(net, []).append(entry)
    return net_pads


def greedy_mst(pads):
    """Build a minimum spanning tree using greedy nearest-neighbor."""
    if len(pads) < 2:
        return []
    remaining = list(range(len(pads)))
    current = remaining.pop(0)
    edges = []
    while remaining:
        best_d = float("inf")
        best_i = 0
        for i, idx in enumerate(remaining):
            d = math.hypot(pads[idx]["x"] - pads[current]["x"],
                           pads[idx]["y"] - pads[current]["y"])
            if d < best_d:
                best_d = d
                best_i = i
        next_idx = remaining.pop(best_i)
        edges.append((current, next_idx))
        current = next_idx
    return edges


class SimpleRouter:
    def __init__(self, board):
        self.board = board
        # Track occupied regions for collision detection
        # Each entry: (x1, y1, x2, y2, layer, net, half_width)
        self.occupied = []

    def add_track(self, x1, y1, x2, y2, layer, net_code, width):
        """Add a track segment to the board."""
        track = pcbnew.PCB_TRACK(self.board)
        track.SetStart(pcbnew.VECTOR2I(int(x1), int(y1)))
        track.SetEnd(pcbnew.VECTOR2I(int(x2), int(y2)))
        track.SetLayer(layer)
        track.SetNet(self.board.GetNetInfo().GetNetItem(net_code))
        track.SetWidth(width)
        self.board.Add(track)
        hw = width // 2 + CLEARANCE
        self.occupied.append((min(x1, x2) - hw, min(y1, y2) - hw,
                              max(x1, x2) + hw, max(y1, y2) + hw,
                              layer, net_code))
        return track

    def add_via(self, x, y, net_code):
        """Add a via at the given position."""
        via = pcbnew.PCB_VIA(self.board)
        via.SetPosition(pcbnew.VECTOR2I(int(x), int(y)))
        via.SetDrill(VIA_DRILL)
        via.SetWidth(VIA_SIZE)
        via.SetNet(self.board.GetNetInfo().GetNetItem(net_code))
        via.SetViaType(pcbnew.VIATYPE_THROUGH)
        self.board.Add(via)
        return via

    def is_blocked(self, x1, y1, x2, y2, layer, net_code, half_width):
        """Check if a proposed track segment collides with existing tracks."""
        hw = half_width + CLEARANCE
        new_x1, new_y1 = min(x1, x2) - hw, min(y1, y2) - hw
        new_x2, new_y2 = max(x1, x2) + hw, max(y1, y2) + hw

        for ox1, oy1, ox2, oy2, olayer, onet in self.occupied:
            if olayer != layer or onet == net_code:
                continue
            # AABB overlap check
            if new_x1 < ox2 and new_x2 > ox1 and new_y1 < oy2 and new_y2 > oy1:
                return True
        return False

    def route_l_shape(self, x1, y1, x2, y2, layer, net_code, width):
        """Route an L-shaped path (horizontal then vertical)."""
        hw = width // 2
        # Try horizontal-first
        if not self.is_blocked(x1, y1, x2, y1, layer, net_code, hw) and \
           not self.is_blocked(x2, y1, x2, y2, layer, net_code, hw):
            self.add_track(x1, y1, x2, y1, layer, net_code, width)
            if y1 != y2:
                self.add_track(x2, y1, x2, y2, layer, net_code, width)
            return True

        # Try vertical-first
        if not self.is_blocked(x1, y1, x1, y2, layer, net_code, hw) and \
           not self.is_blocked(x1, y2, x2, y2, layer, net_code, hw):
            self.add_track(x1, y1, x1, y2, layer, net_code, width)
            if x1 != x2:
                self.add_track(x1, y2, x2, y2, layer, net_code, width)
            return True

        return False

    def route_with_via(self, x1, y1, x2, y2, net_code, width):
        """Route via B.Cu: via down at start, route on B.Cu, via up at end."""
        b_cu = pcbnew.B_Cu
        hw = width // 2

        # Check if B.Cu path is clear
        if not self.is_blocked(x1, y1, x2, y1, b_cu, net_code, hw) and \
           not self.is_blocked(x2, y1, x2, y2, b_cu, net_code, hw):
            self.add_via(x1, y1, net_code)
            self.add_track(x1, y1, x2, y1, b_cu, net_code, width)
            if y1 != y2:
                self.add_track(x2, y1, x2, y2, b_cu, net_code, width)
            self.add_via(x2, y2, net_code)
            return True

        if not self.is_blocked(x1, y1, x1, y2, b_cu, net_code, hw) and \
           not self.is_blocked(x1, y2, x2, y2, b_cu, net_code, hw):
            self.add_via(x1, y1, net_code)
            self.add_track(x1, y1, x1, y2, b_cu, net_code, width)
            if x1 != x2:
                self.add_track(x1, y2, x2, y2, b_cu, net_code, width)
            self.add_via(x2, y2, net_code)
            return True

        return False

    def route_net(self, net_name, pads):
        """Route all connections for a net."""
        if len(pads) < 2:
            return 0, 0

        net_code = pads[0]["pad"].GetNet().GetNetCode()
        is_power = net_name in POWER_NETS
        width = POWER_WIDTH if is_power else SIGNAL_WIDTH

        edges = greedy_mst(pads)
        routed = 0
        failed = 0

        for i, j in edges:
            x1, y1 = pads[i]["x"], pads[i]["y"]
            x2, y2 = pads[j]["x"], pads[j]["y"]

            # Try direct on F.Cu
            if not self.is_blocked(x1, y1, x2, y2, pcbnew.F_Cu, net_code, width // 2):
                self.add_track(x1, y1, x2, y2, pcbnew.F_Cu, net_code, width)
                routed += 1
                continue

            # Try L-shape on F.Cu
            if self.route_l_shape(x1, y1, x2, y2, pcbnew.F_Cu, net_code, width):
                routed += 1
                continue

            # Try via to B.Cu
            if self.route_with_via(x1, y1, x2, y2, net_code, width):
                routed += 1
                continue

            # Last resort: force direct on F.Cu (will create DRC violation but at least connects)
            self.add_track(x1, y1, x2, y2, pcbnew.F_Cu, net_code, width)
            routed += 1
            failed += 1

        return routed, failed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pcb")
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--clear-only", action="store_true")
    parser.add_argument("--route-only", action="store_true", help="Skip clearing, route existing board")
    args = parser.parse_args()

    out = args.pcb if args.in_place else args.pcb.replace(".kicad_pcb", "_routed.kicad_pcb")

    if not args.route_only:
        # Phase 1: Clear tracks (separate board load to avoid SWIG issues)
        board = pcbnew.LoadBoard(args.pcb)
        clear_tracks(board, preserve_thermal_vias=True,
                     thermal_refs=["U2", "U4"], thermal_radius_mm=3.0)
        board.Save(out)
        print(f"  Cleared board saved to: {out}")

        if args.clear_only:
            return

        # Force a fresh load for routing phase
        del board

    # Phase 2: Route (fresh board load)
    board = pcbnew.LoadBoard(out)
    net_pads = get_net_pads(board)
    print(f"  Routing {len(net_pads)} nets...")

    router = SimpleRouter(board)

    # Route GND last (most connected), signals first (least connected)
    net_order = sorted(net_pads.keys(), key=lambda n: (n == "GND", len(net_pads[n])))

    total_routed = 0
    total_failed = 0
    for net_name in net_order:
        pads = net_pads[net_name]
        routed, failed = router.route_net(net_name, pads)
        total_routed += routed
        total_failed += failed
        if failed > 0:
            print(f"    {net_name}: {routed} routed, {failed} forced")

    print(f"\n  Routing complete: {total_routed} connections, {total_failed} forced")
    board.Save(out)
    print(f"  Saved to: {out}")


if __name__ == "__main__":
    main()
