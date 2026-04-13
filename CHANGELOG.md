# LLUPS Engineering Changelog

## 2026-04-13: Connector Orientation Fix — Body Center Reference

### Bug Fix
- **`_best_rotation_for_edge()` used wrong reference point**: The function measured pad centroid direction from the footprint origin (`comp.pos`), which for connectors like USB-C (GCT USB4085) is at corner pad A1. The pad centroid from origin was at ~22.7° — close enough to snap to 0° delta — so the connector was left at 0° (opening downward instead of toward the board edge). Fix: use body center (courtyard bbox center) as reference. From body center, the pad centroid is at 270° (perpendicular to opening face), which correctly produces rotation 270° for a left-edge connector.

### Data Model
- **Added `body_center: Point | None` to `Component`**: Populated from courtyard bbox center during PCB load. Transformed alongside pads in `_update_pad_positions()`, `_swap_pad_positions()`, and `_shift_pads_inside()`.

### Orientation Validation
- **`orientation_check.py` rewritten**: Replaced hard-coded expected rotation table (`left→270°`, `right→90°`, etc.) with dynamic pad-centroid-vs-body-center check. Now correctly validates any connector footprint regardless of internal geometry.

### Files Changed
- `autoplacer/brain/types.py` — `body_center` field on Component
- `autoplacer/hardware/adapter.py` — populate body_center from courtyard/bbox center
- `autoplacer/brain/placement.py` — body_center in rotation calc, transform on move/rotate/swap/shift
- `scoring/orientation_check.py` — dynamic facing validation

---

## 2026-04-13: Rotation Convention Fix + Pad Containment + Connector Grouping

### Critical Bug Fixes
- **Rotation convention**: `_update_pad_positions()` and all rotation code fixed from CCW (standard math) to KiCad's CW convention (`x'=x·cos+y·sin, y'=-x·sin+y·cos`). This was the root cause of pads appearing outside the board — model computed pad positions on the wrong side vs where KiCad actually placed them.
- **Layer flip pad mirroring**: `_assign_layers()` now mirrors pad X offsets when flipping components to B.Cu, matching KiCad's `Flip()` behavior.
- **Step reordering**: Layer assignment now runs before edge pinning so connector positions account for flipped pad geometry.
- **`_best_rotation_for_edge`**: Rotation delta fixed from `desired - current` to `current - desired` (CW direction).

### Pipeline Hardening
- **Hard pad-containment gate**: Zero-tolerance rejection — any pad outside board boundary blocks routing. `pads_outside_board` count added to PlacementEngine output.
- **Post-restore clamp**: `_clamp_pads_to_board()` runs after `_restore_pinned_positions()` as defense in depth.

### New Features
- **Connector edge grouping**: Same-edge connectors placed in compact rows/columns with `connector_gap_mm` spacing. Auto-oriented via `_best_rotation_for_edge()` so pads face board center.
- **Orderedness parameter**: 0.0-1.0 strength for aligning passives into grid near IC group leaders. Added to minor/major mutation search space.
- **Edge-pinned rotation skip**: `_optimize_rotations()` skips components in `_pinned_targets` to preserve edge orientation.

### Results
- Best score: 92.7 (up from 91.1), 0 pads outside board (verified by KiCad reload)

---

## 2026-04-11: Codebase Cleanup — Old Python Router Removed

Removed all remnants of the custom Python A*/RRR autorouter. FreeRouting is now the sole routing engine.

### Files Deleted
- `simple_router.py` — old A* grid router
- `reroute_net.py` — old MST-based Python net rerouter
- `autoplacer/_apply_routing.py` — old routing application code
- `BUGFIX_PLAN.md`, `IMPROVEMENT_PLAN.md` — old planning docs
- `docs/freerouting-plan.md`, `docs/dashboard-automation.md` — completed migration plans

### Code Cleaned
- `autoroute.py`: removed dead `--no-rrr` flag and `rip_up` parameter
- `diff_rounds.py`: removed A\* Expansions and RRR timing fields
- `generate_report.py`: removed RRR timing display and per-net `a_star_expansions` column
- `plot_experiments.py`: removed RRR bar from stacked timing chart

### Documentation Updated
- `docs/next-steps.md`: rewritten to reflect current state (150-round experiment complete, old items removed)
- `docs/monitoring-guide.md`: removed rip-up-reroute reference from timing chart description

---

## 2026-04-09: Autoplacer Improvement Plan — Implementation & Validation

### Changes Implemented (from IMPROVEMENT_PLAN.md)

