#!/usr/bin/env python3
"""Smoke-test both stamping subprocess paths in under a minute.

Run this AFTER any change that touches:

* ``kicraft/autoplacer/hardware/_stamp_subcircuit_subprocess.py`` or
  the ``stamp_subcircuit_board_*`` family that drives it,
* ``kicraft/cli/_parent_stamp_subprocess.py`` or its caller in
  ``compose_subcircuits._stamp_parent_board``,
* anything else that introspects ``board.GetDrawings()`` /
  ``Footprints()`` / ``GetTracks()`` / ``Zones()`` via pcbnew.

Why both: the leaf and parent stamps are TWO DIFFERENT subprocess
scripts. Running ``compose_subcircuits`` only exercises the parent
path; running ``solve_subcircuits`` only exercises the leaf path. A
regression in either is easy to ship if you only test one.

Exits 0 on success, non-zero with the failing script's stderr on
failure.

Usage::

    python tools/smoke_stamp.py [--leaf NAME] [--keep-artifacts]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


_DEFAULT_LEAF = "BATT PROT"


def _project_root() -> Path:
    here = Path(__file__).resolve().parent
    return here.parent


def _run(label: str, cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    print(f"[{label}] $ {' '.join(cmd[:5])} ...")
    t0 = time.monotonic()
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    elapsed = time.monotonic() - t0
    rc_marker = "ok " if proc.returncode == 0 else "FAIL"
    print(f"[{label}] {rc_marker} rc={proc.returncode} elapsed={elapsed:.1f}s")
    return proc.returncode, proc.stdout, proc.stderr


def _pick_pcb_and_schematic(project_root: Path) -> tuple[Path, Path]:
    """Find the project's main .kicad_pcb / .kicad_sch pair."""
    pcbs = sorted(project_root.glob("*.kicad_pcb"))
    if not pcbs:
        sys.exit(f"error: no .kicad_pcb found in {project_root}")
    pcb = pcbs[0]
    sch = pcb.with_suffix(".kicad_sch")
    if not sch.exists():
        sys.exit(f"error: schematic {sch} not found")
    return pcb, sch


def _ensure_manual_layout(project_root: Path) -> Path:
    """Use the saved manual_layout.json if present, else synthesise one
    from the most recent auto layout so the parent-stamp path can run."""
    saved = project_root / ".experiments" / "manual" / "manual_layout.json"
    if saved.is_file():
        return saved

    sys.path.insert(0, str(project_root / "KiCraft"))
    from kicraft.gui.pages.manual_layout_runner import (  # type: ignore
        discover_leaves,
        load_initial_layout,
        save_manual_layout_json,
    )

    leaves = discover_leaves(project_root / ".experiments")
    if not leaves:
        sys.exit(
            "error: no solved leaves on disk; run leaves-only first or "
            "save a manual layout"
        )
    initial = load_initial_layout(project_root / ".experiments", leaves)
    out = save_manual_layout_json(project_root / ".experiments", initial, leaves)
    print(f"[setup] synthesised manual layout -> {out}")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--leaf",
        default=_DEFAULT_LEAF,
        help=f"Sheet name of leaf to test the leaf-stamp path on (default: '{_DEFAULT_LEAF}')",
    )
    p.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Keep the temporary output JSON for inspection",
    )
    args = p.parse_args(argv)

    project_root = _project_root()
    pcb, sch = _pick_pcb_and_schematic(project_root)
    print(f"project: {project_root}")
    print(f"pcb:     {pcb}")
    print(f"sch:     {sch}")
    print()

    failures: list[str] = []

    # Leaf stamp path (solve_subcircuits invokes
    # adapter._stamp_subcircuit_subprocess.py).
    leaf_rc, leaf_stdout, leaf_stderr = _run(
        "leaf-stamp",
        [
            sys.executable,
            "-m",
            "kicraft.cli.solve_subcircuits",
            str(sch),
            "--pcb",
            str(pcb),
            "--rounds",
            "1",
            "--seed",
            "42",
            "--route",
            "--workers",
            "1",
            "--only",
            args.leaf,
        ],
        cwd=project_root,
    )
    if leaf_rc != 0:
        failures.append("leaf-stamp")
        print("=== leaf-stamp stderr ===")
        print(leaf_stderr[:4000])
    elif "routed        : True" not in leaf_stdout:
        # solve_subcircuits sometimes prints "routed: False" while
        # exiting 0 if the round was rejected for non-stamp reasons.
        # That's fine for the smoke goal (stamp didn't crash) but
        # worth surfacing.
        print("[leaf-stamp] note: solver exited 0 but reported routed=False")

    # Parent stamp path (compose_subcircuits invokes
    # _parent_stamp_subprocess.py).
    manual_layout = _ensure_manual_layout(project_root)
    with tempfile.TemporaryDirectory(prefix="smoke_stamp_") as td:
        output = Path(td) / "parent_smoke.json"
        parent_rc, parent_stdout, parent_stderr = _run(
            "parent-stamp",
            [
                sys.executable,
                "-m",
                "kicraft.cli.compose_subcircuits",
                "--project",
                str(project_root),
                "--parent",
                "/",
                "--pcb",
                str(pcb),
                "--manual-layout",
                str(manual_layout),
                "--stamp",
                "--output",
                str(output),
            ],
            cwd=project_root,
        )
        if parent_rc != 0:
            failures.append("parent-stamp")
            print("=== parent-stamp stderr ===")
            print(parent_stderr[:4000])
        else:
            try:
                payload = json.loads(output.read_text())
                state = payload.get("state", {})
                tier = state.get("tier", "?")
                print(f"[parent-stamp] tier={tier}")
            except (OSError, json.JSONDecodeError):
                pass
        if args.keep_artifacts and output.exists():
            keep = project_root / ".experiments" / "manual" / "smoke_stamp_output.json"
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(output, keep)
            print(f"[parent-stamp] kept output: {keep}")

    print()
    if failures:
        print(f"FAIL: {', '.join(failures)} (smoke test detected stamping breakage)")
        return 1
    print("OK: both stamping subprocess paths executed cleanly")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
