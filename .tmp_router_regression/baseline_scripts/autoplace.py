#!/usr/bin/env python3
"""CLI: Run placement optimization on a KiCad PCB.

Usage:
    python3 autoplace.py <file.kicad_pcb> [--output <out.kicad_pcb>] [--iterations 300]
"""
import argparse
import json
import sys

from autoplacer.pipeline import PlacementEngine


def main():
    parser = argparse.ArgumentParser(description="Autoplace KiCad PCB components")
    parser.add_argument("pcb", help="Input .kicad_pcb file")
    parser.add_argument("--output", "-o", help="Output file (default: in-place)")
    parser.add_argument("--iterations", "-n", type=int, default=300)
    args = parser.parse_args()

    engine = PlacementEngine()
    result = engine.run(args.pcb, args.output, max_iterations=args.iterations)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
