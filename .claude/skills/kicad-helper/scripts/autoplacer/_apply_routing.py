#!/usr/bin/env python3
"""Subprocess worker: applies routing data to a KiCad PCB.

Run in a separate process to avoid SWIG memory corruption
when loading a board multiple times in the same process.

Usage: python3 _apply_routing.py <routing_data.json>
"""
import json
import math
import sys

import pcbnew


def main():
    with open(sys.argv[1]) as f:
        data = json.load(f)

    board = pcbnew.LoadBoard(data["pcb_path"])

    # Clear existing tracks
    if data["clear_existing"]:
        thermal_centers = []
        if data["preserve_thermal"]:
            for ref in data["thermal_refs"]:
                fp = board.FindFootprintByReference(ref)
                if fp:
                    pos = fp.GetPosition()
                    thermal_centers.append(
                        (pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)))

        to_remove = []
        for track in board.GetTracks():
            if isinstance(track, pcbnew.PCB_VIA) and data["preserve_thermal"]:
                vpos = track.GetPosition()
                vx, vy = pcbnew.ToMM(vpos.x), pcbnew.ToMM(vpos.y)
                if any(math.hypot(vx - tx, vy - ty) <= data["thermal_radius_mm"]
                       for tx, ty in thermal_centers):
                    continue
            to_remove.append(track)
        for t in to_remove:
            board.Remove(t)

    # Build net lookup
    nets_by_name = {}
    for fp in board.Footprints():
        for pad in fp.Pads():
            nn = pad.GetNetname()
            if nn and nn not in nets_by_name:
                nets_by_name[nn] = pad.GetNet()

    # Add traces
    for seg in data["traces"]:
        track = pcbnew.PCB_TRACK(board)
        track.SetStart(pcbnew.VECTOR2I(
            pcbnew.FromMM(seg["sx"]), pcbnew.FromMM(seg["sy"])))
        track.SetEnd(pcbnew.VECTOR2I(
            pcbnew.FromMM(seg["ex"]), pcbnew.FromMM(seg["ey"])))
        layer = pcbnew.B_Cu if seg["layer"] == 1 else pcbnew.F_Cu
        track.SetLayer(layer)
        if seg["net"] in nets_by_name:
            track.SetNet(nets_by_name[seg["net"]])
        track.SetWidth(pcbnew.FromMM(seg["width"]))
        board.Add(track)

    # Add vias
    for v in data["vias"]:
        via = pcbnew.PCB_VIA(board)
        via.SetPosition(pcbnew.VECTOR2I(
            pcbnew.FromMM(v["x"]), pcbnew.FromMM(v["y"])))
        via.SetDrill(pcbnew.FromMM(v["drill"]))
        via.SetWidth(pcbnew.FromMM(v["size"]))
        if v["net"] in nets_by_name:
            via.SetNet(nets_by_name[v["net"]])
        via.SetViaType(pcbnew.VIATYPE_THROUGH)
        board.Add(via)

    board.Save(data["pcb_path"])


if __name__ == "__main__":
    main()