**program.md (1A):** Fixed param ranges — `clearance_mm` floor raised to 0.2 (DRC min), removed useless `existing_trace_cost` tunable, added `grid_resolution_mm` [0.25–0.5], widened `force_repel_k` to 50–500, `max_rips_per_net` to 3–20. Added `net_priority` for 3 always-failing nets (`/CHG_N`, `/NTC_SENSE`, `Net-(F1-Pad2)`).

**config.py (1C, 2A):** Grid default 0.5→0.25mm, `max_search` 1M→2M, added `net_priority: {}` default.

**autoexperiment.py (1B, 3A, 3B, 3C):**
- Shorts penalty changed from multiplicative log-scale (÷2.5 at 31 shorts) to additive (−0.5/short, max −15). Preserves routing-completion signal.
- `grid_resolution_mm` added to minor (0.25–0.5) and major (0.2–0.5) tunable ranges.
- 20% of each batch reserved for pure exploration (random config + seed).
- Per-net failure counts tracked and written to round detail JSON.
- `net_priority` from program.md injected into all candidate configs.

**conflict.py (2D):** RRR made more aggressive — default iterations 5→25, max victims per rip 2→4, stagnation limit 2→6, timeout 8→60s, victim search bbox ±5→±10mm.

**router.py (2B):** `_prioritize_nets` now applies `net_priority` overrides from config, boosting historically-failing signal nets.

**grid_builder.py (2C):** Escape corridors carved in all 4 directions from each pad (was nearest-edge only). Corridor width scales with grid resolution: `max(2, ceil(3·res/0.25))` cells.

### Validation Run (20 rounds, still in progress as of writing)

- **Baseline score: 41.02** (was 21.83 — 88% improvement from additive penalty alone)
- **Best after 5 rounds: 56.72** — 21/26 nets routed (was 13/26), from an explore config with `force_repel_k=129.5`, `cooling_factor=0.94`
- Round 1 (minor): score=51.7, 18/26 routed, 77 shorts
- Round 4 (explore): score=56.7, **21/26 routed**, 96 shorts ← new best
- `Net-(F1-Pad2)` now routes consistently (was never-routed); `/CHG_N` and `/NTC_SENSE` routed in some rounds
- 2 of 5 rounds kept (40% acceptance, was 10.7%)

### Performance Problem: Rounds Too Slow

Each round takes **14–22 minutes** (was ~2 min at 0.5mm grid). Root causes:

1. **4× grid cells** (0.25mm): ~167K cells/layer → A* expansions jumped from ~5M to 55–91M per round
2. **RRR timeout 60s**: each failed net burns up to 60s in rip-up cycles (was 8s)
3. **max_search 2M**: A* explores 4× more nodes before giving up on impossible paths
4. **Wider escape corridors in all 4 directions**: more cells to clear per pad, slower grid construction

The experiment was running correctly but appeared stuck because the first batch of 5 workers took ~14 min each. The status file only updates on batch completion, so there was no visible progress for long stretches.

**Mitigation ideas for next run:**
- Try `grid_resolution_mm=0.35` as a compromise (2× cells vs 4×)
- Lower `rrr_timeout_s` to 30s (diminishing returns past 30s)
- Cap `max_search` at 1M (enough for 0.25mm, most failures hit the cap anyway)
- Add per-worker progress heartbeats to status file so long rounds don't look hung

---

## 2026-04-09: 45-Round Autoexperiment Audit

- Ran `python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb --rounds 45 --program .claude/skills/kicad-helper/scripts/program.md`
- Live monitoring used `.experiments/run_status.json`, `.experiments/run_status.txt`, and the Flask dashboard on port 5000
- Run completed in about 12 minutes with 22 workers; artifacts written to `.experiments/` including `experiments.jsonl`, `rounds/`, `progress.gif`, and `experiments_dashboard.png`
- Baseline reported `score=0.00`, `shorts=38`, `drc_total=393`
- No candidate rounds were kept; final best stayed the baseline (`Best config delta from default: {}`)
- All 45 round detail files show `routing.total = 0`, `routing.routed = 0`, `routing_ms = 0.0`, `rrr_ms = 0.0`, and empty `per_net` data
- Representative round JSONs also show `placement.total = 0.0` and `placement.board_containment = 0.0`, so the experiment is not producing valid placed-and-routed candidates
- The negative scores in `experiments.jsonl` are failure sentinels from `autoexperiment.py` worker handling (`score.total = -1.0`) plus downstream penalty logic, not genuine improvements
- Score ordering is therefore misleading in this run: the highest logged round score (`-0.358`, round 33) coincided with worse DRC (`61` shorts, `438` total violations) rather than a better board
- Main next step for follow-up: instrument or temporarily unmask worker exceptions in `autoexperiment.py` / `autoplacer.pipeline` to identify why the worker path returns sentinel failures while still emitting DRC snapshots

