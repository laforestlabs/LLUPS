"""Deterministic verification that pinned leaves render consistently.

For every pinned leaf, verify three invariants:

  1. ``leaf_routed.kicad_pcb`` (canonical) is byte-identical to
     ``round_NNNN_leaf_routed.kicad_pcb`` (the pinned snapshot).
     pin_leaf must copy the snapshot over the canonical name.

  2. ``renders/routed_front_all.png`` (monitor + pipeline-graph use
     this) is byte-identical to ``round_NNNN_routed_front_all.png``.
     pin_leaf must copy the round's render snapshots, not just the
     core three files. Treated as N/A when neither file exists --
     leaves with no copper routing (e.g. battery connectors) produce
     no routed render.

  3. ``renders/leaf_canvas.png`` (manual layout uses this) is
     perceptually identical (dhash similarity >= 0.85) to a fresh
     kicad-cli render of the canonical PCB. The manual layout's
     render cache must be invalidated whenever the canonical PCB
     changes content -- including pin operations that use
     shutil.copy2 / shutil.copy and may set mtimes earlier than the
     cached PNG.

Run from the project root. Does NOT require the GUI to be up: works
entirely off the on-disk artifacts the GUI serves.

  $ python tools/verify_pinned_renders.py

Exit code 0 = all pinned leaves consistent. Non-zero = at least one
canonical artifact disagreed with the pinned round; see the failing
row(s) plus ``tools/.verify_renders/<sheet>_truth.png`` for the truth
render that was compared against.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("Install Pillow: pip install pillow", file=sys.stderr)
    sys.exit(2)


EXPERIMENTS = Path(__file__).resolve().parent.parent / ".experiments"
OUT_DIR = Path(__file__).resolve().parent / ".verify_renders"


def md5_hex(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def _dhash(p: Path) -> int:
    img = Image.open(p).convert("L").resize((17, 16), Image.LANCZOS)
    px = img.load()
    bits = [1 if px[x, y] > px[x + 1, y] else 0 for y in range(16) for x in range(16)]
    return int("".join(str(b) for b in bits), 2)


def perceptual_sim(p1: Path, p2: Path) -> float:
    """1.0 == identical, 0.0 == completely different. Robust against
    subtle anti-aliasing differences while catching wholesale layout
    swaps."""
    return 1.0 - bin(_dhash(p1) ^ _dhash(p2)).count("1") / 256.0


def render_truth(pcb: Path, out: Path) -> None:
    """Same kicad-cli args as KiCraft/kicraft/gui/pages/leaf_canvas_render.py.
    A fresh render of the canonical PCB is the truth the manual-layout
    canvas should match."""
    svg = out.with_suffix(".svg")
    try:
        subprocess.run(
            [
                "kicad-cli", "pcb", "export", "svg",
                "--layers", "F.Cu,F.SilkS,Edge.Cuts",
                "--mode-single", "--fit-page-to-board",
                "--exclude-drawing-sheet", "--drill-shape-opt", "2",
                "-o", str(svg), str(pcb),
            ],
            check=True, capture_output=True, timeout=30,
        )
        subprocess.run(
            [
                "magick", "-background", "none", "-density", "420",
                str(svg), "PNG32:" + str(out),
            ],
            check=True, capture_output=True, timeout=30,
        )
    finally:
        svg.unlink(missing_ok=True)


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    pins_path = EXPERIMENTS / "pins.json"
    if not pins_path.exists():
        print("No pins.json — nothing to verify.")
        return 0
    pins = json.loads(pins_path.read_text()).get("pinned_leaves", {})
    if not pins:
        print("No pinned leaves — nothing to verify.")
        return 0

    print(f"{'leaf':<13} pin  pcb=pin   monitor=pin   canvas=truth   verdict")
    print("-" * 72)

    overall_ok = True
    for leaf_key, pin in pins.items():
        leaf_dir = EXPERIMENTS / "subcircuits" / leaf_key
        try:
            meta = json.loads((leaf_dir / "metadata.json").read_text())
            sheet = meta.get("sheet_name", leaf_key[:12])
        except (OSError, json.JSONDecodeError):
            sheet = leaf_key[:12]
        r = int(pin["round"])

        canonical_pcb = leaf_dir / "leaf_routed.kicad_pcb"
        pinned_pcb = leaf_dir / f"round_{r:04d}_leaf_routed.kicad_pcb"
        canonical_render = leaf_dir / "renders/routed_front_all.png"
        pinned_render = leaf_dir / f"renders/round_{r:04d}_routed_front_all.png"
        canvas = leaf_dir / "renders/leaf_canvas.png"
        truth = OUT_DIR / f"{sheet}_truth.png"

        # 1) canonical PCB == pinned snapshot PCB (must be exact)
        if canonical_pcb.exists() and pinned_pcb.exists():
            pcb_ok = md5_hex(canonical_pcb) == md5_hex(pinned_pcb)
            pcb_label = "Y" if pcb_ok else "N"
        else:
            pcb_ok = False
            pcb_label = "MISS"

        # 2) monitor render == pinned snapshot render (or N/A)
        if not canonical_render.exists() and not pinned_render.exists():
            mon_ok = True
            mon_label = "N/A"
        elif canonical_render.exists() and pinned_render.exists():
            mon_ok = md5_hex(canonical_render) == md5_hex(pinned_render)
            mon_label = "Y" if mon_ok else "N"
        else:
            mon_ok = False
            mon_label = "MISS"

        # 3) manual layout canvas ~= fresh kicad-cli truth
        if canvas.exists() and canonical_pcb.exists():
            try:
                render_truth(canonical_pcb, truth)
                s = perceptual_sim(canvas, truth)
                canvas_ok = s >= 0.85
                canvas_label = f"{s:.2f}"
            except subprocess.CalledProcessError:
                canvas_ok = False
                canvas_label = "ERR"
        else:
            canvas_ok = False
            canvas_label = "MISS"

        ok = pcb_ok and mon_ok and canvas_ok
        overall_ok = overall_ok and ok
        verdict = "PASS" if ok else "FAIL"
        print(
            f"  {sheet:<11} R{r}   "
            f"{pcb_label:<5}    "
            f"{mon_label:<5}        "
            f"{canvas_label:<5}         "
            f"{verdict}"
        )

    print()
    print("ALL PASS" if overall_ok else "SOME FAILED -- see rows above")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
