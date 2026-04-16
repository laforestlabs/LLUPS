# LLUPS — Next Steps

> Updated: 2026-04-16
> Current best: **92.7** (seed bank). 26/26 nets routed, 0 shorts, 0 pads outside board. Placement score ~85.
> Recent fixes: connector body-edge alignment, SMT/THT dual-sided layout, dynamic board sizing, area-proportional courtyard scoring, placement iteration increase.
> Subcircuits redesign status: in progress, but not yet MVP. Current hierarchical work proves data flow and routed-child preservation, but does not yet produce a credible routed parent board.
> Current blocker: the real leaf FreeRouting path now reaches stamped KiCad leaf boards and visible routing activity, but the stamped `leaf_pre_freerouting.kicad_pcb` is still illegal before routing, so the pipeline now correctly fails at a pre-route legality gate instead of blaming routed copper.

---

## Subcircuits MVP Takeover (next session)

### Current reality

The current subcircuits branch has these pieces working:

- true-sheet hierarchy parsing
- leaf extraction from the full board into local board states
- leaf placement solving
- canonical solved artifact persistence in `solved_layout.json`
- rigid solved-artifact loading and transform helpers
- parent composition from solved child artifacts
- preservation of routed child copper in parent composition
- lightweight parent interconnect routing from transformed anchors
- stamping a composed parent state into a real `.kicad_pcb`
- real leaf FreeRouting invocation from stamped KiCad leaf boards
- canonical routed-copper import from routed KiCad leaf boards
- per-leaf render diagnostics under `.experiments/subcircuits/<slug>/renders/`

However, this is **not yet MVP**.

The current routed subcircuit flow no longer falls back to the lightweight leaf router in the real leaf path, but the stamped pre-route leaf board is still illegal before FreeRouting can be fairly judged. A recent on-screen FreeRouting capture was still encouraging because it showed visible leaf routing activity on a real stamped board, but the pipeline now correctly rejects the leaf earlier when the pre-route board itself is malformed or edge-coupled geometry is wrong. The preview/demo path should therefore be treated as a debugging scaffold, not as the target deliverable.

### What is explicitly not MVP

The following do **not** count as MVP:

- a synthetic or readability-only hierarchical demo
- a parent board composed from heuristic Manhattan-routed leaves
- a parent board that merely proves routed child copper can be stamped into a parent board
- a DSN that loads in FreeRouting but starts from a malformed or non-credible parent board
- a preview image that requires interpretation rather than showing a sane board directly

### MVP definition for subcircuits

The minimum viable product for the LLUPS subcircuits redesign is:

1. solve selected leaf subcircuits with real placement optimization
2. route those leaf subcircuits with **FreeRouting**, not the heuristic Manhattan router
3. validate each accepted leaf artifact with at least a basic DRC / legality gate
4. persist those accepted routed leaf artifacts as the canonical child inputs
5. compose a parent board from those routed leaf artifacts
6. preserve the routed child copper exactly in the parent board
7. launch parent FreeRouting from that preloaded parent board **without clearing the child copper**
8. produce a parent board that is human-readable in KiCad and credible enough to inspect before and after parent routing
9. make the flow reproducible from CLI without ad hoc manual patching

### Immediate takeover priorities

The next agent should work in this order:

#### 1. Fix stamped pre-route leaf legality so FreeRouting-backed leaf artifacts can be accepted
The real leaf solve path now does:

- leaf placement
- stamp a real leaf `.kicad_pcb`
- export DSN
- run FreeRouting
- import SES
- import routed copper back into canonical artifact structures

The current blocker is earlier in the flow: the stamped `leaf_pre_freerouting.kicad_pcb` is still illegal for at least the `USB INPUT` leaf, so the next session should focus on preserving source-board edge relationships for edge-pinned parts rather than tweaking routed-copper acceptance first.

The current Manhattan router may remain as a fallback for debugging elsewhere, but it must not be reintroduced as the canonical routed-artifact path for MVP.

#### 2. Keep and extend the leaf acceptance gates
Each leaf artifact should carry validation metadata and be rejected if it is obviously bad.

Minimum acceptance checks:
- no Python exceptions
- no malformed board geometry
- no illegal pre-route board geometry
- no obviously illegal routed geometry
- basic DRC / legality summary persisted with the artifact
- anchor completeness summary persisted with the artifact
- render diagnostics persisted with the artifact

Current status:
- a pre-route legality gate now exists and correctly fails with `illegal_pre_route_geometry`
- this is an improvement because it distinguishes “bad stamped board” from “bad routed copper”

#### 3. Fix LLUPS leaf anchor completeness
The current LLUPS-specific blockers are still:
- `USB INPUT` has incomplete anchor coverage
- `BATT PROT` has no usable anchors
- battery-related artifacts are not yet integrated into a credible parent routing story

These must be improved before the parent routing story is credible.

