"""FreeRouting integration — DSN export → FreeRouting CLI → SES import.

Replaces the custom A*/RRR router with the FreeRouting autorouter
via the Specctra DSN/SES file exchange format.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile

def _make_settings(max_passes: int) -> dict:
    """Build FreeRouting settings — GUI disabled, blocking dialogs suppressed."""
    return {
        "gui": {"enabled": False},
        "dialog_confirmation_timeout": 0,
        "router": {
            "max_passes": max_passes,
            "max_threads": 1,
            "optimizer": {
                "max_passes": max_passes,
                "max_threads": 1,
            },
        },
        "usage_and_diagnostic_data": {"disable_analytics": True},
        "feature_flags": {
            "logging": True,
            "file_load_dialog_at_startup": False,
            "select_mode": False,
            "macros": False,
        },
    }


def _run_pcbnew_script(script: str) -> None:
    """Run a pcbnew script in a fresh subprocess to avoid SwigPyObject bugs."""
    result = subprocess.run(
        ["python3", "-c", script],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"pcbnew subprocess failed (rc={result.returncode}):\n"
            f"{result.stderr}"
        )


def clear_traces(kicad_pcb_path: str) -> None:
    """Remove all traces and non-thermal vias from the board."""
    _run_pcbnew_script(
        "import pcbnew\n"
        f"board = pcbnew.LoadBoard({kicad_pcb_path!r})\n"
        "for t in list(board.GetTracks()): board.Remove(t)\n"
        f"board.Save({kicad_pcb_path!r})\n"
    )


def export_dsn(kicad_pcb_path: str, dsn_path: str) -> None:
    """Export Specctra DSN from a KiCad PCB file using pcbnew API."""
    _run_pcbnew_script(
        "import pcbnew\n"
        f"board = pcbnew.LoadBoard({kicad_pcb_path!r})\n"
        f"pcbnew.ExportSpecctraDSN(board, {dsn_path!r})\n"
    )


def parse_freerouting_output(stdout: str, stderr: str,
                             returncode: int) -> dict:
    """Parse FreeRouting stdout/stderr for routing statistics."""
    stats = {
        "returncode": returncode,
        "passes": 0,
        "unrouted": -1,
        "violations": -1,
        "score": 0.0,
        "routing_seconds": 0.0,
        "optimization_seconds": 0.0,
    }

    combined = stdout + "\n" + stderr

    # Parse final routing result:
    # "Auto-routing was completed in X.XX seconds with the score of X (N unrouted and M violations)."
    m = re.search(
        r'Auto-routing was completed in ([\d.]+) seconds.*?'
        r'score of ([\d.]+).*?(\d+) unrouted.*?(\d+) violations',
        combined,
    )
    if m:
        stats["routing_seconds"] = float(m.group(1))
        stats["score"] = float(m.group(2))
        stats["unrouted"] = int(m.group(3))
        stats["violations"] = int(m.group(4))

    # Count successful passes
    pass_matches = re.findall(r'Auto-router pass #(\d+)', combined)
    if pass_matches:
        stats["passes"] = int(pass_matches[-1])

    # Parse optimization time
    m_opt = re.search(
        r'Optimization was completed in ([\d.]+) seconds',
        combined,
    )
    if m_opt:
        stats["optimization_seconds"] = float(m_opt.group(1))

    return stats


def run_freerouting(dsn_path: str, ses_path: str,
                    jar_path: str, timeout_s: int = 120,
                    max_passes: int = 40,
                    work_dir: str | None = None) -> dict:
    """Run FreeRouting CLI headless and return result metadata."""
    cmd = [
        "java",
        "-jar", jar_path,
        "--gui.enabled=false",
        "-de", dsn_path,
        "-do", ses_path,
        "-mp", str(max_passes),
        "-mt", "1",  # single-threaded optimization (multi is buggy)
        "-dct", "0",  # auto-dismiss dialogs immediately
    ]

    # Write a freerouting.json with GUI disabled into the working directory
    # so FreeRouting picks it up and doesn't pop dialog boxes.
    # Also set max_passes here since the JSON config overrides the CLI flag.
    cwd = work_dir or os.path.dirname(dsn_path)
    settings_path = os.path.join(cwd, "freerouting.json")
    with open(settings_path, "w") as f:
        json.dump(_make_settings(max_passes), f)

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout_s, cwd=cwd,
    )

    return parse_freerouting_output(
        result.stdout, result.stderr, result.returncode,
    )


def import_ses(kicad_pcb_path: str, ses_path: str,
               output_path: str) -> None:
    """Import Specctra SES session file into KiCad PCB."""
    _run_pcbnew_script(
        "import pcbnew\n"
        f"board = pcbnew.LoadBoard({kicad_pcb_path!r})\n"
        f"pcbnew.ImportSpecctraSES(board, {ses_path!r})\n"
        f"board.Save({output_path!r})\n"
    )


def route_with_freerouting(kicad_pcb_path: str, output_path: str,
                           jar_path: str, config: dict) -> dict:
    """Full DSN → FreeRouting → SES pipeline. Returns routing stats."""
    # Clear existing traces so FreeRouting starts fresh
    clear_traces(kicad_pcb_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        dsn_path = os.path.join(tmpdir, "board.dsn")
        ses_path = os.path.join(tmpdir, "board.ses")

        export_dsn(kicad_pcb_path, dsn_path)

        stats = run_freerouting(
            dsn_path, ses_path, jar_path,
            timeout_s=config.get("freerouting_timeout_s", 120),
            max_passes=config.get("freerouting_max_passes", 40),
        )

        # Only import SES if routing produced output
        if os.path.exists(ses_path):
            import_ses(kicad_pcb_path, ses_path, output_path)
        else:
            # Copy original if routing failed to produce output
            import shutil
            shutil.copy2(kicad_pcb_path, output_path)

    return stats
