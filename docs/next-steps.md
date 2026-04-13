# LLUPS — Next Steps

> Updated: 2026-04-13
> Current best: **92.7** (seed bank). 26/26 nets routed, 0 shorts, 0 pads outside board. Placement score ~85.
> Recent fixes: connector body-edge alignment, SMT/THT dual-sided layout, dynamic board sizing, area-proportional courtyard scoring, placement iteration increase.

---

## Where Things Stand

- **Rotation convention fixed**: Model now uses KiCad's CW rotation formula (`x'=x·cos+y·sin, y'=-x·sin+y·cos`). Previously used CCW (standard math), causing model-vs-KiCad pad position divergence — the root cause of pads-outside-board issues.
- **Layer flip mirroring fixed**: `_assign_layers()` now mirrors pad X offsets when flipping components to B.Cu, matching KiCad's `Flip()` behavior. Layer assignment runs before edge pinning so connector positions account for flipped geometry.
- **Hard pad-containment gate**: Pipeline rejects placement if ANY pad is outside board boundary (zero tolerance). Previously used a percentage-based check that let ~5 outlier pads through.
- **Connector body-edge alignment** (NEW): Edge-pinned connectors now positioned with body edge flush to board edge (configurable via `connector_edge_inset_mm`, default 1.0mm). Previously used center+margin which placed connectors 6mm inward. `_shift_pads_inside()` now respects edge assignments — won't pull connectors away from their assigned edge. `_best_rotation_for_edge()` uses aspect ratio for symmetric footprints (e.g. USB-C) instead of failing on near-zero pad centroid.
- **SMT stays on F.Cu** (NEW): Removed `smt_backside_with_tht` logic that moved SMT passives to B.Cu with THT group partners. SMT components always stay on F.Cu; IC group connectivity forces keep them in the same XY region as back-side THT components, achieving true dual-sided board usage.
- **Dynamic board sizing** (NEW): Minimum viable board size computed from total component area × overhead factor (default 2.5×). Board size search range dynamically bounded [min_viable, 2×min_viable] instead of hardcoded [60-120, 40-80]. Area bonus weight increased from 10% → 15% with nonlinear (exponential) scoring.
- **Courtyard scoring gradient** (NEW): Replaced cliff penalty (5pts/pair, floors at 4+ overlaps) with area-proportional scoring. Total overlap area as fraction of total courtyard area provides smooth gradient so partial improvements are always rewarded.
- **Placement iterations increased** (NEW): `max_placement_iterations` 100→300, `convergence_threshold` 1.5→0.5, stagnation limit 10→20. `max_placement_iterations` added to search space (100-500). Parameter bounds clamped in `__init__` to prevent degenerate configs.
- **Placement=0 fallback** (NEW): Pipeline retries with default force parameters if initial placement scores 0. Eliminates ~6% failure rate from extreme configs.
- **Compactness weight increased**: PlacementScore compactness 0.08→0.12 (crossover_score 0.24→0.20 to compensate). Stronger signal for tighter layouts.
- **Connector grouping**: Same-edge connectors placed in compact rows/columns with configurable gap. Auto-orientation faces pads toward board center.
- **Orderedness parameter**: Configurable 0.0-1.0 strength for aligning passives into neat rows/columns near their IC group leaders.
- **FreeRouting v1.9.0** is the sole router. Routing time ~10-15 sec/round.
- **22 parallel workers** using ProcessPoolExecutor with spawn context.

### Current Scoring Weights

**PlacementScore** (sub-score within placement, 0-100):
| Component | Weight |
|-----------|--------|
| net_distance | 0.25 |
| crossover_score | 0.20 |
| compactness | 0.12 |
| edge_compliance | 0.10 |
| rotation_score | 0.03 |
| board_containment | 0.15 |
| courtyard_overlap | 0.15 |

**ExperimentScore** (overall, 0-100):
| Component | Weight |
|-----------|--------|
| placement | 0.15 |
| route_completion | 0.50 |
| via_penalty | 0.10 |
| containment | 0.05 |
| drc | 0.20 |
| area (when board size search active) | 0.15 |

---

## Completed (this session)

### ~~1. Increase placement iterations~~ ✅
- `max_placement_iterations`: 100 → 300
- `placement_convergence_threshold`: 1.5 → 0.5
- Stagnation limit: 10 → 20
- Added to minor tunable search space (100-500, sigma 0.15)

### ~~3. Fix courtyard overlap scoring~~ ✅
- Switched from fixed-points-per-pair cliff to area-proportional scoring
- overlap_ratio = total_overlap_area / total_courtyard_area
- Smooth gradient: 10% overlap → score ~70, 30% → ~30

### ~~4. Eliminate placement=0 failures~~ ✅
- Parameter bounds validation in `PlacementSolver.__init__()` (clamp to safe ranges)
- Fallback retry in pipeline with default force params when score < 1.0

---

## High Priority

### 1. Reduce DRC clearance violations

