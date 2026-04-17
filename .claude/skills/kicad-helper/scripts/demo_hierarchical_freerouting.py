#!/usr/bin/env python3
"""Visible hierarchical FreeRouting demo for LLUPS.

This script creates a real, viewable demo of the hierarchical routing flow:

1. Load solved subcircuit artifacts from `.experiments/subcircuits`
2. Compose them into the selected parent sheet
3. Preserve already-routed child copper in the parent composition
4. Stamp that composed state into a real KiCad `.kicad_pcb`
5. Export a DSN from that stamped board without clearing existing traces
6. Run FreeRouting so the parent session starts with child routing already loaded
7. Import the resulting SES back into a routed parent `.kicad_pcb`
8. Optionally render PNG snapshots and open the results on screen

This is intended as a demo/inspection tool, not a production pipeline.

Example:
    python3 .claude/skills/kicad-helper/scripts/demo_hierarchical_freerouting.py \
        --project . \
        --parent / \
        --base-pcb LLUPS.kicad_pcb \
        --open

Notes:
- This script assumes solved subcircuit artifacts already exist.
- For the most convincing demo, regenerate routed leaf artifacts first:
    python3 .claude/skills/kicad-helper/scripts/solve_subcircuits.py LLUPS.kicad_sch \
        --only CHARGER --only "LDO 3.3V" --only "BOOST 5V" --rounds 1 --route
- FreeRouting must be installed and the configured jar path must exist.
- The built-in preview renderer is intentionally optimized for human readability:
  it crops to actual geometry, uses a compact grid composition, and overlays
  subcircuit labels directly on the preview image.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import site
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


def _ensure_kicad_python_path() -> None:
    """Ensure KiCad Python bindings are importable."""
    try:
        import pcbnew  # noqa: F401

        return
    except Exception:
        pass

    ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    candidates = [
        f"/usr/lib/python{ver}/site-packages",
        f"/usr/lib64/python{ver}/site-packages",
        "/usr/lib/python3/dist-packages",
        "/usr/lib64/python3/dist-packages",
    ]

    try:
        candidates.extend(site.getsitepackages())
    except Exception:
        pass
    try:
        candidates.append(site.getusersitepackages())
    except Exception:
        pass

    seen = set()
    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        pcbnew_py = Path(path) / "pcbnew.py"
        pcbnew_pkg = Path(path) / "pcbnew"
        if pcbnew_py.exists() or pcbnew_pkg.exists():
            if path not in sys.path:
                sys.path.append(path)

    try:
        import pcbnew  # noqa: F401
    except Exception as exc:
        raise ModuleNotFoundError(
            "KiCad Python module 'pcbnew' not found. "
            "Install KiCad bindings or set PYTHONPATH to KiCad site-packages."
        ) from exc


_ensure_kicad_python_path()

from autoplacer.brain.hierarchy_parser import parse_hierarchy
from autoplacer.brain.subcircuit_composer import build_parent_composition
from autoplacer.brain.subcircuit_instances import load_solved_artifacts
from autoplacer.config import DEFAULT_CONFIG, LLUPS_CONFIG, load_project_config
from autoplacer.freerouting_runner import (
    _kicad_subprocess_env,
    export_dsn,
    import_ses,
    parse_freerouting_output,
    run_freerouting,
)
from autoplacer.hardware.adapter import KiCadAdapter
from compose_subcircuits import (
    _discover_artifact_dirs,
    _filter_artifacts_for_parent,
    _filter_loaded_artifacts,
    _select_parent_definition,
)


def _validate_parent_board_geometry(pcb_path: Path) -> None:
    """Clamp stamped parent copper to the board outline before DSN export.

    FreeRouting's DSN reader is stricter than KiCad about copper geometry that
    lands outside the Edge.Cuts rectangle. The parent composition currently
    stamps preloaded child copper plus inferred parent interconnect traces, so
    we do a final cleanup pass here to ensure every segment endpoint and via
    center is inside the board bounds before exporting DSN.
    """
    script = (
        "import pcbnew\n"
        f"board = pcbnew.LoadBoard({str(pcb_path)!r})\n"
        "if board is None:\n"
        f"    raise RuntimeError('Failed to load board: {str(pcb_path)}')\n"
        "rect = board.GetBoardEdgesBoundingBox()\n"
        "if rect.GetWidth() <= 0 or rect.GetHeight() <= 0:\n"
        "    raise RuntimeError('Board outline is empty before DSN export')\n"
        "min_x = rect.GetX()\n"
        "min_y = rect.GetY()\n"
        "max_x = rect.GetX() + rect.GetWidth()\n"
        "max_y = rect.GetY() + rect.GetHeight()\n"
        "margin = pcbnew.FromMM(0.05)\n"
        "min_x += margin\n"
        "min_y += margin\n"
        "max_x -= margin\n"
        "max_y -= margin\n"
        "removed = 0\n"
        "clamped = 0\n"
        "tracks = list(board.GetTracks())\n"
        "for item in tracks:\n"
        "    if isinstance(item, pcbnew.PCB_VIA):\n"
        "        pos = item.GetPosition()\n"
        "        x = min(max(pos.x, min_x), max_x)\n"
        "        y = min(max(pos.y, min_y), max_y)\n"
        "        if x != pos.x or y != pos.y:\n"
        "            item.SetPosition(pcbnew.VECTOR2I(x, y))\n"
        "            clamped += 1\n"
        "        continue\n"
        "    start = item.GetStart()\n"
        "    end = item.GetEnd()\n"
        "    sx = min(max(start.x, min_x), max_x)\n"
        "    sy = min(max(start.y, min_y), max_y)\n"
        "    ex = min(max(end.x, min_x), max_x)\n"
        "    ey = min(max(end.y, min_y), max_y)\n"
        "    if sx == ex and sy == ey:\n"
        "        board.Remove(item)\n"
        "        removed += 1\n"
        "        continue\n"
        "    if sx != start.x or sy != start.y or ex != end.x or ey != end.y:\n"
        "        item.SetStart(pcbnew.VECTOR2I(sx, sy))\n"
        "        item.SetEnd(pcbnew.VECTOR2I(ex, ey))\n"
        "        clamped += 1\n"
        "board.BuildConnectivity()\n"
        f"board.Save({str(pcb_path)!r})\n"
        "print(f'validated_parent_geometry clamped={clamped} removed={removed}')\n"
    )
    _run_pcbnew_script(script)


def _load_config(config_path: str | None) -> dict[str, Any]:
    cfg: dict[str, Any] = {**DEFAULT_CONFIG, **LLUPS_CONFIG}
    if config_path:
        cfg.update(load_project_config(config_path))
    return cfg


def _resolve_project_dir(project: str | None) -> Path:
    if project:
        return Path(project).resolve()
    return Path(".").resolve()


def _resolve_base_pcb(project_dir: Path, base_pcb: str | None) -> Path:
    if base_pcb:
        return Path(base_pcb).resolve()
    return (project_dir / "LLUPS.kicad_pcb").resolve()


def _resolve_output_dir(project_dir: Path, output_dir: str | None) -> Path:
    if output_dir:
        return Path(output_dir).resolve()
    return (project_dir / ".experiments" / "hierarchical_freerouting_demo").resolve()


def _copy_base_board(base_pcb: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(base_pcb, destination)
    return destination


def _run_pcbnew_script(script: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=_kicad_subprocess_env(),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"pcbnew subprocess failed (rc={result.returncode}):\n{result.stderr}"
        )


def _count_tracks(pcb_path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, pcbnew\n"
                f"board = pcbnew.LoadBoard({str(pcb_path)!r})\n"
                "traces = vias = 0\n"
                "for t in board.GetTracks():\n"
                "    if isinstance(t, pcbnew.PCB_VIA):\n"
                "        vias += 1\n"
                "    else:\n"
                "        traces += 1\n"
                "print(json.dumps({'traces': traces, 'vias': vias}))\n"
            ),
        ],
        capture_output=True,
        text=True,
        env=_kicad_subprocess_env(),
    )
    if result.returncode != 0:
        return {"traces": 0, "vias": 0}
    try:
        return json.loads(result.stdout.strip())
    except Exception:
        return {"traces": 0, "vias": 0}


def _open_path(path: Path) -> None:
    if sys.platform.startswith("linux"):
        subprocess.Popen(["xdg-open", str(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        raise RuntimeError(f"Unsupported platform for opening files: {sys.platform}")


def _render_snapshot(
    pcb_path: Path,
    png_path: Path,
    title: str,
    composition=None,
) -> None:
    """Render a cropped, readable preview for hierarchical demo boards."""
    png_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tmp:
        svg_front = Path(tmp.name)
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tmp:
        svg_back = Path(tmp.name)

    try:
        subprocess.run(
            [
                "kicad-cli",
                "pcb",
                "export",
                "svg",
                "--layers",
                "F.Cu,F.SilkS,Edge.Cuts",
                "--mode-single",
                "--fit-page-to-board",
                "--exclude-drawing-sheet",
                "--drill-shape-opt",
                "2",
                "-o",
                str(svg_front),
                str(pcb_path),
            ],
            capture_output=True,
            check=True,
        )
        subprocess.run(
            [
                "kicad-cli",
                "pcb",
                "export",
                "svg",
                "--layers",
                "B.Cu,Edge.Cuts",
                "--mode-single",
                "--fit-page-to-board",
                "--exclude-drawing-sheet",
                "--drill-shape-opt",
                "2",
                "-o",
                str(svg_back),
                str(pcb_path),
            ],
            capture_output=True,
            check=True,
        )

        width_mm, height_mm = _board_size_from_pcb(pcb_path)
        canvas_w = 1600
        canvas_h = 1000
        margin_px = 70
        label_band_px = 120 if composition else 80

        usable_w = max(200, canvas_w - margin_px * 2)
        usable_h = max(200, canvas_h - margin_px * 2 - label_band_px)
        scale = min(
            usable_w / max(width_mm, 1.0),
            usable_h / max(height_mm, 1.0),
        )
        target_w = max(1, int(round(width_mm * scale)))
        target_h = max(1, int(round(height_mm * scale)))

        cmd = [
            "magick",
            "-density",
            "300",
            "(",
            "-background",
            "none",
            str(svg_back),
            "-resize",
            f"{target_w}x{target_h}!",
            "-channel",
            "A",
            "-evaluate",
            "multiply",
            "0.22",
            "+channel",
            ")",
            "(",
            "-background",
            "none",
            str(svg_front),
            "-resize",
            f"{target_w}x{target_h}!",
            ")",
            "-gravity",
            "northwest",
            "(",
            "-size",
            f"{canvas_w}x{canvas_h}",
            "xc:white",
            ")",
            "-reverse",
            "-compose",
            "over",
            "-flatten",
        ]

        board_x = (canvas_w - target_w) // 2
        board_y = margin_px

        cmd.extend(
            [
                "-fill",
                "none",
                "-stroke",
                "#D0D0D0",
                "-strokewidth",
                "2",
                "-draw",
                f"rectangle {board_x},{board_y} {board_x + target_w},{board_y + target_h}",
            ]
        )

        title_text = title
        cmd.extend(
            [
                "-fill",
                "#111111",
                "-gravity",
                "north",
                "-pointsize",
                "28",
                "-font",
                "DejaVu-Sans-Bold",
                "-annotate",
                "+0+18",
                title_text,
            ]
        )

        subtitle = f"{width_mm:.1f} mm × {height_mm:.1f} mm"
        cmd.extend(
            [
                "-fill",
                "#666666",
                "-gravity",
                "north",
                "-pointsize",
                "16",
                "-font",
                "DejaVu-Sans",
                "-annotate",
                "+0+54",
                subtitle,
            ]
        )

        if composition is not None:
            tl_x, tl_y = _board_origin_from_pcb(pcb_path)
            for child in composition.composed_children:
                bbox_tl, bbox_br = child.transformed.bounding_box
                cx_mm = (bbox_tl.x + bbox_br.x) / 2.0
                cy_mm = (bbox_tl.y + bbox_br.y) / 2.0
                px = board_x + int(round((cx_mm - tl_x) * scale))
                py = board_y + int(round((cy_mm - tl_y) * scale))

                label = child.sheet_name
                cmd.extend(
                    [
                        "-fill",
                        "rgba(255,255,255,0.88)",
                        "-stroke",
                        "#666666",
                        "-strokewidth",
                        "1",
                        "-draw",
                        f"roundrectangle {px - 70},{py - 18} {px + 70},{py + 18} 8,8",
                        "-fill",
                        "#111111",
                        "-stroke",
                        "none",
                        "-gravity",
                        "northwest",
                        "-pointsize",
                        "16",
                        "-font",
                        "DejaVu-Sans-Bold",
                        "-annotate",
                        f"+{px - 58}+{py - 14}",
                        label,
                    ]
                )

            summary = (
                f"Children: {len(composition.composed_children)}"
                f"   Components: {len(composition.board_state.components)}"
                f"   Traces: {len(composition.board_state.traces)}"
                f"   Routed parent interconnects: {len(composition.routed_interconnect_nets)}"
            )
            cmd.extend(
                [
                    "-fill",
                    "rgba(0,0,0,0.82)",
                    "-draw",
                    f"rectangle 0,{canvas_h - label_band_px} {canvas_w},{canvas_h}",
                    "-fill",
                    "#00AA44",
                    "-gravity",
                    "southwest",
                    "-pointsize",
                    "22",
                    "-font",
                    "DejaVu-Sans-Bold",
                    "-annotate",
                    "+28+58",
                    summary,
                ]
            )

        cmd.append(str(png_path))
        subprocess.run(cmd, capture_output=True, check=True)

        if png_path.exists():
            print(f"Rendered snapshot: {png_path}")
        else:
            print(f"WARNING: snapshot render did not produce {png_path}")
        print(f"Snapshot label: {title}")
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"WARNING: snapshot render failed for {png_path}: {exc}")
    finally:
        try:
            svg_front.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            svg_back.unlink(missing_ok=True)
        except Exception:
            pass


def _board_origin_from_pcb(pcb_path: Path) -> tuple[float, float]:
    """Return top-left board origin from Edge.Cuts geometry."""
    try:
        text = pcb_path.read_text(encoding="utf-8")
    except OSError:
        return (0.0, 0.0)

    coords = [
        (float(x), float(y))
        for x, y in re.findall(
            r"\((?:start|end)\s+([-\d.]+)\s+([-\d.]+)\)",
            text,
        )
    ]
    if not coords:
        return (0.0, 0.0)

    min_x = min(x for x, _ in coords)
    min_y = min(y for _, y in coords)
    return (min_x, min_y)


def _board_size_from_pcb(pcb_path: Path) -> tuple[float, float]:
    """Return board width/height from Edge.Cuts geometry."""
    try:
        text = pcb_path.read_text(encoding="utf-8")
    except OSError:
        return (140.0, 90.0)

    coords = [
        (float(x), float(y))
        for x, y in re.findall(
            r"\((?:start|end)\s+([-\d.]+)\s+([-\d.]+)\)",
            text,
        )
    ]
    if not coords:
        return (140.0, 90.0)

    min_x = min(x for x, _ in coords)
    max_x = max(x for x, _ in coords)
    min_y = min(y for _, y in coords)
    max_y = max(y for _, y in coords)
    return (max(1.0, max_x - min_x), max(1.0, max_y - min_y))


def _build_parent_composition_from_artifacts(
    project_dir: Path,
    parent_selector: str,
    only: list[str],
):
    artifact_dirs = _discover_artifact_dirs(project_dir)
    if not artifact_dirs:
        raise FileNotFoundError(
            f"No solved subcircuit artifacts found under {project_dir / '.experiments' / 'subcircuits'}"
        )

    loaded_artifacts = load_solved_artifacts([str(path) for path in artifact_dirs])
    loaded_artifacts = _filter_loaded_artifacts(loaded_artifacts, only)

    parent_definition = _select_parent_definition(project_dir, parent_selector)
    if parent_definition is None:
        raise ValueError(f"Could not resolve parent definition for {parent_selector!r}")

    loaded_artifacts = _filter_artifacts_for_parent(loaded_artifacts, parent_definition)
    if not loaded_artifacts:
        raise ValueError(
            f"No solved child artifacts found for parent {parent_definition.id.sheet_name}"
        )

    # Use a compact grid placement so the stamped parent board is readable
    # in screenshots and when opened in KiCad/FreeRouting.
    from autoplacer.brain.subcircuit_composer import ChildArtifactPlacement
    from autoplacer.brain.types import Point

    placements: list[ChildArtifactPlacement] = []
    spacing_mm = 12.0
    cols = 3

    max_width = max(
        (artifact.layout.width for artifact in loaded_artifacts), default=0.0
    )
    max_height = max(
        (artifact.layout.height for artifact in loaded_artifacts),
        default=0.0,
    )
    cell_w = max_width + spacing_mm
    cell_h = max_height + spacing_mm

    for index, artifact in enumerate(loaded_artifacts):
        row = index // cols
        col = index % cols
        placements.append(
            ChildArtifactPlacement(
                artifact=artifact,
                origin=Point(col * cell_w, row * cell_h),
                rotation=0.0,
            )
        )

    composition = build_parent_composition(
        parent_definition,
        child_artifact_placements=placements,
    )
    return parent_definition, loaded_artifacts, composition


def _write_demo_metadata(
    output_path: Path,
    payload: dict[str, Any],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a visible hierarchical FreeRouting demo board"
    )
    parser.add_argument(
        "--project",
        default=".",
        help="Project directory containing .experiments/subcircuits (default: .)",
    )
    parser.add_argument(
        "--parent",
        default="/",
        help="Parent sheet selector: sheet name, sheet file, or instance path (default: /)",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Restrict included solved artifacts by sheet name, file, or instance path",
    )
    parser.add_argument(
        "--base-pcb",
        help="Base KiCad PCB to stamp the composed routed state onto (default: LLUPS.kicad_pcb in project)",
    )
    parser.add_argument(
        "--config",
        help="Optional config file to merge on top of default/project config",
    )
    parser.add_argument(
        "--output-dir",
        help="Output directory for demo artifacts (default: .experiments/hierarchical_freerouting_demo)",
    )
    parser.add_argument(
        "--jar",
        help="Override FreeRouting jar path",
    )
    parser.add_argument(
        "--timeout-s",
        type=int,
        default=None,
        help="Override FreeRouting timeout in seconds",
    )
    parser.add_argument(
        "--max-passes",
        type=int,
        default=None,
        help="Override FreeRouting max passes",
    )
    parser.add_argument(
        "--skip-freerouting",
        action="store_true",
        help="Only stamp and export the preloaded parent board; do not run FreeRouting",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open generated board/snapshot files after creation",
    )
    parser.add_argument(
        "--render-png",
        action="store_true",
        help="Render PNG snapshots of the preloaded and final routed boards",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    project_dir = _resolve_project_dir(args.project)
    base_pcb = _resolve_base_pcb(project_dir, args.base_pcb)
    output_dir = _resolve_output_dir(project_dir, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not base_pcb.exists():
        print(f"error: base PCB not found: {base_pcb}", file=sys.stderr)
        return 2

    cfg = _load_config(args.config)
    if args.jar:
        cfg["freerouting_jar"] = args.jar
    if args.timeout_s is not None:
        cfg["freerouting_timeout_s"] = args.timeout_s
    if args.max_passes is not None:
        cfg["freerouting_max_passes"] = args.max_passes

    jar_path = cfg.get("freerouting_jar")
    if not args.skip_freerouting and (not jar_path or not Path(jar_path).exists()):
        print(
            "error: FreeRouting jar not found. Set --jar or configure freerouting_jar.",
            file=sys.stderr,
        )
        return 2

    try:
        parent_definition, loaded_artifacts, composition = (
            _build_parent_composition_from_artifacts(
                project_dir=project_dir,
                parent_selector=args.parent,
                only=args.only,
            )
        )
    except Exception as exc:
        print(f"error: failed to build parent composition: {exc}", file=sys.stderr)
        return 1

    preloaded_pcb = output_dir / "parent_preloaded.kicad_pcb"
    routed_pcb = output_dir / "parent_freerouted.kicad_pcb"
    dsn_path = output_dir / "parent_preloaded.dsn"
    ses_path = output_dir / "parent_freerouted.ses"
    metadata_path = output_dir / "demo_metadata.json"
    preloaded_png = output_dir / "parent_preloaded.png"
    routed_png = output_dir / "parent_freerouted.png"

    try:
        _copy_base_board(base_pcb, preloaded_pcb)

        adapter = KiCadAdapter(str(preloaded_pcb), cfg)
        adapter.stamp_board_state(
            composition.board_state,
            output_path=str(preloaded_pcb),
            clear_existing_tracks=True,
            clear_existing_zones=True,
        )

        _validate_parent_board_geometry(preloaded_pcb)

        preloaded_counts = _count_tracks(preloaded_pcb)

        export_dsn(str(preloaded_pcb), str(dsn_path))

        freerouting_stats: dict[str, Any] | None = None
        if not args.skip_freerouting:
            freerouting_stats = run_freerouting(
                str(dsn_path),
                str(ses_path),
                str(jar_path),
                timeout_s=int(cfg.get("freerouting_timeout_s", 120)),
                max_passes=int(cfg.get("freerouting_max_passes", 40)),
                work_dir=str(output_dir),
            )
            if freerouting_stats.get("returncode", 1) != 0 and not ses_path.exists():
                print(
                    "warning: FreeRouting did not produce an SES file; keeping only preloaded board",
                    file=sys.stderr,
                )
            elif ses_path.exists():
                import_ses(str(preloaded_pcb), str(ses_path), str(routed_pcb))

        final_board = routed_pcb if routed_pcb.exists() else preloaded_pcb
        final_counts = _count_tracks(final_board)

        if args.render_png:
            _render_snapshot(
                preloaded_pcb,
                preloaded_png,
                "Hierarchical parent board with routed child subcircuits preloaded",
                composition=composition,
            )
            _render_snapshot(
                final_board,
                routed_png,
                "Hierarchical parent board after FreeRouting session",
                composition=composition,
            )

        metadata = {
            "project_dir": str(project_dir),
            "parent": {
                "sheet_name": parent_definition.id.sheet_name,
                "sheet_file": parent_definition.id.sheet_file,
                "instance_path": parent_definition.id.instance_path,
            },
            "artifact_count": len(loaded_artifacts),
            "artifacts": [
                {
                    "sheet_name": artifact.layout.subcircuit_id.sheet_name,
                    "instance_path": artifact.layout.subcircuit_id.instance_path,
                    "component_count": len(artifact.layout.components),
                    "trace_count": len(artifact.layout.traces),
                    "via_count": len(artifact.layout.vias),
                    "anchor_count": len(artifact.layout.interface_anchors),
                    "artifact_dir": artifact.artifact_dir,
                }
                for artifact in loaded_artifacts
            ],
            "composition": {
                "component_count": len(composition.board_state.components),
                "trace_count": len(composition.board_state.traces),
                "via_count": len(composition.board_state.vias),
                "interconnect_net_count": len(
                    composition.hierarchy_state.interconnect_nets
                ),
                "routed_interconnect_net_count": len(
                    composition.routed_interconnect_nets
                ),
                "failed_interconnect_net_count": len(
                    composition.failed_interconnect_nets
                ),
                "notes": list(composition.notes),
            },
            "files": {
                "base_pcb": str(base_pcb),
                "preloaded_pcb": str(preloaded_pcb),
                "dsn": str(dsn_path),
                "ses": str(ses_path) if ses_path.exists() else "",
                "routed_pcb": str(routed_pcb) if routed_pcb.exists() else "",
                "preloaded_png": str(preloaded_png) if preloaded_png.exists() else "",
                "routed_png": str(routed_png) if routed_png.exists() else "",
            },
            "track_counts": {
                "preloaded": preloaded_counts,
                "final": final_counts,
            },
            "freerouting": freerouting_stats,
        }
        _write_demo_metadata(metadata_path, metadata)

    except Exception as exc:
        print(f"error: demo generation failed: {exc}", file=sys.stderr)
        return 1

    print("=== Hierarchical FreeRouting Demo ===")
    print(f"parent                 : {parent_definition.id.sheet_name}")
    print(f"parent_instance_path   : {parent_definition.id.instance_path}")
    print(f"artifact_count         : {len(loaded_artifacts)}")
    print(f"preloaded_pcb          : {preloaded_pcb}")
    print(f"dsn                    : {dsn_path}")
    if ses_path.exists():
        print(f"ses                    : {ses_path}")
    if routed_pcb.exists():
        print(f"routed_pcb             : {routed_pcb}")
    print(f"metadata_json          : {metadata_path}")
    print()
    print("preloaded board counts:")
    print(f"  traces               : {preloaded_counts.get('traces', 0)}")
    print(f"  vias                 : {preloaded_counts.get('vias', 0)}")
    print()
    print("composition routing:")
    print(
        f"  interconnect_nets    : {len(composition.hierarchy_state.interconnect_nets)}"
    )
    print(f"  routed_interconnects : {len(composition.routed_interconnect_nets)}")
    print(f"  failed_interconnects : {len(composition.failed_interconnect_nets)}")
    print()

    if routed_pcb.exists():
        print("final board counts:")
        print(f"  traces               : {final_counts.get('traces', 0)}")
        print(f"  vias                 : {final_counts.get('vias', 0)}")
        print()

    if args.render_png:
        if preloaded_png.exists():
            print(f"preloaded_png          : {preloaded_png}")
        if routed_png.exists():
            print(f"routed_png             : {routed_png}")
        print()

    if args.skip_freerouting:
        print("FreeRouting step skipped.")
    else:
        print(
            "FreeRouting session completed."
            if routed_pcb.exists()
            else "FreeRouting session did not produce a routed board."
        )

    if args.open:
        try:
            if preloaded_png.exists():
                _open_path(preloaded_png)
            else:
                _open_path(preloaded_pcb)

            if routed_png.exists():
                _open_path(routed_png)
            elif routed_pcb.exists():
                _open_path(routed_pcb)
        except Exception as exc:
            print(f"warning: failed to open output files: {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
