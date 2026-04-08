#!/usr/bin/env python3
"""Delete all tracks for a specific net and re-route on a target layer.

Usage:
    python3 reroute_net.py <pcb> <net_name> [--layer B.Cu] [--in-place]
"""
import argparse
import math
import pcbnew


def reroute_net(pcb_path, net_name, target_layer_name="B.Cu", in_place=False):
    board = pcbnew.LoadBoard(pcb_path)

    target_layer = board.GetLayerID(target_layer_name)
    signal_width = pcbnew.FromMM(0.25)

    # Find and remove existing tracks for this net
    to_remove = []
    for t in board.GetTracks():
        if t.GetNetname() == net_name and not isinstance(t, pcbnew.PCB_VIA):
            to_remove.append(t)
    for t in to_remove:
        board.Remove(t)
    print(f"  Removed {len(to_remove)} tracks for {net_name}")

    # Get pad positions
    pads = []
    for pad in board.GetPads():
        if pad.GetNetname() == net_name:
            pos = pad.GetPosition()
            fp = pad.GetParentFootprint()
            ref = fp.GetReferenceAsString() if fp else "?"
            pads.append({
                "x": pos.x, "y": pos.y,
                "x_mm": pcbnew.ToMM(pos.x), "y_mm": pcbnew.ToMM(pos.y),
                "ref": ref, "pad": pad.GetNumber(),
                "layer": pad.GetLayer(),
            })

    if len(pads) < 2:
        print(f"  Only {len(pads)} pads for {net_name}, nothing to route")
        return

    net_code = board.GetNetInfo().GetNetItem(net_name).GetNetCode()

    # Build MST
    remaining = list(range(len(pads)))
    current = remaining.pop(0)
    edges = []
    while remaining:
        best_d, best_i = float("inf"), 0
        for i, idx in enumerate(remaining):
            d = math.hypot(pads[idx]["x"] - pads[current]["x"],
                           pads[idx]["y"] - pads[current]["y"])
            if d < best_d:
                best_d, best_i = d, i
        next_idx = remaining.pop(best_i)
        edges.append((current, next_idx))
        current = next_idx

    # Route each edge
    for i, j in edges:
        p1, p2 = pads[i], pads[j]
        x1, y1 = p1["x"], p1["y"]
        x2, y2 = p2["x"], p2["y"]

        # Short connections (<3mm) stay on F.Cu
        dist_mm = math.hypot(p1["x_mm"] - p2["x_mm"], p1["y_mm"] - p2["y_mm"])
        if dist_mm < 3.0:
            track = pcbnew.PCB_TRACK(board)
            track.SetStart(pcbnew.VECTOR2I(int(x1), int(y1)))
            track.SetEnd(pcbnew.VECTOR2I(int(x2), int(y2)))
            track.SetLayer(pcbnew.F_Cu)
            track.SetNet(board.GetNetInfo().GetNetItem(net_name))
            track.SetWidth(signal_width)
            board.Add(track)
            print(f"    {p1['ref']}.{p1['pad']} -> {p2['ref']}.{p2['pad']} "
                  f"({dist_mm:.1f}mm) on F.Cu")
            continue

        # Longer connections: via down to target layer, L-route, via up
        via1 = pcbnew.PCB_VIA(board)
        via1.SetPosition(pcbnew.VECTOR2I(int(x1), int(y1)))
        via1.SetDrill(pcbnew.FromMM(0.3))
        via1.SetWidth(pcbnew.FromMM(0.6))
        via1.SetNet(board.GetNetInfo().GetNetItem(net_name))
        via1.SetViaType(pcbnew.VIATYPE_THROUGH)
        board.Add(via1)

        # L-shape on target layer (horizontal then vertical)
        mid_x, mid_y = x2, y1
        t1 = pcbnew.PCB_TRACK(board)
        t1.SetStart(pcbnew.VECTOR2I(int(x1), int(y1)))
        t1.SetEnd(pcbnew.VECTOR2I(int(mid_x), int(mid_y)))
        t1.SetLayer(target_layer)
        t1.SetNet(board.GetNetInfo().GetNetItem(net_name))
        t1.SetWidth(signal_width)
        board.Add(t1)

        if mid_y != y2:
            t2 = pcbnew.PCB_TRACK(board)
            t2.SetStart(pcbnew.VECTOR2I(int(mid_x), int(mid_y)))
            t2.SetEnd(pcbnew.VECTOR2I(int(x2), int(y2)))
            t2.SetLayer(target_layer)
            t2.SetNet(board.GetNetInfo().GetNetItem(net_name))
            t2.SetWidth(signal_width)
            board.Add(t2)

        via2 = pcbnew.PCB_VIA(board)
        via2.SetPosition(pcbnew.VECTOR2I(int(x2), int(y2)))
        via2.SetDrill(pcbnew.FromMM(0.3))
        via2.SetWidth(pcbnew.FromMM(0.6))
        via2.SetNet(board.GetNetInfo().GetNetItem(net_name))
        via2.SetViaType(pcbnew.VIATYPE_THROUGH)
        board.Add(via2)

        print(f"    {p1['ref']}.{p1['pad']} -> {p2['ref']}.{p2['pad']} "
              f"({dist_mm:.1f}mm) via {target_layer_name}")

    out = pcb_path if in_place else pcb_path.replace(".kicad_pcb", "_rerouted.kicad_pcb")
    board.Save(out)
    print(f"  Saved to: {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pcb")
    parser.add_argument("net")
    parser.add_argument("--layer", default="B.Cu")
    parser.add_argument("--in-place", action="store_true")
    args = parser.parse_args()
    reroute_net(args.pcb, args.net, args.layer, args.in_place)
