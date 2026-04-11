# LLUPS — Suggested Next Steps

> Updated: 2026-04-11
> Current state: Critical placement/rendering bugs fixed — placements now actually apply to PCB, connectors snap to edges, GIF shows per-round layouts

---

## Where Things Stand

- **FreeRouting** is the sole router. Routing time is ~15-30 sec/round.
- **Subprocess isolation** for pcbnew calls avoids the SwigPyObject stale-object bug.
- **Blocking dialogs eliminated** via `dialog_confirmation_timeout: 0` in `freerouting.json`.
- **Scoring fixed**: `ExperimentScore.compute()` uses passed weights; `board_containment` no longer zeroes all scores.
- 28-round verification experiment completed after bug fixes.
- **Best score: 91.12** — plateau confirmed, but search space now explored properly.

### Bug Fixes (2026-04-11)

| Fix | File | Detail |
|-----|------|--------|
| Locked components never written | `adapter.py` | `apply_placement` checked `comp.locked` (solver flag) instead of `fp.IsLocked()` (KiCad flag) — connectors/batteries/mounting holes positions were never saved to PCB |
| Connector pad positions stale | `placement.py` | `_pin_edge_components` didn't call `_update_pad_positions()` when snapping connectors to edges — pads stayed at original positions, corrupting net distance calculations |
| GIF frames all identical | `autoexperiment.py` | Frames always rendered `best.kicad_pcb` instead of each round's `work_pcb` — now shows actual per-round layout |

### Verification Experiment (28 rounds, post-fix)

| Metric | Before fix | After fix |
|--------|-----------|-----------|
| Explore avg score | 65.91 | **85.30** (+19 pts) |
| Explore timeouts | 5/5 (100%) | **1/10** (10%) |
| Placement scores | All 0.0 (explore) | 64-84 across modes |
| GIF frames | All identical | **All unique** (29 distinct layouts) |
| Minor avg | 86.71 | **88.12** |

### Recent Improvements (2026-04-12)

| Feature | Status | Detail |
|---------|--------|--------|
| Type-aware placement zones | **Done** | `component_zones` config: connectors→edges, batteries→center-bottom, mounting holes→corners |
| Signal flow ordering | **Done** | `signal_flow_order` biases IC placement left→right along X-axis |
| Decoupling cap proximity | **Done** | Caps in `ic_groups` placed at 1.5× clearance radius from parent IC |
| Scatter mode | **Done** | `scatter_mode="random"` for uniform random initial placement |
| Temperature reheat | **Done** | Force sim reheats at 50% of iterations to escape local minima |
| Wider MAJOR mutations | **Done** | Uniform sampling instead of Gaussian for aggressive exploration |
| Placement validation gate | **Done** | Skips routing if placement score < `min_placement_score` |
| Courtyard padding | **Done** | Configurable `courtyard_padding_mm` in overlap scoring |
| Scoring rebalanced | **Done** | DRC weight 0.10→0.20, route_completion 0.55→0.50, containment 0.10→0.05 |
| Elite config persistence | **Done** | Top-5 configs saved cross-run; seeded into early batches |
| Plateau threshold | **Done** | Reduced 5→3 for faster MAJOR trigger |
| Explore fraction | **Done** | Increased 20%→33% of batch |
| FreeRouting timeout | **Done** | Reduced 120→60s |
| Config separation | **Done** | `DEFAULT_CONFIG` (generic) + `LLUPS_CONFIG` (project-specific) |

### Latest 50-Round Experiment Summary (2026-04-11)

| Metric | Value |
|--------|-------|
| Rounds | 50 (0 kept) |
| Score range | 64.76 – 90.37 (best remain 91.12) |
| Score mean / median | 87.04 / 88.24 |
| Nets routed | 26/26 in 47/50 rounds (3 total failures) |
| DRC shorts | 0 in 28/50 rounds; up to 12 in worst case |
| DRC unconnected | 18–91 per round (avg 27.1) |
| DRC clearance | 24–34 per round (always present) |
| DRC courtyard | 1–9 per round (always present) |
| Placement score | 61.0–83.2 (avg 71.2, 3 rounds scored 0 / total failure) |
| Via score | 63.8–82.3 (avg 70.4) |

### Score Ceiling Analysis

The best score 91.12 is near the theoretical ceiling given current constraints:
- **route_completion** (weight 0.55): Maxed at 100% in 94% of rounds — not the bottleneck
- **board_containment** (weight 0.10): Maxed at 100% — not the bottleneck
- **placement** (weight 0.10): Best ~83, contributes ~8.3/10 — modest room
- **via_penalty** (weight 0.10): Best ~82, contributes ~8.2/10 — modest room
- **DRC** (weight 0.15): ~62-70% effective score due to persistent courtyard/clearance/unconnected violations — **primary bottleneck**

### Key Findings

1. **DRC violations are the score ceiling**: Every round has 77-179 DRC violations (clearance, courtyard overlap, unconnected). These cap the DRC sub-score at ~65%, limiting total score to ~91-92. Placement and via improvements alone cannot push past 93.
2. **Placement failures are catastrophic**: 3/50 rounds had placement_score=0 with routing completely failing (0 nets routed, 89-91 unconnected). These were all MINOR mutations — the placement engine occasionally produces degenerate layouts.
3. **Explore and Major modes outperform Minor**: Explore (avg 88.37) and Major (avg 88.38) consistently beat Minor (avg 86.22), suggesting the search is trapped in a local optimum and needs larger perturbations.
4. **Parameter sensitivity is weak**: All parameter-score correlations are low (|r| < 0.3). Edge margin has the strongest effect (r=-0.298), suggesting tighter edge margins slightly help. Clearance and force constants barely matter at this plateau.
5. **Zero-short routing is achievable**: 28/50 rounds had 0 shorts — the router handles the 26-net board well when placement is reasonable. Shorts correlate with poor placements, not parameter settings.