## Phase 3: Performance Optimizations

**Commit:** `462962d`

- `came_from` dict → numpy array (eliminates tuple allocation per node)
- Footprint lookups vectorized with numpy slices (9 reads → 1 C call for multi-cell traces)
- Base-grid caching in RipUpRerouter (90% reduction in grid-building overhead)
- Result: 2-3x speedup on deep A* searches

## Phase 2: Correctness Fixes (Hard-Block + Escape Via)

**Commit:** `83256e9`

- Completed traces now hard-blocked at 1e6 (impossible to cross)
- Escape vias marked on grid immediately after creation
- Via markings include clearance margin (+0.2mm)
- A* max_search raised from 500K to 2M nodes
- Test added: `test_hard_block_prevents_cross_net_routing` (all 9 unit tests pass)

## Phase 1: Root Cause Analysis

Identified 3 critical bugs causing ~80 DRC shorts per routing run:

1. Cross-net traces marked as soft obstacles (cost=100), not hard blocks (1e6)
2. Escape vias never marked on grid → via collisions
3. Via markings had no clearance margin

## Grid & Scoring Tuning

- Grid resolution: 0.5mm → 0.25mm. At 0.5mm the router can't distinguish "fits" from "doesn't fit" (trace+clearance rounds to 1 cell). At 0.25mm traces can thread between existing routes honestly.
- Route completion weight: 50% → 65%
- Crossover score in placement: 20% → 30%
- Deleted `drc_sweep.py` (complex nudge logic, didn't help; -287 lines)
- Reverted `mark_segment` point-to-segment distance → bbox (simpler, safer)

## Code Cleanup

- Extracted `GridBuilder` class and `build_grid()` / `path_to_traces()` into `autoplacer/brain/grid_builder.py` — eliminated ~120 lines of duplication between `router.py` and `conflict.py`
- Rip-count-aware victim selection in RRR (nets ripped many times become less likely victims)

---

## Key Learnings

1. **Finer grids > complex algorithms** for congested 2-layer boards.
2. **Hard-blocking is correct** — honest metrics expose real routing constraints. Previously got "26/26 routed" by routing through other nets (hidden shorts).
3. **Over-engineering makes things worse** — start simple, add complexity only when measured to help.
4. **Scoring weights are hyperparameters** — tune them like any other search lever.
5. **Placement clearance ≠ routing clearance** — tighter placement (2.5mm → 1.5mm in experiments) helps routing by shortening traces.

---

## Current State

- **Best score**: 27.5 (21/26 nets, 32 shorts, 0.25mm grid)
- **Baseline at 0.5mm grid**: 26/26 nets (100%), ~81 DRC shorts, 432s per routing
- Trade-off: 0.25mm grid is 5x slower but produces honest routing
- Shorts are DRC-hard (real clearance violations, not routing artifacts)

## Root Causes of Remaining Shorts

1. **Via placement grid quantization** — vias snap to 0.5mm grid; two nets may collide
2. **Trace-to-trace clearance** — hard blocks force tight packing, traces can be 0.195mm apart (below 0.2mm DRC minimum)
3. **Component escape corridors too narrow** — escape vias collide near boxed-in pads

---

## Future Ideas

### High Priority
1. Per-net adaptive grid resolution (0.2mm near congestion, 0.5mm elsewhere)
2. Escape via optimization (avoid collision clusters)
3. Net routing order: power-first + MST-based ordering
4. Wider traces for power nets (dynamically thin at tight-pitch footprints)

### Medium Priority
1. Parallel net routing (spatially independent nets on read-only grid copies)
2. Hierarchical routing (power/GND first, then high-priority signals)
3. Thermal-aware placement (pin high-current traces for direct routing)
4. Incremental grid updates (shadow grid, only update touched cells)

### Lower Priority
1. Continuous cost field instead of binary soft/hard obstacles
2. Simulated annealing RRR
3. ML placement seeding

---

## Files Changed (Cumulative)

| File | Changes |
|------|---------|
| `autoplacer/brain/router.py` | Hard-block logic, max_search, numpy A*, imports grid_builder |
| `autoplacer/brain/grid_builder.py` | New — extracted grid construction + path_to_traces |
| `autoplacer/brain/conflict.py` | RRR base-grid caching, rip-count victims, imports grid_builder |
| `autoplacer/brain/types.py` | ExperimentScore weights (0.15/0.65/0.10/0.10) |
| `autoplacer/config.py` | max_search=1M, trace_cost=100, grid_resolution=0.5 |
| `autoplacer/brain/test_router_grid_behavior.py` | Hard-block verification test |
