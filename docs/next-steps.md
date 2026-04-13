# LLUPS — Next Steps

> Updated: 2026-04-12
> Current best: **91.13** (50-round test_fixes run, R45). 26/26 nets routed, 0 shorts, 49 DRC violations (21 clearance, 2 courtyard, 26 other). Placement score 78.4.

---

## Where Things Stand

- **FreeRouting v1.9.0** is the sole router. Routing time ~10-15 sec/round.
- **Subprocess isolation** for pcbnew calls avoids SwigPyObject stale-object bugs.
- **Stale DRC fixed**: Pipeline now stores DRC results on `ExperimentScore.pipeline_drc`; autoexperiment uses pipeline DRC instead of always re-running `quick_drc()` (which returned stale pre-routing data).
- **Pinned position restoration**: Edge/corner-pinned components (J1, J2, J3, H4, H86) are restored to their target positions as a final solve step, preventing drift from overlap resolution.
- **22 parallel workers** using ProcessPoolExecutor with spawn context.

### Current Scoring Weights

**PlacementScore** (sub-score within placement, 0-100):
| Component | Weight |
|-----------|--------|
| net_distance | 0.25 |
| crossover_score | 0.30 |
| compactness | 0.02 |
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

### Score Ceiling Analysis

Best score 91.13 breakdown:
- **route_completion** (0.50): 100% — 26/26 nets → 50.0/50.0
- **placement** (0.15): 78.4 → 11.8/15.0 — room to improve
- **via_penalty** (0.10): 75.4 (32 vias / 26 nets) → 7.5/10.0
- **containment** (0.05): 100% → 5.0/5.0
- **drc** (0.20): ~76 (49 violations, log-scale) → ~15.2/20.0 — **primary bottleneck**

### Key Findings (from 50-round test_fixes + 500-round experiments)

1. **DRC violations are the score ceiling**: Best round has 49 DRC violations (21 clearance, 2 courtyard, 26 other). These cap the DRC sub-score at ~76%, limiting total to ~91.
2. **Placement score doubled**: Pinned position restoration + overlap priority fixes brought placement from ~39 to 78.4 (2× improvement).
3. **Stale DRC was masking problems**: Previous 500-round best of 93.67 was inflated — DRC penalty wasn't applied because routing was skipped and `quick_drc()` returned pre-routing data.
4. **Score still climbing at R45**: No plateau — contrast with previous experiment that plateaued at R12. The fixes unlocked continued optimization.
5. **Placement failures still occur**: 3/50 rounds (6%) produce placement_score=0 and score=75.0. These are elite/explore rounds that crash or produce degenerate layouts.
6. **FreeRouting crashes**: ~6% of rounds crash with "no SES output (rc=-1)". Gracefully handled but wastes worker slots.
7. **Courtyard overlap is bimodal**: 46% of rounds have 0% overlap score, 20% have 100% — the scoring seems to produce extreme values rather than a gradient.
8. **`edge_compliance` not logged**: The JSONL doesn't record the edge_compliance sub-score, making it hard to verify the weight increase is having effect.

---

## High Priority

### 1. Reduce DRC clearance violations (21 in best round)

Clearance violations are the largest DRC category. Likely causes:
- FreeRouting trace-to-pad or trace-to-trace clearance doesn't match KiCad design rules
- Possible mismatch between DSN export clearance settings and actual board rules
- **Action**: Compare KiCad net class clearance rules with FreeRouting DSN clearance values. Consider increasing `placement_clearance_mm` or adding per-net clearance overrides in the DSN export.

### 2. Investigate the 26 "other" DRC violations

The best round has 26 DRC violations that aren't shorts, unconnected, clearance, or courtyard. These could be:
- Edge clearance violations (tracks too close to board edge)
- Minimum trace width violations
- Drill/hole violations
- **Action**: Run KiCad DRC on `LLUPS_best.kicad_pcb` with verbose output to identify exact violation types. The `quick_drc()` function may be lumping multiple categories into "other".

### 3. Fix courtyard overlap scoring

Courtyard overlap scores are bimodal (0% or 100%) in 66% of rounds with no gradient between. The overlap resolution step may not be working correctly, or the scoring function may be too binary.
- 23/50 rounds score 0% (worst), 10/50 score 100% (best), remaining 17 are in between.
- **Action**: Review `_score_courtyard_overlap()` and `_resolve_overlaps()` to ensure the score reflects actual overlap area rather than just presence/absence. Verify the overlap priority fix for edge-pinned components is functioning.

### 4. Eliminate placement=0 failures

3/50 rounds (6%) produce `placement_score=0` and `score=75.0`. These appear correlated with elite/explore configs that have extreme parameters.
- **Action**: Add parameter bounds validation in `mutate_config_explore()` to prevent degenerate configs. Consider a fallback placement that runs if the primary placement returns score=0.

### 5. Fix `plot_experiments.py` dashboard generation

Dashboard generation fails with `ValueError: setting an array element with a sequence. The requested array has an inhomogeneous shape after 2 dimensions. The detected shape was (7, 11) + inhomogeneous part.`
- **Action**: Fix the numpy array construction in `plot_experiments()` — likely caused by `failed_net_names` lists having variable lengths across rounds.

---

## Medium Priority

### 6. Log edge_compliance sub-score to JSONL

The `edge_compliance` weight was increased from 0.05→0.10 but the sub-score isn't recorded in the JSONL output. Without this, we can't verify the weight change is driving better edge placement.
- **Action**: Add `edge_compliance` field to the JSONL round output in `autoexperiment.py`.

### 7. Reduce FreeRouting crash rate (~6%)

FreeRouting crashes with "no SES output (rc=-1)" in ~6% of rounds, wasting a worker slot for ~60s each time. The crashes correlate with explore/elite configs that produce unusual placements.
- **Action**: Add a pre-routing sanity check (e.g., verify DSN file is well-formed, check board has components within bounds). Consider reducing FreeRouting timeout from 60s to 30s to fail faster on stuck runs.

### 8. Deduplicate force simulation code

The force-directed placement code has ~180 lines duplicated between cluster-level and board-level loops. Extract to a shared `force_step()` function.

---

## Low Priority / Future

### 9. USB-PD header for future revision

The spec mentions routing CC1/CC2 to pads or a header for a future PD controller. Verify the current layout leaves space and traces for this.

### 10. Thermal analysis

Components U2 and U4 are thermal-sensitive. After placement stabilizes, verify thermal pad placement and copper pour connectivity.

### 11. Generate fabrication outputs

Target: 26/26 nets, 0 shorts, <20 total DRC violations.
```bash
kicad-cli pcb export gerbers -o gerber/ LLUPS_best.kicad_pcb
kicad-cli pcb export drill -o gerber/ LLUPS_best.kicad_pcb
```

---

## Completed (reverse chronological)

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
