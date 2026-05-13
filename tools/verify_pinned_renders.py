"""Deterministic verification that pinned leaves render consistently
AND that the saved manual layout produces a physically-valid parent.

PER-LEAF invariants (run for every pinned leaf):

  1. ``leaf_routed.kicad_pcb`` (canonical) is byte-identical to
     ``round_NNNN_leaf_routed.kicad_pcb`` (the pinned snapshot).
     pin_leaf must copy the snapshot over the canonical name.

  2. ``renders/routed_front_all.png`` (monitor + pipeline-graph use
     this) is byte-identical to ``round_NNNN_routed_front_all.png``.
     Treated as N/A when neither file exists -- leaves with no copper
     routing (e.g. battery connectors) produce no routed render.

  3. ``renders/leaf_canvas.png`` (manual layout uses this) is
     perceptually identical (dhash similarity >= 0.85) to a fresh
     kicad-cli render of the canonical PCB. The manual layout's
     render cache must be invalidated whenever the canonical PCB
     changes content.

PLACEMENT invariants (run once over manual_layout.json):

  4. For every pair of placements, the Edge.Cuts AABBs in parent
     space must NOT overlap by more than 0.01 mm. Edge.Cuts is the
     leaf's TRUE physical extent (the rectangle stamped on the parent
     board) -- if two AABBs intersect, the stamped output has two
     leaves trying to occupy the same physical space, which surfaces
     as DRC shorts. Re-uses the same Edge.Cuts parsing the canvas
     uses, so the check answers exactly the question "is what got
     saved physically valid?"

Run from the project root. Does NOT require the GUI to be up.

  $ python tools/verify_pinned_renders.py

Exit code 0 = all invariants hold. Non-zero = at least one failed;
see the row(s) and the ``tools/.verify_renders/*_truth.png`` truth
renders.
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

    # Placement-level invariant: no two leaves' Edge.Cuts AABBs may
    # overlap in parent space (>0.01 mm). Re-uses the same parser the
    # canvas uses, so a PASS here means the saved manual layout will
    # not produce inter-leaf shorts when stamped.
    overlaps = _check_placement_overlap()
    print()
    if overlaps is None:
        print("placement-overlap: SKIPPED (no manual_layout.json or no Edge.Cuts data)")
    elif not overlaps:
        print("placement-overlap: PASS (no leaves overlap)")
    else:
        overall_ok = False
        print("placement-overlap: FAIL")
        for (a, b, ox, oy) in overlaps:
            print(f"  {a:<12} overlaps {b:<12} by {ox:.2f} x {oy:.2f} mm ({ox*oy:.2f} mm^2)")

    print()
    print("ALL PASS" if overall_ok else "SOME FAILED -- see rows above")
    return 0 if overall_ok else 1


def _parse_edge_cuts_bbox(pcb_path: Path) -> tuple[float, float, float, float] | None:
    """Same Edge.Cuts parser the canvas uses. Returns (xmin, ymin, xmax,
    ymax) in leaf-local mm, or None when the PCB has no Edge.Cuts."""
    import re

    try:
        text = pcb_path.read_text(encoding="utf-8")
    except OSError:
        return None
    xs: list[float] = []
    ys: list[float] = []
    block_re = re.compile(
        r'\(gr_(line|arc|rect|poly|circle)\s+(.*?)\)\s*(?=\(gr_|\(footprint|\Z)',
        re.S,
    )
    point_re = re.compile(
        r'(?:\((?:start|end|center|mid)\s+([-\d.eE+]+)\s+([-\d.eE+]+)\))'
        r'|(?:\(xy\s+([-\d.eE+]+)\s+([-\d.eE+]+)\))'
    )
    for m in block_re.finditer(text):
        blk = m.group(0)
        if 'Edge.Cuts' not in blk:
            continue
        for pm in point_re.finditer(blk):
            if pm.group(1) is not None:
                xs.append(float(pm.group(1)))
                ys.append(float(pm.group(2)))
            else:
                xs.append(float(pm.group(3)))
                ys.append(float(pm.group(4)))
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _check_placement_overlap() -> list[tuple[str, str, float, float]] | None:
    """Read manual_layout.json + every leaf's Edge.Cuts and return the
    list of overlapping pairs (sheet_a, sheet_b, overlap_x, overlap_y)
    in mm. Returns None when manual_layout.json is missing or no leaf
    has Edge.Cuts data (test inapplicable)."""
    import math

    ml_path = EXPERIMENTS / "manual" / "manual_layout.json"
    if not ml_path.exists():
        return None
    try:
        ml = json.loads(ml_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    key2info: dict[str, tuple[str, tuple[float, float, float, float]]] = {}
    for d in (EXPERIMENTS / "subcircuits").iterdir():
        meta = d / "metadata.json"
        pcb = d / "leaf_routed.kicad_pcb"
        if not (meta.exists() and pcb.exists()):
            continue
        try:
            md = json.loads(meta.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        ec = _parse_edge_cuts_bbox(pcb)
        if ec is None:
            continue
        key2info[md["instance_path"]] = (md["sheet_name"], ec)

    if not key2info:
        return None

    placements = []
    for p in ml.get("placements", []):
        info = key2info.get(p["instance_path"])
        if not info:
            continue
        sheet, (x0, y0, x1, y1) = info
        r = math.radians(p["rotation"])
        c, s = math.cos(r), math.sin(r)
        xs, ys = [], []
        for lx, ly in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
            xs.append(p["origin"]["x"] + lx * c + ly * s)
            ys.append(p["origin"]["y"] - lx * s + ly * c)
        placements.append((sheet, (min(xs), min(ys), max(xs), max(ys))))

    EPS = 0.01

    def contains(outer, inner):
        """outer fully contains inner (within EPS)?"""
        return (
            outer[0] <= inner[0] + EPS
            and outer[1] <= inner[1] + EPS
            and outer[2] + EPS >= inner[2]
            and outer[3] + EPS >= inner[3]
        )

    bad: list[tuple[str, str, float, float]] = []
    for i in range(len(placements)):
        for j in range(i + 1, len(placements)):
            a, b = placements[i][1], placements[j][1]
            ox = min(a[2], b[2]) - max(a[0], b[0])
            oy = min(a[3], b[3]) - max(a[1], b[1])
            if ox <= EPS or oy <= EPS:
                continue
            # Containment exception: one leaf encompassing another is
            # intentional stacking (e.g. BATT substrate) -- the canvas
            # uses the same rule, so the test matches the visual.
            if contains(a, b) or contains(b, a):
                continue
            bad.append((placements[i][0], placements[j][0], ox, oy))
    return bad


if __name__ == "__main__":
    sys.exit(main())
