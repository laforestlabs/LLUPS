#!/usr/bin/env python3
"""CLI: Run A* autorouter with rip-up/re-route on a KiCad PCB.

Usage:
    python3 autoroute.py <file.kicad_pcb> [--output <out.kicad_pcb>] [--no-rrr]
"""
import argparse
import json
import sys

from autoplacer.pipeline import RoutingEngine


def main():
    parser = argparse.ArgumentParser(description="Autoroute KiCad PCB")
    parser.add_argument("pcb", help="Input .kicad_pcb file")
    parser.add_argument("--output", "-o", help="Output file (default: in-place)")
    parser.add_argument("--no-rrr", action="store_true",
                        help="Skip rip-up and re-route")
    args = parser.parse_args()

    engine = RoutingEngine()
    result = engine.run(args.pcb, args.output, rip_up=not args.no_rrr)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
