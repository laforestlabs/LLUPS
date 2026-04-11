# LLUPS — Lithium Li-ion Universal Power Supply

> **Status: Draft / Untested** — Schematic and layout are procedurally generated and have not been fabricated or validated on hardware. Review all design choices and run DRC before ordering boards.

A compact PCB module providing regulated 5V and 3.3V power from two 18650 Li-ion cells (1S2P), charged via USB-C with passthrough capability.

## Specs

| Parameter | Value |
|---|---|
| Cells | 2x 18650 in parallel (1S2P), 3.7V nominal |
| Input | USB-C 5V (default power, no PD) |
| Outputs | 5V @ 1A (boost), 3.3V @ 500mA (LDO), raw VBAT |
| Charger | BQ24072, 1-2A CC/CV with power path |
| Protection | HY2113 (2.8V hard cutoff) + LN61C supervisor (3.3V operating cutoff) |
| Boost | MT3608, 5V from 3.3-4.2V input |
| LDO | AP2112K-3.3, 600mA |
| Board | 90x58mm, 2-layer, 1oz Cu |

## Core Files

```text
LLUPS.kicad_pro          # KiCad 9 project
LLUPS.kicad_sch          # Schematic
LLUPS.kicad_pcb          # PCB layout
generate_project.py      # Regenerates project artifacts
spec.md                  # Design specification
BOM.csv / BOM.xlsx       # Bill of materials
```

## Regenerating

```bash
python3 generate_project.py
```

Requires KiCad 9 CLI tools (`kicad-cli`) for netlist export.

## Running the Optimizer

```bash
python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb --rounds 100
```

The optimizer iterates placement and routing, keeping candidates that improve the overall score and discarding the rest. The best layout is saved to `LLUPS_best.kicad_pcb`.

## Monitoring Your Run

> All monitoring is read-only — it reads output files and never interferes with the experiment. Zero performance impact.

**During a run** — pick any of these (in a second terminal):

```bash
# Live web dashboard (recommended)
python3 .claude/skills/kicad-helper/scripts/dashboard_app.py --port 5000
# then open http://localhost:5000

# Or: one-line terminal status
watch -n2 cat .experiments/run_status.txt

# Or: leave the HTML report open; it rebuilds after each round and refreshes itself
xdg-open report.html
```

**After a run:**

```bash
# Animated layout evolution
xdg-open .experiments/progress.gif

# Score dashboard (PNG)
xdg-open .experiments/experiments_dashboard.png

# Interactive HTML report (richest view; rebuilt live during the run and finalized at the end)
python3 .claude/skills/kicad-helper/scripts/generate_report.py .experiments/ -o report.html
xdg-open report.html
```

Full details on every artifact, the web dashboard, the HTML report sections, DRC overlays, failure heatmaps, dependencies, and troubleshooting: [`docs/monitoring-guide.md`](docs/monitoring-guide.md)

![Experiment Results](.experiments/experiments_dashboard.png)
![Layout Progress GIF](.experiments/progress.gif)

## Architecture & Scoring

- [`docs/architecture.md`](docs/architecture.md) — system diagrams and layer responsibilities
- [`docs/footprint-layout.md`](docs/footprint-layout.md) — placement engine details
- [`docs/auto-trace.md`](docs/auto-trace.md) — routing engine details
- [`docs/scoring.md`](docs/scoring.md) — scoring formulas and weight breakdowns
- [`docs/monitoring-guide.md`](docs/monitoring-guide.md) — reports, dashboard, and monitoring

Static QA score (independent of the optimizer):

```bash
python3 .claude/skills/kicad-helper/scripts/score_layout.py LLUPS.kicad_pcb
```

## KiCad Helper Scripts

Automation scripts using the KiCad 9 `pcbnew` Python API:

| Script | Purpose |
|---|---|
| `list_footprints.py` | List components with positions |
| `check_trace_widths.py` | Find traces below minimum width |
| `run_drc.py` | Report DRC markers |
| `net_report.py` | List nets and pad counts |
| `move_component.py` | Move a footprint to X,Y |
| `arrange_grid.py` | Arrange components in a grid |
| `align_components.py` | Align components along an axis |

All in `.claude/skills/kicad-helper/scripts/`.

## License

GPLv3 — see [LICENSE](LICENSE).
