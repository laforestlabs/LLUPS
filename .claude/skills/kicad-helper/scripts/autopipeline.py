#!/usr/bin/env python3
"""CLI: Run full placement + routing pipeline on a KiCad PCB.

Usage:
    python3 autopipeline.py <file.kicad_pcb> [--output <out.kicad_pcb>]
"""
import argparse
import json

from autoplacer.pipeline import FullPipeline


def main():
    parser = argparse.ArgumentParser(description="Full autoplace + autoroute pipeline")
    parser.add_argument("pcb", help="Input .kicad_pcb file")
    parser.add_argument("--output", "-o", help="Output file (default: in-place)")
    args = parser.parse_args()

    pipeline = FullPipeline()
    result = pipeline.run(args.pcb, args.output)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
