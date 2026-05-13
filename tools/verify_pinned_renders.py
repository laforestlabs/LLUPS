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

REPRESENTATION-AGREEMENT invariants (per-leaf). The same physical
leaf is described by five files; they MUST agree because the manual
layout overlays them on one canvas and the parent stamper writes
from them too. Any drift here surfaces as the user seeing one
representation misaligned with another (e.g. a red Edge.Cuts overlay
that doesn't hug the silk frame). These checks lock the relationship
explicitly so the next drift fails CI rather than a screenshot.

  4. canvas PNG sidecar mm extent == Edge.Cuts AABB (within 0.01 mm).
  5. canvas PNG content (alpha-channel bbox in mm) is contained in
     the Edge.Cuts AABB (no rendered pixel hangs past the physical
     board edge; tolerance 0.05 mm per side for anti-aliased halos).
  6. ``solved_layout.json`` silk-poly bbox == Edge.Cuts AABB shrunk
     by SILK_TO_EDGE_INSET_MM on every side (within 0.01 mm).
  7. ``metadata.json`` ``local_board_outline`` width/height ==
     Edge.Cuts AABB width/height (within 0.01 mm).

PLACEMENT invariants (run once over manual_layout.json):

  8. For every pair of placements, the Edge.Cuts AABBs in parent
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

# Default uniform gap between silkscreen poly and Edge.Cuts on every
# side. Sourced from leaf_routing.py::_outline_around_geometry which
# sets ``edge_margin = silk_margin + 0.3`` (so the silk-to-edge gap is
# always 0.3 mm regardless of silk_margin). If you change that
# relationship in the leaf solver, update this constant too -- this
# test exists to catch silent drift.
SILK_TO_EDGE_INSET_MM = 0.30

# Tolerance for "two coordinates that come from the same physical
# thing should be equal". 0.01 mm = 10 microns, well below kicad-cli's
# output precision but above floating-point round-trip noise.
EPS_MM = 0.01

# Anti-aliased silk strokes can spill a fraction of a millimeter past
# the geometric edge they trace. Allow that much overshoot when
# checking that the rendered PNG stays inside Edge.Cuts.
ALPHA_OVERSHOOT_MM = 0.05


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

    # Representation-agreement invariants. For each pinned leaf, the
    # same physical board is described by five files; they MUST agree
    # because the manual layout overlays them on one canvas. Each row
    # reports four checks: sidecar==edge, alpha-bbox in-edge,
    # silk==edge-inset, metadata==edge. Any FAIL is what the user
    # would otherwise see as a visual misalignment in the canvas.
    print()
    print(f"{'leaf':<13}   sidecar=edge   alpha⊆edge   silk=edge-inset   meta=edge   verdict")
    print("-" * 80)
    for leaf_key, pin in pins.items():
        leaf_dir = EXPERIMENTS / "subcircuits" / leaf_key
        try:
            meta = json.loads((leaf_dir / "metadata.json").read_text())
            sheet = meta.get("sheet_name", leaf_key[:12])
        except (OSError, json.JSONDecodeError):
            sheet = leaf_key[:12]
        agree_ok, labels = _check_representation_agreement(leaf_dir)
        overall_ok = overall_ok and agree_ok
        sc, al, sk, md = labels
        verdict = "PASS" if agree_ok else "FAIL"
        print(
            f"  {sheet:<11}   "
            f"{sc:<13}  "
            f"{al:<11}  "
            f"{sk:<16}  "
            f"{md:<10}  "
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

    bad: list[tuple[str, str, float, float]] = []
    for i in range(len(placements)):
        for j in range(i + 1, len(placements)):
            a, b = placements[i][1], placements[j][1]
            ox = min(a[2], b[2]) - max(a[0], b[0])
            oy = min(a[3], b[3]) - max(a[1], b[1])
            if ox > EPS_MM and oy > EPS_MM:
                bad.append((placements[i][0], placements[j][0], ox, oy))
    return bad


def _read_canvas_extent(
    leaf_dir: Path,
) -> tuple[float, float, float, float] | None:
    """Read ``leaf_canvas.png.extent.json`` and return
    ``(x_mm, y_mm, w_mm, h_mm)`` or None when the sidecar is missing
    or malformed."""
    sidecar = leaf_dir / "renders" / "leaf_canvas.png.extent.json"
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return (
            float(data["x_mm"]),
            float(data["y_mm"]),
            float(data["width_mm"]),
            float(data["height_mm"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _silk_poly_bbox(
    leaf_dir: Path,
) -> tuple[float, float, float, float] | None:
    """Same silk-poly bbox reader as the manual layout runner uses --
    first ``kind=="poly"`` entry in ``solved_layout.json``'s
    ``silkscreen`` list. Returns ``(min_x, min_y, max_x, max_y)`` or
    None when no silk poly is present."""
    sl_path = leaf_dir / "solved_layout.json"
    try:
        sl = json.loads(sl_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for elem in sl.get("silkscreen", []) or []:
        if elem.get("kind") != "poly":
            continue
        xs, ys = [], []
        for pt in elem.get("points", []) or []:
            try:
                xs.append(float(pt["x"]))
                ys.append(float(pt["y"]))
            except (KeyError, TypeError, ValueError):
                continue
        if xs and ys:
            return (min(xs), min(ys), max(xs), max(ys))
        return None
    return None


def _metadata_outline_wh(leaf_dir: Path) -> tuple[float, float] | None:
    """Read ``metadata.json``'s ``local_board_outline`` and return
    ``(width_mm, height_mm)`` or None when absent."""
    meta_path = leaf_dir / "metadata.json"
    try:
        md = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    outline = md.get("local_board_outline") or {}
    try:
        return (
            float(outline["width_mm"]),
            float(outline["height_mm"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _alpha_bbox_mm(
    png_path: Path,
    extent: tuple[float, float, float, float],
) -> tuple[float, float, float, float] | None:
    """Bounding box of non-transparent pixels in ``png_path`` mapped
    back to leaf-local mm via the recorded mm extent. Returns
    ``(min_x, min_y, max_x, max_y)`` in mm or None on read failure
    or fully-transparent image.

    Pixels with alpha < 16/255 are treated as transparent so that
    very faint anti-alias halos around stroke edges don't dominate
    the bbox. This is a "does the rendered content stay inside the
    physical board?" check, not a sub-pixel-perfect stroke audit.
    """
    try:
        img = Image.open(png_path).convert("RGBA")
    except (OSError, ValueError):
        return None
    alpha = img.split()[3]
    bbox_px = alpha.point(lambda a: 255 if a >= 16 else 0).getbbox()
    if bbox_px is None:
        return None
    x0_px, y0_px, x1_px, y1_px = bbox_px  # x1, y1 are exclusive
    img_w, img_h = img.size
    if img_w <= 0 or img_h <= 0:
        return None
    ex0, ey0, ew, eh = extent
    # Linear px -> mm. Pillow's getbbox returns half-open coords so
    # x1_px / y1_px already point one past the last opaque pixel,
    # which is the right "right edge" in mm.
    sx = ew / img_w
    sy = eh / img_h
    return (
        ex0 + x0_px * sx,
        ey0 + y0_px * sy,
        ex0 + x1_px * sx,
        ey0 + y1_px * sy,
    )


def _check_representation_agreement(
    leaf_dir: Path,
) -> tuple[bool, tuple[str, str, str, str]]:
    """Run the four per-leaf representation-agreement invariants and
    return ``(ok, (sidecar_label, alpha_label, silk_label, meta_label))``.

    Labels are short status strings for the row print:
      - ``"Y"`` / ``"N"`` for pass / fail
      - ``"N/A"`` when the input file is missing (counts as PASS so a
        leaf without copper routing doesn't fail; the existing tests
        already cover the missing-file case)
      - ``"DELTA=<n>"`` on FAIL when a numeric delta clarifies it
    """
    pcb = leaf_dir / "leaf_routed.kicad_pcb"
    canvas_png = leaf_dir / "renders" / "leaf_canvas.png"
    ec = _parse_edge_cuts_bbox(pcb) if pcb.exists() else None
    if ec is None:
        # No Edge.Cuts data: every downstream check is inapplicable.
        return True, ("N/A", "N/A", "N/A", "N/A")
    ex0, ey0, ex1, ey1 = ec
    ew, eh = ex1 - ex0, ey1 - ey0

    extent = _read_canvas_extent(leaf_dir) if canvas_png.exists() else None
    if extent is None:
        sidecar_ok = True
        sidecar_label = "N/A"
        alpha_ok = True
        alpha_label = "N/A"
    else:
        ix0, iy0, iw, ih = extent
        deltas = (
            abs(ix0 - ex0),
            abs(iy0 - ey0),
            abs(iw - ew),
            abs(ih - eh),
        )
        sidecar_ok = max(deltas) <= EPS_MM
        sidecar_label = (
            "Y" if sidecar_ok
            else f"d={max(deltas):.2f}mm"
        )
        ab = _alpha_bbox_mm(canvas_png, extent)
        if ab is None:
            alpha_ok = True
            alpha_label = "N/A"
        else:
            ax0, ay0, ax1, ay1 = ab
            overshoot = max(
                ex0 - ax0,
                ey0 - ay0,
                ax1 - ex1,
                ay1 - ey1,
            )
            alpha_ok = overshoot <= ALPHA_OVERSHOOT_MM
            alpha_label = (
                "Y" if alpha_ok
                else f"+{overshoot:.2f}mm"
            )

    silk = _silk_poly_bbox(leaf_dir)
    if silk is None:
        silk_ok = True
        silk_label = "N/A"
    else:
        sx0, sy0, sx1, sy1 = silk
        # Expected: silk == Edge.Cuts shrunk by SILK_TO_EDGE_INSET_MM
        # on every side. Compute the absolute discrepancy per side
        # and FAIL if any exceeds the tolerance.
        expected = (
            ex0 + SILK_TO_EDGE_INSET_MM,
            ey0 + SILK_TO_EDGE_INSET_MM,
            ex1 - SILK_TO_EDGE_INSET_MM,
            ey1 - SILK_TO_EDGE_INSET_MM,
        )
        max_delta = max(
            abs(sx0 - expected[0]),
            abs(sy0 - expected[1]),
            abs(sx1 - expected[2]),
            abs(sy1 - expected[3]),
        )
        silk_ok = max_delta <= EPS_MM
        silk_label = "Y" if silk_ok else f"d={max_delta:.2f}mm"

    meta = _metadata_outline_wh(leaf_dir)
    if meta is None:
        meta_ok = True
        meta_label = "N/A"
    else:
        mw, mh = meta
        max_delta = max(abs(mw - ew), abs(mh - eh))
        meta_ok = max_delta <= EPS_MM
        meta_label = "Y" if meta_ok else f"d={max_delta:.2f}mm"

    ok = sidecar_ok and alpha_ok and silk_ok and meta_ok
    return ok, (sidecar_label, alpha_label, silk_label, meta_label)


if __name__ == "__main__":
    sys.exit(main())
