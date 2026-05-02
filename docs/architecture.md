# LLUPS Autoplacer Architecture

This document describes how the autoplacer stack operates.

## High-Level Pipeline

The autoexperiment runner is the user-facing entry point. Each round spawns
two subprocesses (leaf solver, parent composer), then scores the combined
result and decides whether to promote it to the running best.

```mermaid
flowchart TD
  user([user]) -->|autoexperiment LLUPS.kicad_pcb --rounds N| ax[autoexperiment.py<br/>outer loop]

  ax -->|subprocess per round| solve[solve_subcircuits.py<br/>leaf solver]
  ax -->|subprocess per round<br/>--stamp --route| compose[compose_subcircuits.py<br/>parent composer]
  ax --> score[_score_round<br/>3-tier]

  solve -->|writes per leaf| leafArt[(.experiments/subcircuits/&lt;leaf&gt;/<br/>solved_layout.json<br/>leaf_routed.kicad_pcb)]
  leafArt --> compose

  compose -->|writes| parentArt[(.experiments/subcircuits/__parent__/<br/>parent_routed.kicad_pcb<br/>composer report.json)]
  compose -->|auto-emit| inspector[(inspect/<br/>annotated_top.png<br/>stacking_heatmap.png<br/>summary.md)]
  parentArt --> score

  score --> accept{score improved by keep_threshold<br/>AND subprocesses succeeded?}
  accept -->|kept| best[(LLUPS_best.kicad_pcb)]
  accept -->|next round| ax

  ax -.atomic write.-> status[(.experiments/run_status.json)]
  status -.poll ~2s.-> gui[GUI monitor]
```

## Layer Responsibilities

CLI entry points (`kicraft/cli/`):
- `autoexperiment.py` -- outer loop: per-round subprocess fan-out, scoring, accept/reject, atomic status writes, run archive.
- `solve_subcircuits.py` -- leaf solver: per-leaf placement + FreeRouting + DRC + acceptance gate; writes `solved_layout.json` and `leaf_routed.kicad_pcb`.
- `compose_subcircuits.py` -- parent composer: discovers solved leaf artifacts, calls parent_adapter to bridge into `PlacementSolver`, stamps parent PCB, runs FreeRouting on parent, auto-emits the inspector bundle.
- `solve_hierarchy.py` -- standalone end-to-end orchestrator (not used inside the autoexperiment loop, but available for one-shot full-hierarchy runs).
- `inspect_parent.py` -- annotated PNGs, stacking heatmap, clustered DRC issue list, suggested next actions, optional baseline diff. Auto-runs after parent route.
- `score_layout.py` -- score a single PCB without re-running the pipeline.

Algorithmic core (`kicraft/autoplacer/brain/`):
- `placement_solver.py` -- unified `PlacementSolver` (cluster placement, force-directed iteration, simulated-annealing refinement). Used for both leaf and parent placement.
- `parent_adapter.py` -- bridges compose data to `PlacementSolver`: `artifact_to_component`, `attachment_constraints_to_zones`, `placements_from_solved_state`.
- `subcircuit_composer.py` -- constraint-aware outline derivation, child geometry transforms.
- `placement_scorer.py` -- inner placement-quality score, used by `PlacementSolver` during iteration.
- `types.py` -- shared dataclasses (`BoardState`, `Component`, `PlacementScore`, `DRCScore`).

I/O bridges:
- `autoplacer/freerouting_runner.py` -- DSN export, FreeRouting subprocess (xvfb-wrapped on FR 1.x, `--gui.enabled=false` on FR 2.x), SES import, retry-on-crash.
- `autoplacer/hardware/adapter.py` -- KiCad I/O via the `pcbnew` SWIG bindings.
- `scoring/` -- DRC, connectivity, geometry, placement-fit, trace-width checks.

GUI (`kicraft/gui/`):
- Polls `.experiments/run_status.json` every ~2 s. Anchors a local 1 s clock to the backend `elapsed_s` only when it advances; otherwise extrapolates locally, so long subprocess phases do not stall the displayed clock.

## Status JSON Flow

The runner writes `.experiments/run_status.json` and `.experiments/run_status.txt` at every stage transition. The GUI polls these files every ~2 s and renders timing, progress, the current node, and preview paths.