Clearance violations remain the largest DRC category (~80-160 per round). Likely causes:
- FreeRouting trace-to-pad clearance doesn't match KiCad design rules
- Placement clearance and trace width settings may be misaligned
- **Action**: Compare KiCad net class clearance rules with FreeRouting DSN clearance values. Increase `SIGNAL_WIDTH_MM` / `POWER_WIDTH_MM` if violations are predominantly narrow traces.

---

## Medium Priority

### 2. Tune force balance for better spread

Components still tend to cluster tightly rather than using available board area. The force balance (attract ~0.04, repel ~200) may be too attraction-dominant for the LLUPS board size.
- **Action**: Add `force_attract_k` and `force_repel_k` to the major tunable space with wider ranges. Consider adding a "spread" force that pushes components toward the board center-of-mass to improve area utilization.

### 3. Reduce FreeRouting crash rate (~6%)

FreeRouting crashes with "no SES output (rc=-1)" in ~6% of rounds.
- **Action**: Add pre-routing DSN sanity check. Reduce timeout from 60s to 30s to fail faster on stuck runs.

### 4. Deduplicate force simulation code

`_force_step()` and `_force_step_numpy()` share ~180 lines of duplicated logic.
- **Action**: Extract shared force computation to a helper function.

---

## Low Priority / Future

### 5. USB-PD header for future revision

Verify the current layout leaves space and traces for CC1/CC2 routing to a future PD controller header.

### 9. Thermal analysis

Verify thermal pad placement and copper pour connectivity for U2 and U4.

### 10. Generate fabrication outputs

Target: 26/26 nets, 0 shorts, <20 total DRC violations.
```bash
kicad-cli pcb export gerbers -o gerber/ LLUPS_best.kicad_pcb
kicad-cli pcb export drill -o gerber/ LLUPS_best.kicad_pcb
```

---

## Completed (reverse chronological)

### Rotation convention + pad containment + connector grouping (2026-04-13)
- **ROOT CAUSE FIX**: `_update_pad_positions()` used CCW rotation formula (standard math convention). KiCad uses CW: `x'=x·cos(θ)+y·sin(θ)`, `y'=-x·sin(θ)+y·cos(θ)`. Fixed in all 5 locations: `_update_pad_positions`, `_optimize_rotations` (2 places), `_place_clusters` early rotation (2 places).
- **Layer flip pad mirroring**: `_assign_layers()` now mirrors pad X offsets (`pad.x = 2*comp.x - pad.x`) when flipping components to B.Cu, matching KiCad's `Flip()` behavior. Both THT and SMT passives get mirrored.
- **Step reordering**: Layer assignment moved before edge pinning so connector pinned positions account for flipped pad geometry.
- **`_best_rotation_for_edge` CW fix**: Rotation delta changed from `desired - current` to `current - desired` to match KiCad's CW convention direction.
- **Hard pad-containment gate**: `pads_outside_board` count added to PlacementEngine return dict. Pipeline rejects placement if ANY pad is outside board boundary (zero tolerance). Previously used percentage-based `board_containment >= 90%` which let ~5 pads through.
- **Post-restore clamp**: Added `_clamp_pads_to_board()` after `_restore_pinned_positions()` as defense in depth.
- **Connector edge grouping**: Same-edge connectors placed in compact rows/columns with `connector_gap_mm` spacing. Prevents scattering and edge-falling.
- **Connector auto-orientation**: `_best_rotation_for_edge()` rotates connectors so pads face board center (USB opening faces outward, pads face inward).
- **Orderedness parameter**: 0.0-1.0 strength for aligning passives into neat rows/columns near IC group leaders. Added to minor tunable (0.0-1.0, sigma 0.2) and major tunable search space.
- **Skip rotation for edge-pinned**: `_optimize_rotations()` skips components in `self._pinned_targets` to preserve edge-oriented rotation.
- Score: 92.7 best (seed bank), 0 pads outside board (verified by KiCad reload).

