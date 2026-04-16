"""Leaf/subcircuit render diagnostics helpers.

This module builds a small, standardized visual diagnostic bundle for routed
leaf artifacts under a leaf artifact directory, typically:

    .experiments/subcircuits/<slug>/renders/

It is intentionally orchestration-focused and reuses the existing rendering
helpers in the scripts directory:

- `render_pcb.py` for board snapshots
- `render_drc_overlay.py` for DRC overlays

Primary outputs:
- pre-route / routed board snapshots
- pre-route / routed DRC JSON sidecars
- pre-route / routed DRC overlays
- a simple contact sheet comparing pre-route vs routed artifacts

The helpers are designed to degrade gracefully when optional external tools
(e.g. `kicad-cli`, ImageMagick) are unavailable.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

try:
    from render_drc_overlay import render_overlay
except Exception:  # pragma: no cover - best-effort import
    render_overlay = None

try:
    from render_pcb import render_all
except Exception:  # pragma: no cover - best-effort import
    render_all = None


DEFAULT_VIEWS = ("copper_both", "front_all")


def ensure_renders_dir(artifact_dir: str | Path) -> Path:
    """Create and return the standard renders directory for one leaf artifact."""
    renders_dir = Path(artifact_dir) / "renders"
    renders_dir.mkdir(parents=True, exist_ok=True)
    return renders_dir


def write_leaf_drc_json(drc_dict: dict[str, Any], output_path: str | Path) -> str:
    """Persist a DRC payload as pretty JSON."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(drc_dict, indent=2, sort_keys=True), encoding="utf-8")
    return str(out)


def render_leaf_board_views(
    pcb_path: str | Path,
    output_dir: str | Path,
    prefix: str,
    views: tuple[str, ...] = DEFAULT_VIEWS,
) -> dict[str, Any]:
    """Render a small set of board snapshots for one PCB.

    Returns a dict with:
    - `requested_views`
    - `rendered_views`
    - `paths`
    - `errors`
    """
    result: dict[str, Any] = {
        "pcb_path": str(pcb_path),
        "requested_views": list(views),
        "rendered_views": [],
        "paths": {},
        "errors": [],
    }

    if render_all is None:
        result["errors"].append("render_pcb_import_failed")
        return result

    pcb = Path(pcb_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not pcb.exists():
        result["errors"].append("pcb_missing")
        return result

    temp_dir = out_dir / f".tmp_{prefix}_views"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        rendered = render_all(str(pcb), str(temp_dir), list(views))
        for view_name, src_path in rendered.items():
            src = Path(src_path)
            if not src.exists():
                continue
            dest = out_dir / f"{prefix}_{view_name}.png"
            shutil.move(str(src), str(dest))
            result["rendered_views"].append(view_name)
            result["paths"][view_name] = str(dest)
    except Exception as exc:  # pragma: no cover - external tool path
        result["errors"].append(f"render_failed:{exc}")
    finally:
        try:
            shutil.rmtree(temp_dir)
        except OSError:
            pass

    return result


def render_leaf_drc_overlay(
    pcb_path: str | Path,
    drc_dict: dict[str, Any],
    output_png: str | Path,
) -> dict[str, Any]:
    """Render a DRC overlay image when coordinate-bearing violations exist."""
    result: dict[str, Any] = {
        "pcb_path": str(pcb_path),
        "output_png": str(output_png),
        "rendered": False,
        "violation_count": 0,
        "located_violation_count": 0,
        "errors": [],
    }

    if render_overlay is None:
        result["errors"].append("render_drc_overlay_import_failed")
        return result

    violations = list(drc_dict.get("violations", []) or [])
    result["violation_count"] = len(violations)
    located = [
        item
        for item in violations
        if isinstance(item, dict)
        and item.get("x_mm") is not None
        and item.get("y_mm") is not None
    ]
    result["located_violation_count"] = len(located)

    if not located:
        result["errors"].append("no_located_violations")
        return result

    try:
        ok = render_overlay(
            str(pcb_path),
            located,
            str(output_png),
        )
        result["rendered"] = bool(ok)
        if not ok:
            result["errors"].append("overlay_render_failed")
    except Exception as exc:  # pragma: no cover - external tool path
        result["errors"].append(f"overlay_exception:{exc}")

    return result


def build_leaf_contact_sheet(
    image_paths: list[str | Path],
    output_path: str | Path,
    *,
    tile: str = "2x2",
    background: str = "white",
) -> dict[str, Any]:
    """Build a simple contact sheet from existing PNGs using ImageMagick."""
    result: dict[str, Any] = {
        "output_path": str(output_path),
        "input_paths": [str(p) for p in image_paths],
        "created": False,
        "errors": [],
    }

    existing = [str(Path(p)) for p in image_paths if Path(p).exists()]
    if not existing:
        result["errors"].append("no_input_images")
        return result

    magick = shutil.which("magick")
    if magick is None:
        result["errors"].append("imagemagick_unavailable")
        return result

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        magick,
        "montage",
        *existing,
        "-background",
        background,
        "-tile",
        tile,
        "-geometry",
        "+8+8",
        str(out),
    ]

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            result["errors"].append(
                f"montage_failed:{stderr or f'rc={completed.returncode}'}"
            )
            return result
        result["created"] = out.exists()
        if not result["created"]:
            result["errors"].append("montage_missing_output")
    except Exception as exc:  # pragma: no cover - external tool path
        result["errors"].append(f"montage_exception:{exc}")

    return result