```mermaid
sequenceDiagram
  participant W as autoexperiment
  participant FS as run_status.json
  participant G as GUI monitor

  loop per stage transition
    W->>FS: write run_status.json.tmp
    W->>FS: os.replace(.tmp, .json) -- atomic
  end

  loop every ~2s
    G->>FS: read run_status.json
    alt backend_elapsed advanced
      G->>G: re-anchor local 1s ticker
    else stale (no advance)
      G->>G: keep extrapolating from last anchor
    end
  end
```

Two invariants keep the GUI clock smooth during long subprocess phases:

1. **Writer side**: `_write_json` writes to `<path>.tmp` then `os.replace()`. The rename is atomic on POSIX, so the GUI never reads a torn JSON.
2. **Reader side**: GUI extrapolates a local 1 s ticker from the last backend-anchored value. It only re-anchors when `backend_elapsed` actually advances. Stale reads do not snap the displayed clock backward.

If either invariant is violated, the user sees toggling or stuck counters (the diagnostic pattern documented in commit `105c8b6`).

## Data Model Path

```mermaid
flowchart LR
  kicadBoard[.kicad_pcb] --> adapterLoad[KiCadAdapter.load]
  adapterLoad --> boardState[BoardState dataclasses]
  boardState --> placementPhase[Placement phase]
  placementPhase --> placementMetrics[PlacementScore]
  boardState --> routingPhase[FreeRouting]
  routingPhase --> routingMetrics[traces, vias, length, unrouted]
  placementMetrics --> expScore[_score_round]
  routingMetrics --> expScore
  expScore --> bestDecision[Best candidate decision]
  bestDecision --> bestBoard[best.kicad_pcb]
```

## Configuration System

Configuration starts from `DEFAULT_CONFIG` in `autoplacer/config.py` and is layered with project-specific overrides at runtime:

- **`DEFAULT_CONFIG`**: Generic defaults for any PCB project. Placement algorithm parameters (clearance, grid, forces), routing settings (timeout, passes, ignore nets), and feature toggles (scatter_mode, reheat, courtyard padding). Project-specific fields like `ic_groups`, `component_zones`, and `signal_flow_order` default to empty.
- **Project overrides**: loaded from a project-local JSON (e.g. `LLUPS_autoplacer.json`) and merged on top: `{**DEFAULT_CONFIG, **project_overrides}`. The merge is performed in `solve_subcircuits.py` (line 315 area) for leaf solves and in `autoexperiment.py` (line 1885 area) for the experiment loop's initial config.
- **Per-round mutations**: the experiment loop further mutates the config each round (minor / major / explore modes; see Evolutionary Search Strategy below).

### Key Config Features

| Config Key | Purpose |
|-----------|---------|
| `component_zones` | Maps refs to placement zones (edge, corner, zone constraints) |
| `signal_flow_order` | List of refs biased left→right along X-axis |
| `scatter_mode` | `"cluster"` (default) or `"random"` (uniform scatter) |
| `reheat_strength` | Temperature reheat factor at 50% of force sim iterations |
| `randomize_group_layout` | Enables variable cluster radii (0.3-1.8× vs 0.8-1.2×) |
| `courtyard_padding_mm` | Extra padding added to courtyard overlap scoring |
| `min_placement_score` | Minimum placement score to proceed to routing |
| `connector_gap_mm` | Gap between same-edge connectors (default 2.0mm) |
| `connector_edge_inset_mm` | Distance from board edge to connector body (default 1.0mm) |
| `orderedness` | Passive alignment strength 0.0-1.0 (organic → grid) |
| `pad_inset_margin_mm` | Minimum pad-to-board-edge distance (default 0.3mm) |
| `max_placement_iterations` | Force sim iteration limit (default 300, searchable 100-500) |
| `placement_convergence_threshold` | Displacement threshold to declare convergence (default 0.5mm) |
| `tht_backside_min_area_mm2` | THT area threshold for back-layer assignment (default 50mm²) |
| `board_size_overhead_factor` | Min board area = component area × factor (default 2.5) |
| `enable_board_size_search` | Enable board dimension search in autoexperiment |
| `smt_opposite_tht` | Attract front-side SMT components toward back-side THT shadows (default True) |
| `align_large_pairs` | Force large similarly-sized component pairs side-by-side (default True) |
| `unlock_all_footprints` | Allow edge/corner-pinned components to move freely during force sim (default True) |
| `skip_gnd_routing` | Exclude GND net from FreeRouting, rely on copper zone pour (default True) |

## Rotation & Flip Conventions

KiCad uses a clockwise rotation convention for `SetOrientationDegrees()`:

```
x' = lx·cos(θ) + ly·sin(θ) + cx
y' = -lx·sin(θ) + ly·cos(θ) + cy
```

where `(lx, ly)` are local pad offsets and `(cx, cy)` is the component center. The model's `_update_pad_positions()` must use this formula (not the standard CCW math convention).

KiCad's `Flip()` negates pad X offsets relative to the component center. When `_assign_layers()` moves a component to B.Cu, it must mirror pad positions: `pad.x = 2·comp.x - pad.x`.

## Evolutionary Optimization

`autoexperiment.py` runs an evolutionary loop with three mutation modes:

- **MINOR**: Gaussian perturbation from best config, reuses best seed
- **MAJOR**: Uniform sampling (aggressive), new seed, optional scatter and group randomization
- **EXPLORE**: Random config + seed, forced scatter mode (33% of batch)

Cross-run learning via **elite archive**: top-5 configs saved to `elite_configs.json`, seeded into 30% of early batches in subsequent runs.

A **placement validation gate** skips routing when:
- Any pads are outside the board boundary (zero tolerance)
- Placement score falls below `min_placement_score`
- Board containment below `min_board_containment`
- Courtyard overlap score below `min_courtyard_overlap_score`


## Theory of Operation

> *Extracted from the autoplacer internal technical reference.*

### Placement Pipeline (14 Steps)

The `PlacementSolver.solve()` method runs the following pipeline in order:

| Step | Name | Description |
|------|------|-------------|
| 0.5 | **Assign layers** | Place large THT components on B.Cu, SMT on F.Cu. Uses `tht_backside_min_area_mm2` threshold. |
| 1 | **Pin edge components** | Snap connectors and mounting holes to their assigned board edges/corners. Applies `edge_jitter_mm` for diversity. |
| 1.3 | **Align large pairs** | Detect pairs of large, similar-sized components (e.g. BT1+BT2) and force side-by-side alignment on one axis. |
| 2 | **Cluster by connectivity** | Run community detection on the net connectivity graph to find natural component clusters. IC groups boost intra-group edge weights. |
| 3 | **Initial cluster placement** | Place cluster centroids on the board using signal flow order (left-to-right) with seeded jitter. Scatter mode controls initial distribution. |
| 4 | **Intra-cluster optimization** | Run a short force-directed simulation within each cluster to arrange members compactly. |
| 5 | **Rotation optimization** | Try 4 rotations (0°, 90°, 180°, 270°) for each IC/connector, keeping whichever minimizes net crossing estimates. |
| 6 | **Force-directed refinement** | Main iterative loop: attraction along nets, repulsion between overlapping bounding boxes, cooling schedule. Scores every N iterations and reverts to best on stagnation. Includes mid-run temperature reheat. |
| 7 | **Swap optimization** | Greedily swap positions of similarly-sized unlocked components to minimize ratsnest crossings. Up to 5 rounds. |
| 8 | **Grid snap** | Snap component positions to `placement_grid_mm` grid. |
| 8.5 | **Orderedness** | Blend passive positions toward neat row/column alignment. Strength controlled by `orderedness` parameter (0.0–1.0). |
| 9 | **Overlap resolution** | Exhaustive push-apart of any remaining courtyard overlaps. |
| 10–12 | **Clamp & validate** | Hard-clamp all components inside the board outline, then verify every electrical pad is within the boundary (up to 3 passes). |
| 13 | **Restore pinned positions** | Re-pin edge/corner components that may have drifted during overlap resolution. Re-resolve overlaps, then re-pin again. |

### Experiment Loop (per round)

Each autoexperiment round runs the leaf solver, then the parent composer,
then scores the combined result.

```mermaid
flowchart LR
  start([round N start]) --> leafSolve[solve_subcircuits.py<br/>per leaf: place + FreeRoute + DRC]
  leafSolve --> leafGate{all leaves accepted?}
  leafGate -->|no| partial[tier=partial_leaves]
  leafGate -->|yes| compose[compose_subcircuits.py<br/>--stamp --route]
  compose --> parentGate{parent routed?}
  parentGate -->|no| notRouted[tier=not_routed]
  parentGate -->|yes| functional[tier=functional]

  partial --> score
  notRouted --> score
  functional --> score{is_meaningful_improvement<br/>AND subprocesses_ok?}

  score -->|yes| keep[promote to best]
  score -->|no| discard[discard]
```

Per-leaf solve, inside `solve_subcircuits.py`:

