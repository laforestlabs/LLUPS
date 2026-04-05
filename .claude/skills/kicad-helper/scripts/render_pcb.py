#!/usr/bin/env python3
"""Render PCB layers to PNG images for visual analysis."""
import argparse
import os
import subprocess
import sys
import tempfile


# Layer sets for different views
VIEWS = {
    "front_all": {
        "layers": "F.Cu,F.SilkS,F.Mask,Edge.Cuts",
        "desc": "Front copper + silkscreen + mask + outline",
    },
    "back_all": {
        "layers": "B.Cu,B.SilkS,B.Mask,Edge.Cuts",
        "desc": "Back copper + silkscreen + mask + outline",
        "mirror": True,
    },
    "copper_both": {
        "layers": "F.Cu,B.Cu,Edge.Cuts",
        "desc": "Both copper layers + outline",
    },
    "front_copper": {
        "layers": "F.Cu,Edge.Cuts",
        "desc": "Front copper traces and pads only",
    },
    "back_copper": {
        "layers": "B.Cu,Edge.Cuts",
        "desc": "Back copper (ground plane, traces)",
        "mirror": True,
    },
    "courtyard": {
        "layers": "F.CrtYd,B.CrtYd,Edge.Cuts",
        "desc": "Component courtyards for overlap review",
    },
}


def render_view(pcb_path, view_name, view_cfg, output_dir, dpi=300, max_px=2000):
    """Render a single view to PNG. Returns output path or None on failure."""
    svg_path = os.path.join(output_dir, f"{view_name}.svg")
    png_path = os.path.join(output_dir, f"{view_name}.png")

    cmd = [
        "kicad-cli", "pcb", "export", "svg",
        "--layers", view_cfg["layers"],
        "--mode-single",
        "--fit-page-to-board",
        "--exclude-drawing-sheet",
        "--drill-shape-opt", "2",
        "-o", svg_path,
    ]
    if view_cfg.get("mirror"):
        cmd.append("--mirror")
    cmd.append(pcb_path)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  SVG export failed for {view_name}: {result.stderr}", file=sys.stderr)
        return None

    # Convert SVG to PNG
    result = subprocess.run([
        "magick", "-density", str(dpi),
        svg_path, "-resize", f"{max_px}x{max_px}",
        png_path,
    ], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  PNG conversion failed for {view_name}: {result.stderr}", file=sys.stderr)
        return None

    # Clean up SVG
    os.remove(svg_path)
    return png_path


def render_all(pcb_path, output_dir, views=None):
    """Render all (or selected) views. Returns dict of view_name -> png_path."""
    os.makedirs(output_dir, exist_ok=True)
    selected = views or list(VIEWS.keys())
    results = {}

    for name in selected:
        if name not in VIEWS:
            print(f"  Unknown view: {name}", file=sys.stderr)
            continue
        path = render_view(pcb_path, name, VIEWS[name], output_dir)
        if path:
            results[name] = path
            size_kb = os.path.getsize(path) / 1024
            print(f"  {name}: {path} ({size_kb:.0f} KB)")

    return results


def main():
    parser = argparse.ArgumentParser(description="Render PCB layers to PNG")
    parser.add_argument("pcb", help="Path to .kicad_pcb file")
    parser.add_argument("--output-dir", default=None, help="Output directory (default: renders/ next to PCB)")
    parser.add_argument("--views", nargs="+", choices=list(VIEWS.keys()),
                        help="Specific views to render (default: all)")
    parser.add_argument("--list", action="store_true", help="List available views")
    args = parser.parse_args()

    if args.list:
        for name, cfg in VIEWS.items():
            print(f"  {name:<20} {cfg['desc']}")
        return

    out_dir = args.output_dir or os.path.join(os.path.dirname(args.pcb) or ".", "renders")
    print(f"Rendering {args.pcb}:")
    results = render_all(args.pcb, out_dir, args.views)
    print(f"\n{len(results)} views rendered to {out_dir}")


if __name__ == "__main__":
    main()