---

## High Priority

### 1. Ensure all footprint pads are inside PCB edge cuts border

Currently some components (especially connectors and edge-placed parts) can have pads extending beyond the board edge cuts. The placement engine should validate that all electrical pads fall within the Edge.Cuts boundary, with a configurable inset margin. Pads outside the board edge are unfabricatable and cause DRC violations.

### 2. Improve placement logic

- Smarter initial placement using netlist topology (place tightly-connected components close together from the start, not just via force simulation)
- Better handling of component rotation — try all 4 orientations during initial placement, not just during refinement
- Constrain large components (ICs, battery holders) first, then fill in passives around them
- Reduce force simulation iterations when placement is already good (adaptive convergence)

### 3. Improve render visualization clarity and contrast

- Increase trace/pad contrast against the board background
- Use distinct colors for front/back copper layers
- Highlight DRC violations with small red arrows or circles at violation coordinates
- Add component reference labels to the render for easier identification
- Improve text overlay readability (background boxes behind score text)

### 4. ~~Fix DRC violations (primary score bottleneck)~~ — Partially addressed

DRC violations are the #1 barrier to score improvement. Actions taken:
- **Clearance violations**: Increased `placement_clearance_mm` 2.0→2.5, added `courtyard_padding_mm` (0.5mm) — should reduce courtyard and clearance violations.
- **DRC scoring weight**: Increased from 0.10→0.20 to drive optimization toward fewer violations.
- **Unconnected items**: Added `"GND"` to `freerouting_ignore_nets` so power nets are zone-routed instead of traced.

Remaining:
- **Unconnected items** (18-28/round, excluding failures): Investigate whether additional copper zones/fills would resolve remaining unconnected pads.
- **Courtyard overlaps**: Monitor whether increased clearance resolves these, or if footprint courtyard modifications are needed.

### 2. ~~Guard against placement failures~~ — Done

- Added placement validation gate: routing is skipped if `placement_score < min_placement_score` (default 30), returning zeroed `ExperimentScore` with `skipped_routing=True` flag.
- Added `courtyard_padding_mm` to overlap scoring to prevent degenerate overlap layouts.

### 3. ~~Power net routing strategy~~ — Partially done

Added `"GND"` to `freerouting_ignore_nets` by default. Consider also adding `VBAT` and `VBUS` after testing impact.

### 4. ~~Escape the local optimum~~ — Done

Multiple diversity mechanisms implemented:
- **Explore fraction increased** 20%→33% of batch
- **Plateau threshold reduced** 5→3 for faster MAJOR triggers
- **Wider MAJOR mutations**: Uniform sampling instead of Gaussian
- **Scatter mode**: Random uniform placement for explore candidates
- **Temperature reheat**: Force sim reheats at 50% of iterations
- **Randomize group layout**: Variable cluster radii per group
- **Elite archive**: Cross-run learning seeds 30% of early batches from top-5 historical configs

---

## Medium Priority

### 5. ~~Tune `freerouting_max_passes`~~ — Done

Reduced `freerouting_timeout_s` from 120→60. FreeRouting typically converges in 15-30s for this board.

### 6. Deduplicate force simulation in placement.py

The force-directed placement code has ~180 lines duplicated between cluster-level and board-level loops. Extract to a single `force_step()` function.

### 7. ~~Elite config persistence~~ — Done

Top-5 configs saved to `.experiments/elite_configs.json` (deduplicated by seed). 30% of early batches are seeded from the archive via `load_elite_archive()`.

---

## Low Priority / Future

### 8. USB-PD header for future revision

The spec mentions routing CC1/CC2 to pads or a header for a future PD controller. Verify the current layout leaves space and traces for this.

### 9. Thermal analysis

Components U2 and U4 are flagged as thermal-sensitive. After placement stabilizes, verify thermal pad placement and copper pour connectivity.

### 10. Generate fabrication outputs

Once the board reaches a satisfactory routing score (target: 26/26 nets, 0 DRC shorts, <20 total DRC):
```bash
kicad-cli pcb export gerbers -o gerber/ LLUPS.kicad_pcb
kicad-cli pcb export drill -o gerber/ LLUPS.kicad_pcb
```

---

## Known Technical Debt

| Item | Location | Notes |
|------|----------|-------|
| Placement engine can produce degenerate layouts | `adapter.py` | 3/50 rounds had placement=0, 0 nets routed |
| FreeRouting ignores `max_passes` | `freerouting_runner.py` | v1.9.0; relies on natural convergence or timeout |
| pcbnew SWIG memory leak warnings | `_run_pcbnew_script()` | Harmless stderr noise from `PCB_TRACK *` / `PCB_VIA *` destructors |
| `routing_ms` includes pcbnew subprocess overhead | `pipeline.py` | Timing includes DSN export + SES import subprocesses, not just FreeRouting |
| Weak parameter sensitivity at plateau | `autoexperiment.py` | All param-score correlations |r| < 0.3 — minor/major mutations are not finding improvements |