```mermaid
flowchart LR
  leaf([leaf input]) --> extract[extract leaf board state<br/>from parent PCB]
  extract --> place[PlacementSolver:<br/>cluster + force-dir + SA refine]
  place --> stamp[stamp leaf PCB]
  stamp --> fr[FreeRouting]
  fr --> drc[quick_drc]
  drc --> gate{legality + DRC<br/>+ unrouted budget}
  gate -->|reject| nextRound[next round]
  gate -->|accept| persist[(solved_layout.json<br/>leaf_routed.kicad_pcb)]
```

Parent compose, inside `compose_subcircuits.py`:

```mermaid
flowchart LR
  start([routed leaf artifacts]) --> discover[_discover_artifact_dirs +<br/>filter by hierarchy parent]
  discover --> adapt[parent_adapter:<br/>artifact_to_component +<br/>attachment_constraints_to_zones]
  adapt --> solver[PlacementSolver.solve<br/>blocker-aware on synthetic blocks]
  solver --> placements[placements_from_solved_state]
  placements --> stampPcb[(parent_pre_freerouting.kicad_pcb)]
  stampPcb --> fr[FreeRouting<br/>preserves child copper]
  fr --> routedPcb[(parent_routed.kicad_pcb)]
  routedPcb --> inspector[inspect_parent auto-emit:<br/>annotated_top.png<br/>stacking_heatmap.png<br/>summary.md]
```

### Scoring

`_score_round()` produces a 3-tier score in roughly `[0, 90]`. The composer's
own quality score (anchor coverage, area utilization, child layout quality,
interconnect compactness, DRC penalty) is the source of truth for the
`functional` tier.

```mermaid
flowchart TD
  start([round result]) --> leaf{leaf_accepted /<br/>leaf_total}
  leaf -->|< 1.0| partial[tier=partial_leaves<br/>score = leaf_ratio * 15<br/>range 0-15]
  leaf -->|= 1.0| routed{parent_routed?}
  routed -->|no| notRouted[tier=not_routed<br/>score = 20]
  routed -->|yes| functional[tier=functional<br/>score = composer_score_total<br/>typical 50-90]
```

A round is promoted to "best" only when both gates pass:

1. `is_meaningful_improvement` -- score exceeds the prior best by `keep_threshold` (0.5), or this is the first round, AND
2. all subprocesses succeeded (`solve_rc == 0` if leaves run, `parent_route_rc == 0` if parent runs).

The subprocess gate prevents a failed first round from being promoted to
"best" (which would otherwise pollute every subsequent improvement
comparison). See `is_meaningful_improvement` in `autoexperiment.py`.

The inner `PlacementScore`, used inside `PlacementSolver.solve()` to drive
each iteration, has its own component weights, defined in
`autoplacer/brain/types.py`:

| Component | Weight | Description |
|-----------|--------|-------------|
| `net_distance` | 0.20 | Connected components close together |
| `crossover_score` | 0.17 | Fewer ratsnest crossings |
| `smt_opposite_tht` | 0.15 | SMT on opposite side of THT |
| `board_containment` | 0.12 | All pads/bodies inside board |
| `edge_compliance` | 0.10 | Connectors/holes on edges |
| `courtyard_overlap` | 0.10 | No overlapping courtyards |
| `group_coherence` | 0.08 | Functional groups stay compact |
| `topology_structure` | 0.05 | Topology-aware passive ordering |
| `aspect_ratio` | 0.02 | Penalize elongated boards |
| `compactness` | 0.01 | Tighter layouts |
| `block_opposite_side` | 0.0 | Parent-side opposite-side block stacking (plumbed but disabled by default; see `types.py` for rationale) |
| `rotation_score` | 0.0 | Pad alignment quality |

### Evolutionary Search Strategy

The experiment loop uses an evolutionary search with five mutation modes:

1. **Minor mutation** — Gaussian perturbation of 1–3 continuous parameters
   around the current best config. Uses the same seed as the best (exploit).
   Board dimensions have a 70% shrink bias.

2. **Major mutation** — Uniform resampling of parameters across full ranges,
   fresh seed, enables `randomize_group_layout` and `reheat_strength`.
   Triggered after `--plateau` consecutive minor rounds without improvement.

3. **Explore** — Fully random config from baseline (not from best).
   Always uses `scatter_mode: "random"` and `randomize_group_layout: True`.
   ~33% of each batch is reserved for exploration.

