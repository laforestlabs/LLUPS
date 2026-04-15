# Autoplacer — Next Steps & Technical Reference

This document covers experimental findings, theory of operation, optimal
parameter regions, and the future roadmap for the hierarchical group-based
PCB placement system.

---

## Experimental Analysis (13-Round Study)

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
   ~1.5:1) and `trace_length_score` to `ExperimentScore` (rewards shorter
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

## Theory of Operation

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

### Experiment Loop (4 Phases)

The `autoexperiment.py` outer loop runs each round through four phases:

```
/dev/null/pipeline.txt#L1-8
┌─────────────┐     ┌──────────────┐     ┌───────────┐     ┌──────────┐
│  Placement   │────▶│   Routing    │────▶│    DRC    │────▶│ Scoring  │
│  (solver)    │     │ (FreeRouting)│     │  (KiCad)  │     │ (unified)│
└─────────────┘     └──────────────┘     └───────────┘     └──────────┘
     ~1-3s               ~10-30s             ~1-2s             <1s
```

1. **Placement** — `PlacementSolver.solve()` arranges components on the
   board. If the placement score is below `min_placement_score`, routing
   is skipped entirely (saves 15–30 s on degenerate layouts).

2. **Routing** — Export to DSN, run FreeRouting (Java), import SES result.
   FreeRouting auto-routes all nets with up to `freerouting_max_passes`
   passes within `freerouting_timeout_s`.

3. **DRC** — `quick_drc()` runs KiCad's design rule checker and counts
   shorts, unconnected nets, clearance violations, and courtyard overlaps.

4. **Scoring** — `ExperimentScore.compute()` produces a single 0–100
   metric combining all quality dimensions.

### Scoring System

The unified `ExperimentScore` combines six weighted components:

| Component | Weight | What it measures |
|-----------|--------|------------------|
| `placement` | 0.15 | Pre-routing placement quality (net distance, crossings, containment, group coherence, aspect ratio) |
| `route_completion` | 0.50 | Fraction of nets successfully routed (dominates the score) |
| `via_penalty` | 0.10 | Fewer vias per routed net = better; blended with trace length efficiency |
| `containment` | 0.05 | Board containment from placement score |
| `drc` | 0.20 | DRC violation count (shorts, unconnected, clearance, courtyard) |
| `area` | 0.15 | Nonlinear reward for smaller board area (exponential decay) |

**Hard score gates** prevent misleading totals:
- Route completion ≤ 50% → score capped at 40
- Route completion < 90% → score capped at 70

The inner `PlacementScore` (used within placement before routing) has its
own weight distribution:

| Component | Weight | Description |
|-----------|--------|-------------|
| `net_distance` | 0.22 | Connected components close together |
| `crossover_score` | 0.18 | Fewer ratsnest crossings |
| `board_containment` | 0.12 | All pads/bodies inside board |
| `edge_compliance` | 0.10 | Connectors/holes on edges |
| `courtyard_overlap` | 0.10 | No overlapping courtyards |
| `smt_opposite_tht` | 0.10 | SMT on opposite side of THT |
| `group_coherence` | 0.10 | Functional groups stay compact |
| `aspect_ratio` | 0.05 | Penalize elongated boards |
| `compactness` | 0.02 | Tighter layouts |
| `rotation_score` | 0.01 | Pad alignment quality |

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

- `placement_clearance_mm` < 2.0 — causes unresolvable courtyard overlaps.
- `force_repel_k` > 400 — components oscillate and never converge.
- `orderedness` = 0.0 with `scatter_mode: "cluster"` — organic layouts
  that FreeRouting struggles to route cleanly.
- Board aspect ratio > 2:1 — long thin boards waste area and create
  long traces.
- `max_placement_iterations` < 100 — not enough iterations for the
  force simulation to converge.

---

## Roadmap

### 1. Intra-group routing awareness

The current intra-group placer (`solve_group()`) optimizes component
positions within each group using a force-directed simulation, but it
has no knowledge of how traces will actually be routed between pads.

**Potential improvements:**

- After intra-group placement, run a lightweight channel/escape router
  within each group's bounding box to estimate trace congestion.
- Use congestion feedback to adjust component spacing or rotation
  before the group is "frozen" as a rigid block.
- Score intra-group routability (e.g., estimated via count, trace
  crossings within the group) and feed it back into group placement
  quality metrics.

### 2. Smarter inter-group placement

The current `GroupPlacer` uses a simple force-directed approach at the
group level. Possible refinements:

- **Simulated annealing** at the group level — the small entity count
  (5–10 groups) makes SA feasible with full evaluation per step.
- **Rotation of group blocks** — currently groups are always placed
  axis-aligned. Allowing 90-degree group rotation could improve
  packing on asymmetric boards.
- **Multi-objective optimization** — balance signal flow order, edge
  constraints, thermal separation, and inter-group net length
  simultaneously using Pareto ranking.

### 3. Group-aware swap optimization

The flat solver's swap optimizer (`solve()` step 7) freely swaps any
two similarly-sized components to minimize crossover count. This is
group-blind — it can scatter group members.

**Fix:** restrict swaps to within-group or between-group as a unit.
When evaluating a swap, also check that group coherence doesn't
degrade.

### 4. Dynamic group sizing

Currently, the virtual board size for intra-group placement uses a
fixed formula: `overhead = max(2.0, 3.5 - 0.15 * n)`. This could be
made adaptive:

- Start with a tight bounding box and expand if overlap resolution
  fails to converge within a budget.
- Use the group's net density (number of inter-component connections
  per mm²) to estimate required routing clearance.

### 5. Schematic-driven pin assignment

For groups with connectors, the schematic provides signal ordering on
the connector pins. This ordering could be used to:

- Place passives in the same order as their connected connector pins
  (reduces trace crossings).
- Orient ICs so that their pin-1 side faces the signal input direction.

### 6. Thermal group separation

Groups containing thermal components (e.g., voltage regulators, power
MOSFETs) should maintain minimum distance from heat-sensitive groups.
Currently `thermal_refs` is defined in config but only affects
individual component spacing, not group-level separation.

### 7. Board shape support

The current system assumes rectangular boards. Extending to support
non-rectangular board outlines (L-shapes, circles, cutouts) would
require:

- Group placement feasibility checking against arbitrary polygons.
- Modified clamping logic for non-rectangular bounds.
- Edge classification for non-rectangular edges (curved, angled).

### 8. Test coverage

- Unit tests for `brain/groups.py` S-expression parser with edge cases
  (escaped quotes, deeply nested structures, malformed files).
- Unit tests for `brain/group_placer.py` with synthetic group
  configurations (2 groups, 10 groups, groups larger than board).
- Integration test: round-trip schematic → groups → placement → score
  with a minimal test project (3 components, 2 groups).

### 9. Clearance violation elimination

Address the persistent 14 clearance violations:

- Investigate per-violation geometry (smd-to-trace vs trace-to-trace).
- Widen DSN clearance classes to give FreeRouting more margin.
- Implement post-routing nudge pass: parse DRC violations, shift
  offending trace segments by the minimum required clearance delta.

### 10. Adaptive scoring weights

The current scoring weights are fixed. An adaptive scheme could:

- Increase `route_completion` weight early (find routable layouts first).
- Shift weight toward `drc` and `area` once 100% routing is achieved.
- Use Bayesian optimization to tune weights based on historical data.