def _stage_prefix(stage: str) -> str:
    normalized = stage.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"pre", "pre_route", "pre_freerouting"}:
        return "pre_route"
    if normalized in {"routed", "post_route", "post"}:
        return "routed"
    return normalized or "stage"


def generate_stage_diagnostic_artifacts(
    *,
    pcb_path: str | Path,
    validation: dict[str, Any] | None,
    artifact_dir: str | Path,
    stage: str,
    views: tuple[str, ...] = DEFAULT_VIEWS,
) -> dict[str, Any]:
    """Generate render diagnostics for one board stage.

    Typical stages:
    - `pre_route`
    - `routed`
    """
    prefix = _stage_prefix(stage)
    renders_dir = ensure_renders_dir(artifact_dir)
    stage_result: dict[str, Any] = {
        "stage": prefix,
        "renders_dir": str(renders_dir),
        "pcb_path": str(pcb_path),
        "board_views": {},
        "drc_json_path": None,
        "drc_overlay": {},
        "errors": [],
    }

    pcb = Path(pcb_path)
    if not pcb.exists():
        stage_result["errors"].append("pcb_missing")
        return stage_result

    stage_result["board_views"] = render_leaf_board_views(
        pcb_path=pcb,
        output_dir=renders_dir,
        prefix=prefix,
        views=views,
    )

    drc = dict((validation or {}).get("drc", {}) or {})
    drc_json_path = renders_dir / f"{prefix}_drc.json"
    try:
        stage_result["drc_json_path"] = write_leaf_drc_json(drc, drc_json_path)
    except Exception as exc:
        stage_result["errors"].append(f"drc_json_write_failed:{exc}")

    report_text_path = renders_dir / f"{prefix}_drc_report.txt"
    try:
        report_text = str(drc.get("report_text", "") or "")
        report_text_path.write_text(report_text, encoding="utf-8")
        stage_result["drc_report_text_path"] = str(report_text_path)
    except Exception as exc:
        stage_result["drc_report_text_path"] = None
        stage_result["errors"].append(f"drc_report_write_failed:{exc}")

    overlay_path = renders_dir / f"{prefix}_drc_overlay.png"
    stage_result["drc_overlay"] = render_leaf_drc_overlay(
        pcb_path=pcb,
        drc_dict=drc,
        output_png=overlay_path,
    )

    return stage_result


def generate_leaf_diagnostic_artifacts(
    *,
    artifact_dir: str | Path,
    pre_route_board: str | Path | None = None,
    routed_board: str | Path | None = None,
    pre_route_validation: dict[str, Any] | None = None,
    routed_validation: dict[str, Any] | None = None,
    views: tuple[str, ...] = DEFAULT_VIEWS,
) -> dict[str, Any]:
    """Generate the full leaf diagnostic bundle.

    Returns a JSON-serializable dict describing all generated artifacts.
    """
    renders_dir = ensure_renders_dir(artifact_dir)
    result: dict[str, Any] = {
        "artifact_dir": str(Path(artifact_dir)),
        "renders_dir": str(renders_dir),
        "pre_route": None,
        "routed": None,
        "comparison": {
            "contact_sheet_path": None,
            "created": False,
            "errors": [],
        },
    }

    if pre_route_board:
        result["pre_route"] = generate_stage_diagnostic_artifacts(
            pcb_path=pre_route_board,
            validation=pre_route_validation,
            artifact_dir=artifact_dir,
            stage="pre_route",
            views=views,
        )

    if routed_board:
        result["routed"] = generate_stage_diagnostic_artifacts(
            pcb_path=routed_board,
            validation=routed_validation,
            artifact_dir=artifact_dir,
            stage="routed",
            views=views,
        )

    contact_inputs: list[str] = []
    for stage_key in ("pre_route", "routed"):
        stage_payload = result.get(stage_key) or {}
        board_views = stage_payload.get("board_views", {})
        paths = board_views.get("paths", {})
        overlay = stage_payload.get("drc_overlay", {})
        if paths.get("copper_both"):
            contact_inputs.append(paths["copper_both"])
        if overlay.get("rendered") and overlay.get("output_png"):
            contact_inputs.append(overlay["output_png"])

    contact_sheet_path = renders_dir / "pre_vs_routed_contact_sheet.png"
    comparison = build_leaf_contact_sheet(contact_inputs, contact_sheet_path)
    result["comparison"]["contact_sheet_path"] = str(contact_sheet_path)
    result["comparison"]["created"] = bool(comparison.get("created", False))
    result["comparison"]["errors"] = list(comparison.get("errors", []))

    summary_path = renders_dir / "diagnostics_summary.json"
    try:
        summary_path.write_text(
            json.dumps(result, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        result["summary_json_path"] = str(summary_path)
    except Exception as exc:
        result["summary_json_path"] = None
        result.setdefault("errors", []).append(f"summary_write_failed:{exc}")

    return result