4. **Elite injection** — In early rounds (< 10), explore slots are replaced
   with configs from the elite archive (cross-run learning) paired with
   fresh seeds. Exploits knowledge from previous experiment runs.

5. **Seed bank** — Top-performing configs are saved to `seed_bank.json`
   across runs. Loaded at startup and injected alongside the elite archive
   for warm-starting new experiments.

**Guardrails** applied to all mutations:
- Aspect ratio capped at 2:1 in either direction
- Board area capped at 2× minimum viable area
- `placement_clearance_mm` floor at 2.0 mm
- Board dimensions rounded to 5 mm steps

### Hierarchical Group Placement

The system uses a three-level hierarchy:

1. **Intra-group placement** (`solve_group()`) — Each functional group
   (e.g., "U2 + C2, C3, C4, R3–R8, RT1, D1, D2") is placed independently
   on a virtual mini-board. The IC is centered, supporting passives are
   arranged around it using force-directed simulation with strong
   intra-group net attraction. Result: a `PlacedGroup` with relative
   component positions and a bounding box.

2. **Inter-group placement** — Groups are treated as rigid blocks and
   placed on the real board using the same force-directed + cluster
   pipeline. Signal flow order biases groups left-to-right.

3. **Post-processing** — After groups are stamped onto the board, global
   passes handle alignment (`_align_large_pairs`), overlap resolution,
   grid snap, orderedness, and edge clamping. Pinned edge components
   are restored to their assigned positions.

**Special case: all-THT groups** (e.g., BT1+BT2) skip group placement
entirely because their large footprints create oversized rigid blocks.
Instead, they are placed individually and aligned by `_align_large_pairs()`.

---


## Experimental Analysis (13-Round Study)

> *Historical findings from the first comprehensive autoplacer validation run.*

### Key Metrics from 13-Round Experiment

| Metric | Value |
|---|---|
| Best score | 79.7 |
| Board dimensions | 120 × 85 mm |
| Board area | 10,200 mm² (17% smaller than 85 × 145 mm baseline) |
| Nets routed | 26/26 (100%) |
| Shorts | 0 |
| Clearance violations | 14 |
| FreeRouting crashes | 0 |

All 13 rounds completed successfully — no FreeRouting crashes, no Python
exceptions, and every round achieved 100% net routing.

### Root Causes Identified & Fixed

1. **Battery group rigid block** — BT1 + BT2 created a 115 mm wide rigid
   block because the group placer treated them as a single unit. Fixed by
   skipping group placement for all-THT groups; alignment is instead handled
   by `_align_large_pairs()` post-processing, which places them side-by-side
   without locking them into an inflexible block.

2. **Subprocess Python resolution** — Worker subprocesses used `"python3"`
   which resolved to a virtualenv Python that lacked pcbnew bindings. Fixed
   by using `sys.executable` so workers always use the same interpreter as
   the parent process.

3. **Board size compute too aggressive** — Margins and area caps were too
   large, producing boards far bigger than necessary. Reduced `block_margin`
   from 8 → 4 mm, `max_cap` from 150 → 120 mm, and tightened the overhead
   factor.

4. **Explore mode catastrophic failures** — Random configs generated boards
   as large as 195 × 110 mm because there were no guardrails on aspect ratio
   or total area. Fixed with `_clamp_board_guardrails()`: max 2:1 aspect
   ratio, area capped at 2× minimum viable area, and 5 mm step rounding.

5. **Scoring blind spots** — The scoring system had no aspect ratio penalty
   (allowing long, thin boards) and no trace length efficiency metric. Added
   `aspect_ratio` to `PlacementScore` (penalizes boards elongated beyond
   ~1.5:1) and `trace_length_score` to the experiment scoring (rewards shorter
   total trace length relative to an MST estimate).

6. **DSN clearance patch incomplete** — Only `smd_smd` clearance was patched
   in the DSN export. Now patches ALL clearance type overrides (`smd_smd`,
   `smd_to_turn_gap`, `smd_to_via_gap`, `via_to_via_gap`, etc.) so
   FreeRouting respects the design rules uniformly.

### Persistent Issues (14 Clearance Violations)

- 14 clearance violations remain in every successful round.
- **Root cause:** KiCad's DRC rules enforce 0.2 mm trace clearance, but
  FreeRouting routes with its own internal clearance model which is less
  strict in certain geometries.
- These are likely smd-to-trace or trace-to-trace clearances at pin escape
  points that FreeRouting doesn't optimize for.
