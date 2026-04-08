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

## Files

```
LLUPS.kicad_pro          # KiCad 9 project
LLUPS.kicad_sch          # Schematic
LLUPS.kicad_pcb          # PCB layout with routed traces
generate_project.py      # Generates all KiCad files from spec
spec.md                  # Full design specification
BOM.csv / BOM.xlsx       # Bill of materials
```

## Regenerating

The entire project (schematic, PCB, traces) is procedurally generated:

```bash
python3 generate_project.py
```

Requires KiCad 9 CLI tools (`kicad-cli`) for netlist export.

## Scoring Framework

A test suite scores PCB layout quality across 8 categories:

```bash
python3 .claude/skills/kicad-helper/scripts/score_layout.py LLUPS.kicad_pcb
```

Results are saved as timestamped JSON in `scripts/results/` for regression tracking.

Compare runs:

```bash
python3 .claude/skills/kicad-helper/scripts/score_layout.py LLUPS.kicad_pcb \
  --compare .claude/skills/kicad-helper/scripts/results/score_PREV.json
```

### Scoring Math

#### Static scorer (`score_layout.py`) — 0–100 scale

The **overall score** is a weighted average of 6 scored checks (2 are advisory, weight=0):

```
overall = Σ(score_i × weight_i) / Σ(weight_i)
```

| Check | Weight | Formula |
|---|---|---|
| **Trace Width Compliance** | 0.10 | `100 - 15×power_violations - 5×signal_violations` |
| **DRC Violations** | 0.35 | Logarithmic per-category (see below) |
| **Net Connectivity** | 0.15 | `100 - 10×single_pad_nets - 5×unassigned_pads` |
| **Component Placement** | 0.20 | `overlap(40) + bounds(20) + utilization(40)` |
| **Via Analysis** | 0.10 | `thermal(40) + density(30) + presence(30)` |
| **Routing Efficiency** | 0.10 | `efficiency(40) + orphan(30) + segments(30)` |
| Board Compactness | 0 (advisory) | `bbox_score(50) + grid_score(50)` |
| Footprint Orientation | 0 (advisory) | `100 × passed / checked` |

**DRC scoring** (35% of total) uses logarithmic decay so any improvement always registers:

```
issue_score(count, weight) = weight × (1 - log10(1+count) / log10(100))
```

Applied as: shorts→40pts, unconnected→30pts, crossings→15pts, clearance→10pts, cosmetic→5pts.
At 1 short: shorts contribution = 40×(1−0/2) = 40×0.5 = 20. At 10 shorts: ≈40×0.25 = 10.

**Placement scoring** (20%):
- Overlaps: 40pts (binary — any overlap = 0)
- Out-of-bounds centers: 20pts (binary)
- Utilization: 40pts, peaks at 30–70% footprint area / board area

**Via scoring** (10%):
- Thermal vias near U2/U4 within 3mm: 40pts (linear to min_thermal=4)
- Via density 2–20 /cm²: 30pts (linear outside range)
- Any vias present: 30pts (binary)

**Routing efficiency** (10%):
- Avg actual/MST ratio ≤1.5: 40pts; ≤3.0: linear; >3.0: 0pts
- Orphaned trace segments: 30 - 10×orphaned
- Has traces at all: 30pts

#### Experiment optimizer (`autoexperiment.py`) — single objective

The optimizer uses `ExperimentScore.compute()` which combines placement + routing into one scalar:

```
raw = 0.20×placement + 0.50×route_completion + 0.20×trace_efficiency + 0.10×via_score
final = raw × (board_containment / 100)          # hard penalty for out-of-board pads
```

Where:
- `placement` = `PlacementScore.total` (weighted sum of sub-scores, 0–100)
- `route_completion` = `(total_nets - failed_nets) / total_nets × 100`
- `trace_efficiency` = `max(0, min(100, 100 - avg_mm_per_routed_net))`
- `via_score` = `max(0, min(100, 100 - vias_per_routed_net × 20))`

If **shorts > 0**, an additional log-scale penalty is applied after DRC:

```
penalty = 0.10 / (1 + log10(1 + shorts))
final = final × penalty
```

1 short → ×0.05, 10 shorts → ×0.033, 100 shorts → ×0.025. Scores stay positive so the optimizer can still distinguish "fewer shorts is better" even when all candidates are failing.

**PlacementScore sub-weights** (applied inside `compute_total()`):

| Sub-score | Weight | Meaning |
|---|---|---|
| net_distance | 0.20 | connected components are close |
| crossover_score | 0.20 | fewer ratsnest crossings |
| compactness | 0.02 | board area utilization |
| edge_compliance | 0.08 | connectors/holes near edges |
| rotation_score | 0.05 | pad alignment quality |
| board_containment | 0.25 | fraction of pads inside outline |
| courtyard_overlap | 0.20 | no courtyard collisions |

## Autonomous Experiment Loop

Run layout optimization offline — no AI tokens, just CPU time:

```bash
cd .claude/skills/kicad-helper/scripts

# Run 50 rounds of placement+routing experiments
python3 autoexperiment.py ../../../../LLUPS.kicad_pcb --rounds 50

# Run overnight with longer plateau tolerance
python3 autoexperiment.py ../../../../LLUPS.kicad_pcb --rounds 500 --plateau 8

# Custom output and verbose logging
python3 autoexperiment.py ../../../../LLUPS.kicad_pcb -n 100 -o best.kicad_pcb -v
```

