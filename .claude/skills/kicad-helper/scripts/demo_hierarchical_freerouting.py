#!/usr/bin/env python3
"""Obsolete script placeholder.

This repository now uses a single parent composition / stamping / routing path
implemented in `compose_subcircuits.py` and orchestrated by
`run_hierarchical_pipeline.py`.

This file is intentionally kept only as a hard failure shim so any lingering
calls fail loudly instead of silently using a stale alternate pipeline.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    _ = argv
    print(
        "error: `demo_hierarchical_freerouting.py` has been removed.\n"
        "The hierarchical parent pipeline now has a single supported path:\n"
        "  1. `compose_subcircuits.py` for parent composition/stamping/routing\n"
        "  2. `run_hierarchical_pipeline.py` as the user-facing orchestrator\n\n"
        "Update any callers to use one of:\n"
        "  python3 .claude/skills/kicad-helper/scripts/compose_subcircuits.py "
        "--project . --parent / --mode packed --spacing-mm 6 --pcb LLUPS.kicad_pcb --route\n"
        "or:\n"
        "  python3 .claude/skills/kicad-helper/scripts/run_hierarchical_pipeline.py "
        "--project . --schematic LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --parent /\n",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