- **Potential fixes:**
  - Increase trace clearance in FreeRouting rules (DSN header) to 0.25 mm.
  - Post-routing DRC-driven nudging: run KiCad DRC, parse violation
    locations, nudge offending traces by 0.05–0.1 mm.
  - Widen the DSN clearance class overrides beyond the KiCad minimums to
    give FreeRouting more margin.

---


## Optimal Parameter Regions

The following parameter ranges consistently produce the best results
(scores 70+, 26/26 nets routed, minimal DRC violations):

| Parameter | Optimal Range | Notes |
|-----------|--------------|-------|
| `placement_clearance_mm` | ~3.0 mm | Too low (< 2.0) causes courtyard overlaps; too high wastes board space |
| `force_attract_k` | 0.02–0.04 | Attraction strength along nets. Higher pulls connected components together more aggressively |
| `force_repel_k` | 150–200 | Repulsion between overlapping bounding boxes. Too high causes oscillation; too low allows overlaps |
| `cooling_factor` | 0.92–0.97 | Damping multiplier per iteration. Lower cools faster (risks local minima); higher allows more exploration |
| `max_placement_iterations` | 300–360 | More iterations help on complex boards but hit diminishing returns past ~400 |
| `orderedness` | 0.7–0.8 | High values produce neat rows/columns that route cleanly. 1.0 is too rigid; 0.0 is too chaotic |
| `scatter_mode` | `"random"` | Random initial scatter outperforms cluster-based seeding for this board topology |
| `edge_margin_mm` | 5–7 mm | Margin from board edge for non-edge-pinned components. Leaves room for edge routing channels |
| `board_width_mm` | 115–125 mm | For LLUPS specifically; determined by component count and battery holder width |
| `board_height_mm` | 80–90 mm | For LLUPS specifically; enough vertical space for signal flow groups |
| `reheat_strength` | 0.05–0.15 | Moderate reheat helps escape local minima at the halfway point |
| `connector_edge_inset_mm` | 0.5–1.5 mm | Slight inset from edge for connectors |

### Anti-patterns (what does NOT work)

- `placement_clearance_mm` < 2.0 -- causes unresolvable courtyard overlaps.
- `force_repel_k` > 400 -- components oscillate and never converge.
- `orderedness` = 0.0 with `scatter_mode: "cluster"` -- organic layouts that FreeRouting struggles to route cleanly.
- Board aspect ratio > 2:1 -- long thin boards waste area and create long traces.
- `max_placement_iterations` < 100 -- not enough iterations for the force simulation to converge.

---

## Observability Model

> *Describes how board artifacts and diagnostics should be structured
> for both human and machine review.*

### Board-first observability direction

For hierarchical and subcircuit work, KiCad board files should remain the visual source of truth.

That means:

- persist meaningful `.kicad_pcb` stage snapshots first
- derive preview PNGs from those persisted boards
- expose the board paths anywhere previews are shown
- keep machine-readable summaries aligned with those board artifacts

### Current observability expectations

For accepted leaf artifacts, the preferred canonical set is:

- `solved_layout.json`
- `leaf_pre_freerouting.kicad_pcb`
- `leaf_routed.kicad_pcb`

For candidate-round observability, the preferred round-specific set is:

- `round_000N_leaf_pre_freerouting.kicad_pcb`
- `round_000N_leaf_routed.kicad_pcb`
- round-specific preview image paths
- machine-readable routing outcome fields such as:
  - router
  - reason
  - failed / skipped
  - routed internal nets
  - failed internal nets
  - routed copper summary

For parent observability, the preferred canonical set is:

- `parent_pre_freerouting.kicad_pcb`
- `parent_routed.kicad_pcb`
- `solved_layout.json`

### Why this matters

Human review needs to answer:

- what exact board file produced this preview?
- what stage is this board from?
- did this round route, fail, or get skipped?

Machine review needs to answer:

- which nets failed?
- what router outcome was recorded?
- which persisted board artifact corresponds to that outcome?

### Recommended next observability work

1. Extend the same explicit board-path observability model across parent-stage artifacts.
2. Ensure every meaningful parent stage persists a `.kicad_pcb` before rendering previews.
3. Keep live status payloads and analysis views aligned with persisted board paths rather than PNG-only assumptions.
4. Add richer machine-readable summaries for parent composition and parent routing transitions.
5. Prefer stage-specific board snapshots over shared artifact-level previews whenever candidate-round inspection is involved.