Edit `program.md` to steer the search space (parameter ranges, scoring weights).
Results log to `.experiments/experiments.jsonl`. Plot results:

```bash
python3 plot_experiments.py ../../../../.experiments/experiments.jsonl
```

![Experiment Results](.experiments/experiments_dashboard.png)

### Layout Progress

![Layout Progress GIF](.experiments/progress.gif)

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          CLI Entry Points                              │
│  autoplace.py    autoroute.py    autopipeline.py    autoexperiment.py  │
│  score_layout.py                 cleanup_routing.py                    │
└────────┬──────────────┬─────────────────┬──────────────────┬───────────┘
         │              │                 │                  │
         ▼              ▼                 ▼                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     autoplacer/pipeline.py                             │
│                                                                        │
│  PlacementEngine ──▶ RoutingEngine ──▶ FullPipeline                   │
│  .run()              .run()            .run() (chains both)            │
└────────┬──────────────┬────────────────────────────────────────────────┘
         │              │
         ▼              ▼
┌─────────────────────────────────────────────────────┐  ┌──────────────┐
│              autoplacer/brain/  (pure Python)        │  │   scoring/   │
│                                                      │  │              │
│  ┌─────────────────────────────────────────────┐     │  │  base.py     │
│  │           PLACEMENT                          │     │  │  LayoutCheck │
│  │                                              │     │  │      ▲       │
│  │  placement.py                                │     │  │      │       │
│  │  ├── PlacementSolver                         │     │  │  ┌───┴────┐  │
│  │  │   ├── solve()          main loop          │     │  │  │ Checks │  │
│  │  │   ├── _pin_edge_components()              │     │  │  ├────────┤  │
│  │  │   ├── _place_clusters()                   │     │  │  │trace   │  │
│  │  │   ├── _force_step()    force-directed     │     │  │  │drc     │  │
│  │  │   ├── _optimize_rotations()               │     │  │  │connect.│  │
│  │  │   ├── _resolve_overlaps()                 │     │  │  │place.  │  │
│  │  │   └── _clamp_to_board()                   │     │  │  │via     │  │
│  │  └── PlacementScorer                         │     │  │  │routing │  │
│  │      ├── score() ──▶ PlacementScore          │     │  │  │compact.│  │
│  │      ├── _score_net_distance()               │     │  │  │orient. │  │
│  │      ├── _score_courtyard_overlap()          │     │  │  │visual  │  │
│  │      └── _score_board_containment()          │     │  │  └────────┘  │
│  └──────────────────────────────────────────────┘     │  │              │
│                                                       │  │  __init__.py │
│  ┌──────────────────────────────────────────────┐     │  │  ALL_CHECKS  │
│  │           ROUTING                             │     │  └──────────────┘
│  │                                               │     │
│  │  router.py                                    │     │
│  │  ├── AStarRouter                              │     │
│  │  │   └── find_path()      A* + octile heur.  │     │
│  │  └── RoutingSolver                            │     │
│  │      ├── solve()           route all nets     │     │
│  │      ├── _prioritize_nets() power→signal      │     │
│  │      └── _route_net()      MST per net        │     │
│  │                                               │     │
│  │  grid_builder.py                              │     │
│  │  ├── RoutingGrid           2-layer cost grid  │     │
│  │  │   ├── mark_segment()   point-to-seg dist   │     │
│  │  │   ├── mark_rect()                          │     │
│  │  │   └── to_cell() / to_point()               │     │
│  │  ├── build_grid()         obstacles + pads    │     │
│  │  └── path_to_traces()     grid→TraceSegments  │     │
│  │                                               │     │
│  │  conflict.py                                  │     │
│  │  └── RipUpRerouter                            │     │
│  │      ├── solve()          iterative RRR       │     │
│  │      ├── _try_route()     re-route one net    │     │
│  │      └── _find_victims()  pick nets to rip    │     │
│  │                                               │     │
│  │  drc_sweep.py             post-route cleanup  │     │
│  │  ├── find_clearance_violations()              │     │
│  │  └── nudge_traces_apart()                     │     │
│  └──────────────────────────────────────────────┘     │
│                                                       │
│  ┌──────────────────────────────────────────────┐     │
│  │           SHARED                              │     │
│  │                                               │     │
│  │  types.py         Point, Pad, Component, Net, │     │
│  │                   TraceSegment, Via, BoardState│     │
│  │                   GridCell, RoutingResult,     │     │
│  │                   PlacementScore, ExperimentSc.│     │
│  │                                               │     │
│  │  graph.py         AdjacencyGraph, MST,        │     │
│  │                   community detection,         │     │
│  │                   crossing count               │     │
│  └──────────────────────────────────────────────┘     │
└───────────────────────────┬───────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                  autoplacer/hardware/adapter.py                         │
│                                                                         │
│  KiCadAdapter  (sole pcbnew interface)                                  │
│  ├── load()              .kicad_pcb ──▶ BoardState                     │
│  ├── apply_placement()   BoardState ──▶ .kicad_pcb                     │
│  └── apply_routing()     traces/vias ──▶ .kicad_pcb                    │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
                          ┌───────────────┐
                          │ .kicad_pcb    │
                          │ (KiCad 9)     │
                          └───────────────┘
```

**Data flow:** CLI scripts call pipeline engines, which use `KiCadAdapter.load()` to read the PCB into a `BoardState`. Brain-layer algorithms (placement, routing) operate on pure Python dataclasses. Results are written back via `KiCadAdapter.apply_*()`. Scoring checks run independently against the PCB file via `kicad-cli`.

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