#### 4. Compose the real root parent from accepted routed leaves
Once routed leaf artifacts are real and accepted, compose the actual root parent from those artifacts.

Important:
- preserve child copper exactly
- do not treat the compact demo layout as a final placement strategy
- if necessary, add a simple but sane parent placement heuristic before parent FreeRouting

#### 5. Run parent FreeRouting without clearing child copper
This is the key MVP milestone.

The parent routing path must:
- start from the composed parent board with routed child copper already present
- export DSN from that board
- run FreeRouting without first wiping the child traces
- import SES back into a routed parent board

This is the first point where the hierarchical routing flow becomes real.

### Files most relevant to takeover

Primary files:
- `docs/subcircuits_pipeline_design.md`
- `.claude/skills/kicad-helper/scripts/solve_subcircuits.py`
- `.claude/skills/kicad-helper/scripts/compose_subcircuits.py`
- `.claude/skills/kicad-helper/scripts/demo_hierarchical_freerouting.py`
- `.claude/skills/kicad-helper/scripts/autoplacer/brain/subcircuit_solver.py`
- `.claude/skills/kicad-helper/scripts/autoplacer/brain/subcircuit_composer.py`
- `.claude/skills/kicad-helper/scripts/autoplacer/brain/subcircuit_instances.py`
- `.claude/skills/kicad-helper/scripts/autoplacer/hardware/adapter.py`
- `.claude/skills/kicad-helper/scripts/autoplacer/freerouting_runner.py`

### Important caution for the next agent

Do **not** spend the next session polishing demo cosmetics first.

The correct next milestone is:
- legal stamped pre-route leaf boards
- accepted real FreeRouting-backed leaf artifacts
- parent FreeRouting preserving child copper

That said, lightweight render diagnostics are now worth keeping because they directly expose the current blocker. Use rendering to diagnose geometry, not to mask it.

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

### 0. Subcircuits MVP takeover

Before further demo work, hierarchical subcircuits need to become a real MVP.

Top actions:
- fix stamped pre-route leaf legality, especially for edge-pinned connectors like `J1`
- keep the real FreeRouting-backed leaf routing path as the only success path
- keep and extend leaf artifact acceptance / validation
- fix incomplete LLUPS anchors (`USB INPUT`, `BATT PROT`, battery-related sheets)
- compose the real root parent from accepted routed leaves
- run parent FreeRouting while preserving preloaded child copper

Success condition:
- you can visibly inspect legal pre-route leaf boards, then routed leaf boards, then open a parent board that already contains those routed leaves, then continue parent routing from that state

Diagnostic note:
- each leaf artifact should now grow a small render bundle under `.experiments/subcircuits/<slug>/renders/`
- preferred artifacts: pre-route/routed board snapshots, DRC JSON sidecars, DRC overlays, and a pre-vs-routed contact sheet

### 1. Fix pre-route leaf legality before tuning routed DRC

For the current subcircuits branch, the most important DRC issue is no longer “routed board has violations” in the abstract. The immediate blocker is:

- the stamped `leaf_pre_freerouting.kicad_pcb` is already illegal before routing
- the pipeline now explicitly fails with `illegal_pre_route_geometry`
- this means the next debugging target is board/footprint/edge relationship preservation, not router tuning alone

Likely causes:
- edge-coupled connector geometry is not preserved when extracting/stamping a leaf board
- the local synthetic outline is still derived too generically from component extents
- source-board edge relationships for edge-pinned parts are being lost during extraction or stamping

Action:
- preserve source-board edge-relative placement for edge-pinned connectors during leaf extraction/stamping
- validate `leaf_pre_freerouting.kicad_pcb` before FreeRouting and keep failing early when illegal
- only after pre-route legality is fixed, revisit DSN clearance tuning and routed-board DRC interpretation

---

## Render Diagnostics Workflow (new)

A minimal render-diagnostics workflow should now be considered part of subcircuit debugging.

### Purpose

The goal is not presentation polish. The goal is to make these questions answerable quickly:

- is the stamped pre-route leaf board already illegal?
- are footprints outside or misaligned to `Edge.Cuts`?
- did FreeRouting add meaningful copper?
- did routing improve or worsen the board visually?

### Standard artifact location

For each leaf artifact:

- `.experiments/subcircuits/<slug>/renders/`

### Preferred artifact set

Per leaf, generate:

- `pre_route_copper_both.png`
- `pre_route_front_all.png`
- `pre_route_drc.json`
- `pre_route_drc_overlay.png` when coordinate-bearing violations exist
- `routed_copper_both.png`
- `routed_front_all.png`
- `routed_drc.json`
- `routed_drc_overlay.png` when coordinate-bearing violations exist
- `pre_vs_routed_contact_sheet.png`

### Current debugging interpretation

If the pre-route board is already illegal, treat routed-board rejection as secondary. The first question should always be whether the stamped leaf board itself is sane.

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
