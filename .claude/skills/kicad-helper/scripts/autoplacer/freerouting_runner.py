"""FreeRouting integration — DSN export → FreeRouting CLI → SES import.

Routing pipeline:
  clear_traces() → export_dsn() → run_freerouting() → import_ses()
  Then count_board_tracks() extracts real trace/via counts from the result.

Note: Uses FreeRouting v1.9.0.  v2.1.0 has a regression where max_passes
is ignored and routing runs indefinitely.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import tempfile


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


def clear_traces(kicad_pcb_path: str,
                 preserve_thermal_vias: bool = True,
                 thermal_refs: list[str] | None = None,
                 thermal_radius_mm: float = 3.0) -> None:
    """Remove all traces/vias from the board, optionally preserving thermal vias."""
    thermal_refs = thermal_refs or []
    _run_pcbnew_script(
        "import math, pcbnew\n"
        f"board = pcbnew.LoadBoard({kicad_pcb_path!r})\n"
        f"thermal_refs = {thermal_refs!r}\n"
        f"thermal_radius_mm = {thermal_radius_mm!r}\n"
        f"preserve = {preserve_thermal_vias!r}\n"
        "thermal_centers = []\n"
        "if preserve:\n"
        "    for ref in thermal_refs:\n"
        "        fp = board.FindFootprintByReference(ref)\n"
        "        if fp:\n"
        "            pos = fp.GetPosition()\n"
        "            thermal_centers.append((pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)))\n"
        "to_remove = []\n"
        "for t in board.GetTracks():\n"
        "    if preserve and isinstance(t, pcbnew.PCB_VIA):\n"
        "        vpos = t.GetPosition()\n"
        "        vx, vy = pcbnew.ToMM(vpos.x), pcbnew.ToMM(vpos.y)\n"
        "        if any(math.hypot(vx-cx, vy-cy) <= thermal_radius_mm for cx,cy in thermal_centers):\n"
        "            continue\n"
        "    to_remove.append(t)\n"
        "for t in to_remove: board.Remove(t)\n"
        f"board.Save({kicad_pcb_path!r})\n"
    )


def count_board_tracks(kicad_pcb_path: str) -> dict:
    """Count traces, vias, and total trace length from a routed board.

    Runs in subprocess to avoid pcbnew SWIG issues.
    Returns {traces: int, vias: int, total_length_mm: float}.
    """
    result = subprocess.run(
        ["python3", "-c",
         "import json, pcbnew\n"
         f"board = pcbnew.LoadBoard({kicad_pcb_path!r})\n"
         "traces = vias = 0\n"
         "length_nm = 0\n"
         "for t in board.GetTracks():\n"
         "    if isinstance(t, pcbnew.PCB_VIA):\n"
         "        vias += 1\n"
         "    else:\n"
         "        traces += 1\n"
         "        length_nm += t.GetLength()\n"
         "print(json.dumps({'traces': traces, 'vias': vias,"
         "  'total_length_mm': round(pcbnew.ToMM(length_nm), 2)}))\n"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return {"traces": 0, "vias": 0, "total_length_mm": 0.0}
    return json.loads(result.stdout.strip())


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

    # v2.x format: "Auto-routing was completed in X.XX seconds with the score of X (N unrouted and M violations)."
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
    else:
        # v1.9.x format: "Auto-routing was completed in X.XX seconds."
        m19 = re.search(
            r'Auto-routing was completed in ([\d.]+) seconds',
            combined,
        )
        if m19:
            stats["routing_seconds"] = float(m19.group(1))

    # Count successful passes (v2.x logs per-pass)
    pass_matches = re.findall(r'Auto-router pass #(\d+)', combined)
    if pass_matches:
        stats["passes"] = int(pass_matches[-1])

    # Parse optimization time (both versions)
    m_opt = re.search(
        r'[Oo]ptimization was completed in ([\d.]+) seconds',
        combined,
    )
    if m_opt:
        stats["optimization_seconds"] = float(m_opt.group(1))

    return stats


def run_freerouting(dsn_path: str, ses_path: str,
                    jar_path: str, timeout_s: int = 120,
                    max_passes: int = 40,
                    work_dir: str | None = None) -> dict:
    """Run FreeRouting CLI and return result metadata.

    Uses start_new_session so the Java process gets its own process group,
    allowing clean kill via os.killpg() on timeout or stop request.
    """
    cmd = [
        "java",
        "-jar", jar_path,
        "-de", dsn_path,
        "-do", ses_path,
        "-mp", str(max_passes),
        "-mt", "1",  # single-threaded optimization (multi is buggy)
        "-dct", "0",  # auto-dismiss dialogs immediately
    ]

    cwd = work_dir or os.path.dirname(dsn_path)

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=cwd, start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        # Kill entire process group (Java + any children)
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except OSError:
            pass
        stdout, stderr = proc.communicate(timeout=5)
        return parse_freerouting_output(stdout, stderr, -1)

    return parse_freerouting_output(stdout, stderr, proc.returncode)


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
    # Clear existing traces so FreeRouting starts fresh (preserve thermal vias)
    clear_traces(
        kicad_pcb_path,
        preserve_thermal_vias=True,
        thermal_refs=config.get("thermal_refs", []),
        thermal_radius_mm=config.get("thermal_radius_mm", 3.0),
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        dsn_path = os.path.join(tmpdir, "board.dsn")
        ses_path = os.path.join(tmpdir, "board.ses")

        export_dsn(kicad_pcb_path, dsn_path)

        stats = run_freerouting(
            dsn_path, ses_path, jar_path,
            timeout_s=config.get("freerouting_timeout_s", 120),
            max_passes=config.get("freerouting_max_passes", 40),
        )

        # Import SES if routing produced output
        if os.path.exists(ses_path):
            import_ses(kicad_pcb_path, ses_path, output_path)
        else:
            raise RuntimeError(
                f"FreeRouting produced no SES output (rc={stats.get('returncode', '?')})"
            )

    return stats