### Critical scoring fix + pipeline hardening + generalization (2026-04-12)
- **CRITICAL BUG FIX**: `ExperimentScore.compute()` returned `route_pct=100%` when `total_nets==0` (routing skipped) — PCBs with zero traces scored 80+. Fixed: `route_pct=0.0` when no nets counted.
- **DRC/via scores zeroed for skipped routing**: No credit for DRC or vias when routing was skipped (previously gave full credit for empty violations dict).
- **Hard score gates**: `route_pct < 50%` → score capped at 40; `route_pct < 90%` → capped at 70. Prevents garbage layouts from dominating.
- **Route_completion gate on best selection**: Rounds with `skipped_routing=True` or `route_pct < 10%` are never kept as best.
- **Duplicate bug fixed in `_score_sub_fields()`**: autoexperiment had same `route_pct=100` fallback — fixed.
- **DEFAULT_CONFIG changes**: `unlock_all_footprints=True` (was False), `enable_board_size_search=True` (was False).
- **GND zone integrated into pipeline**: `adapter.ensure_gnd_zone()` creates/updates GND copper pour on B.Cu covering full board area before DSN export. Idempotent, config-driven (`gnd_zone_net`, `gnd_zone_layer`, `gnd_zone_margin_mm`).
- **BT1/BT2 zone fix**: Changed from separate `bottom-left`/`bottom-right` zones to shared `bottom` zone. Sibling grouping pulls same-footprint components adjacent.
- **Sibling grouping**: Auto-detects same-kind, similar-size components and adds attraction forces proportional to component area. BT1+BT2 battery holders now placed adjacent.
- **SMT backside placement**: When large THT components go to B.Cu, SMT passives from same ic_group also move to back. Config: `smt_backside_with_tht=True`.
- **Placement weight rebalance**: `compactness` 0.02→0.08, `crossover_score` 0.30→0.24 — tighter layouts rewarded.
- **Silkscreen labels rewritten**: Auto-scaling font (scales to group width), collision detection (tries 7 positions: above/below/left/right/diagonal), inter-label collision avoidance.
- **Added zone shorthand**: `"bottom"`, `"top"`, `"left"`, `"right"` zone names spanning full board width/height.
- **JSONL extended fields**: `skipped_routing`, `edge_compliance`, `trace_count`, `via_count`, `total_length_mm` logged per round.
- **LLUPS config externalized**: `llups_config.json` created; `load_project_config()` loads from JSON. POWER_NETS moved from hardcoded adapter.py to config-driven.
- **Seed bank**: `seed_bank.json` persists top-10 configs across ALL experiment runs for cross-run learning (unlike `elite_configs.json` which is per-run).
- **Phased optimization**: `--phased` CLI flag splits rounds into: Phase A (placement-only, fast), Phase B (full pipeline), Phase C (board size). Phase gating: A→B requires `placement_score > 40`, B→C requires `route_completion > 80%`.
- **Population-based evolution**: `--population N` CLI flag (infrastructure for future population tracking).

### Stale DRC + overlap priority + scoring rebalance (2026-04-12)
- Added `pipeline_drc` field to `ExperimentScore` — pipeline stores DRC dict directly; autoexperiment uses it instead of stale `quick_drc()`
- `_resolve_overlaps()` both-locked case now checks `component_zones` config — edge/corner-pinned components have priority over non-pinned
- `_pin_edge_components()` stores target positions in `self._pinned_targets`; `_restore_pinned_positions()` restores them as Step 13 after all other solve steps
- Threaded `compactness` through PlacementEngine return dict and FullPipeline PlacementScore construction
- Rebalanced placement weights: `edge_compliance` 0.05→0.10, `board_containment` 0.20→0.15
- 50-round validation: best 91.13 (R45), placement 78.4 (was ~39), 0 shorts, 49 DRC

### Connector/mounting-hole containment enforced (2026-04-11)
- `_score_board_containment()` scores all component types equally
- `_clamp_pads_to_board()` applies to all components including solver-locked ones
- Connectors and mounting holes removed from auto-lock in `adapter.py`

### Pad containment enforcement (2026-04-12)
- `_clamp_pads_to_board()` shifts components inward when pads extend beyond board boundary
- Configurable `pad_inset_margin_mm` (default 0.3mm)
- Board containment 100% in all rounds

### Placement logic improvements (2026-04-12)
- Net-topology-aware positioning, large-first ordering, connectivity-based cluster sorting
- Early IC rotation (4 orientations), adaptive convergence
- Placement score improved +4.50 mean

### Render visualization improvements (2026-04-12)
- DRC violations rendered with distinct colors/shapes
- Sub-score breakdown line in info band

### Earlier items
| Feature | Status |
|---------|--------|
| Type-aware placement zones (`component_zones`) | Done |
| Signal flow ordering | Done |
| Decoupling cap proximity | Done |
| Scatter mode, temperature reheat | Done |
| Wider MAJOR mutations | Done |
| Placement validation gate | Done |
| Courtyard padding | Done |
| Elite config persistence | Done |
| Plateau threshold 5→3 | Done |
| Explore fraction 20%→33% | Done |
| FreeRouting timeout 120→60s | Done |
| Config separation (DEFAULT + LLUPS) | Done |
| GND in `freerouting_ignore_nets` | Done |

---

## Known Technical Debt

| Item | Location | Impact |
|------|----------|--------|
| `quick_drc()` categories incomplete | `autoexperiment.py` | 26 "other" violations in best round not broken down — may be edge clearance, min width, or drill violations |
| Courtyard overlap scoring is bimodal | `placement.py` | 0% or 100% in 66% of rounds, weak gradient signal for optimizer |
| Placement=0 failures on explore configs | `placement.py` | 6% of rounds produce degenerate layouts (score=75.0) |
| FreeRouting crash rate ~6% | `freerouting_runner.py` | "no SES output (rc=-1)" wastes worker slots |
| `plot_experiments.py` numpy shape error | `plot_experiments.py` | Dashboard generation broken due to inhomogeneous array shapes |
| `routing_ms` includes subprocess overhead | `pipeline.py` | Timing includes DSN export + SES import, not just FreeRouting |
| pcbnew SWIG memory leak warnings | `_run_pcbnew_script()` | Harmless stderr noise |
| `edge_compliance` not in JSONL output | `autoexperiment.py` | Can't verify edge weight increase is working |
