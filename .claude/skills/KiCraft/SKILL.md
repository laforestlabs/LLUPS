---
name: KiCraft
description: Use when the user asks to "check trace widths", "audit my layout", "list footprints", "rearrange footprints", "arrange LEDs in a grid", "move component", "run DRC", "check clearances", "align components", or discusses KiCad PCB layout automation. Provides Python scripts using the KiCad 9 pcbnew API to parse and modify .kicad_pcb files.
---

# KiCad PCB Helper

Automate KiCad 9 PCB tasks using the `KiCraft` Python package (installed
as a git submodule at `KiCraft/`).

## Installation

The package is installed as an editable pip package from the submodule:

```bash
pip install -e KiCraft/
```

## CLI Commands

All commands are available as installed entry points after `pip install -e KiCraft/`.
Run them directly from the command line.

### Inspection

| Command | Usage | Description |
|---------|-------|-------------|
| `list-footprints` | `list-footprints <pcb>` | List all footprints with reference, value, position, layer |
| `check-trace-widths` | `check-trace-widths <pcb> [--min-mm 0.2]` | Find traces narrower than a minimum width |
| `run-drc` | `run-drc <pcb>` | Run Design Rule Check and report violations |
| `net-report` | `net-report <pcb>` | List all nets with pad counts and connectivity |
| `inspect-subcircuits` | `inspect-subcircuits <sch>` | Inspect subcircuit hierarchy from schematic |
| `inspect-solved-subcircuits` | `inspect-solved-subcircuits --project .` | Inspect solved subcircuit artifacts |

### Modification

| Command | Usage | Description |
|---------|-------|-------------|
| `move-component` | `move-component <pcb> <ref> <x_mm> <y_mm> [--rotate-deg N]` | Move a footprint to absolute position |
| `arrange-grid` | `arrange-grid <pcb> <ref_prefix> --cols N --spacing-mm S` | Arrange matching footprints in a grid |
| `align-components` | `align-components <pcb> <refs...> --axis x\|y` | Align footprints along an axis |
| `add-group-labels` | `add-group-labels <pcb> --config <config.json>` | Add/update silkscreen group labels |
| `split-schematic` | `split-schematic <sch> --config <config.json>` | Split flat schematic into hierarchical sheets |
| `add-gnd-zone` | `add-gnd-zone <pcb> [--in-place]` | Add GND copper zone on B.Cu |
| `cleanup-routing` | `cleanup-routing <pcb> [--remove-dangling] [--in-place]` | Clean up routing artifacts |

### Core Pipeline

| Command | Usage | Description |
|---------|-------|-------------|
| `solve-subcircuits` | `solve-subcircuits <sch> --pcb <pcb> --rounds N --route` | Hierarchical subcircuit placement and routing |
| `compose-subcircuits` | `compose-subcircuits --project .` | Assemble solved subcircuits into parent boards |
| `solve-hierarchy` | `solve-hierarchy <sch> --pcb <pcb>` | Full hierarchical solve (leaves → parents) |
| `export-subcircuit-artifacts` | `export-subcircuit-artifacts <sch> --pcb <pcb>` | Export subcircuit placement artifacts |
| `run-hierarchical-pipeline` | `run-hierarchical-pipeline --project . --schematic <sch> --pcb <pcb>` | Full hierarchical pipeline run |

### Experiment Management

| Command | Usage | Description |
|---------|-------|-------------|
| `autoexperiment` | `autoexperiment <pcb> <sch> --rounds N --workers W` | Automated experiment loop with parameter search |
| `clean-experiments` | `clean-experiments --before-run\|--after-run\|--nuke` | Clean experiment artifacts |
| `watch-status` | `watch-status [--file run_status.json]` | Live terminal monitor for running experiments |

### Scoring & Visual Analysis

| Command | Usage | Description |
|---------|-------|-------------|
| `score-layout` | `score-layout <pcb> [--compare prev.json]` | Score layout quality |
| `render-pcb` | `render-pcb <pcb> [--views front_all back_copper]` | Render PCB layers to PNG |
| `render-drc-overlay` | `render-drc-overlay <pcb> <round.json>` | DRC violation overlay on PCB render |
| `render-failure-heatmap` | `render-failure-heatmap <experiments_dir> <pcb>` | Routing failure heatmap |

### Analysis & Reporting

| Command | Usage | Description |
|---------|-------|-------------|
| `diff-rounds` | `diff-rounds <experiments_dir> <A> <B>` | Compare two experiment rounds |
| `generate-report` | `generate-report <experiments_dir>` | Interactive HTML report |
| `plot-experiments` | `plot-experiments [experiments.jsonl]` | Static matplotlib dashboard |
| `plot-scores` | `plot-scores [results_dir]` | Score results dashboard |
| `dashboard-app` | `dashboard-app [--port 5000]` | Live Flask dashboard |
| `layout-session` | `layout-session summary` | Track layout session progress |

### GUI

```bash
python -m kicraft.gui
```

## Package Structure

```
KiCraft/                    # Git submodule
├── pyproject.toml               # Package config with CLI entry points
├── kicraft/
│   ├── autoplacer/              # Placement and routing engine
│   │   ├── config.py            # DEFAULT_CONFIG + project config loader
│   │   ├── freerouting_runner.py
│   │   ├── brain/               # Pure algorithms (no pcbnew)
│   │   │   ├── placement.py     # Core placement solver
│   │   │   ├── types.py         # Data types and scoring weights
│   │   │   ├── hierarchy_parser.py
│   │   │   └── subcircuit_*.py  # Subcircuit pipeline modules
│   │   └── hardware/
│   │       └── adapter.py       # KiCad pcbnew API interface
│   ├── scoring/                 # Layout quality scoring checks
│   ├── gui/                     # NiceGUI experiment manager
│   └── cli/                     # CLI entry-point scripts
├── tests/
└── examples/
    └── llups_autoplacer.json
```

## Important Rules

1. **Always back up before modifying**: Scripts that modify the PCB save to `<filename>_modified.kicad_pcb` by default. Pass `--in-place` to overwrite.
2. **Units**: The pcbnew API uses nanometers internally. CLI commands accept millimeters.
3. **After modification**: Tell the user to reload the PCB in KiCad (`File > Revert`).
4. **Do NOT modify .kicad_pcb files with text editing** — always use the CLI commands or the pcbnew API.
5. **Project config**: LLUPS-specific settings are in `LLUPS_autoplacer.json` at the project root.
