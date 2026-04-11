# LLUPS — Suggested Next Steps

> Updated: 2026-04-12
> Current state: Placement engine improved — pad containment enforced, net-topology-aware placement, DRC visualization in GIF renders. Best score: 91.33.

---

## Where Things Stand

- **FreeRouting** is the sole router. Routing time is ~15-30 sec/round.
- **Subprocess isolation** for pcbnew calls avoids the SwigPyObject stale-object bug.
- **Blocking dialogs eliminated** via `dialog_confirmation_timeout: 0` in `freerouting.json`.
- **Best score: 91.33** — plateau confirmed; score ceiling driven by DRC violations.

### Score Ceiling Analysis

The best score ~91 is near the theoretical ceiling given current constraints:
- **route_completion** (weight 0.50): Maxed at 100% in 94% of rounds — not the bottleneck
- **board_containment** (weight 0.05): Maxed at 100% — not the bottleneck
- **placement** (weight 0.10): Best ~86, contributes ~8.6/10 — modest room
- **via_penalty** (weight 0.10): Best ~82, contributes ~8.2/10 — modest room
- **DRC** (weight 0.20): ~62-72% effective score due to persistent courtyard/clearance/unconnected violations — **primary bottleneck**

### Key Findings

1. **DRC violations are the score ceiling**: Every round has 70-180 DRC violations (clearance, courtyard overlap, unconnected). These cap the DRC sub-score at ~65-72%, limiting total score to ~91-92.
2. **Catastrophic placement failures eliminated**: Pad containment enforcement and large-first ordering prevent degenerate layouts. Minimum score rose from 68.51 to 84.00 in 30-round experiments.
3. **Explore and Major modes outperform Minor**: Explore and Major consistently beat Minor, suggesting the search benefits from larger perturbations.
4. **Parameter sensitivity is weak**: All parameter-score correlations are low (|r| < 0.3). Edge margin has the strongest effect. Clearance and force constants barely matter at this plateau.
5. **Zero-short routing is achievable**: ~56% of rounds have 0 shorts. Shorts correlate with poor placements, not parameter settings.

---

## Completed

### Pad containment enforcement (2026-04-12)

- Added `_clamp_pads_to_board()` method that shifts components inward when any pad extends beyond the board boundary
- Configurable `pad_inset_margin_mm` (default 0.3mm) in config
- Board containment now 100% in all rounds (was 93.33%)
- Called after overlap resolution in force loop and as final step in `solve()`

### Placement logic improvements (2026-04-12)

- **Net-topology-aware positioning**: components biased 50/50 toward cluster centroid and weighted centroid of already-placed connected neighbors
- **Large-first ordering**: components within clusters sorted by area descending (ICs placed before passives)
- **Connectivity-based cluster sorting**: clusters with highest total connectivity placed first
- **Early IC rotation**: all 4 orientations evaluated at cluster placement time
- **Adaptive convergence**: early exit from force loop when score > 85, displacement < 3.0, stagnant >= 3, iteration > 15
- Placement score improved +4.50 mean (74.17 → 78.66)

### Render visualization improvements (2026-04-12)

- All DRC violation types rendered with distinct colors/shapes: shorts (red X), unconnected (orange circle), clearance (yellow dot), courtyard (magenta rectangle)
- Sub-score breakdown line: `DRC | Place | Route | Via` shown below main score
- Increased font size and info band opacity (85%)

### Earlier completed items

| Feature | Detail |
|---------|--------|
| Type-aware placement zones | `component_zones` config: connectors→edges, batteries→center-bottom, mounting holes→corners |
| Signal flow ordering | `signal_flow_order` biases IC placement left→right along X-axis |
| Decoupling cap proximity | Caps in `ic_groups` placed at 1.5× clearance radius from parent IC |
| Scatter mode | `scatter_mode="random"` for uniform random initial placement |
| Temperature reheat | Force sim reheats at 50% of iterations to escape local minima |
| Wider MAJOR mutations | Uniform sampling instead of Gaussian for aggressive exploration |
| Placement validation gate | Skips routing if placement score < `min_placement_score` |
| Courtyard padding | Configurable `courtyard_padding_mm` in overlap scoring |
| Scoring rebalanced | DRC weight 0.10→0.20, route_completion 0.55→0.50, containment 0.10→0.05 |
| Elite config persistence | Top-5 configs saved cross-run; seeded into early batches |
| Plateau threshold | Reduced 5→3 for faster MAJOR trigger |
| Explore fraction | Increased 20%→33% of batch |
| FreeRouting timeout | Reduced 120→60s |
| Config separation | `DEFAULT_CONFIG` (generic) + `LLUPS_CONFIG` (project-specific) |
| Guard against placement failures | Placement validation gate + courtyard padding prevents degenerate layouts |
| Escape the local optimum | Explore fraction, MAJOR mutations, scatter mode, reheat, elite archive |
| Power net routing (partial) | `"GND"` added to `freerouting_ignore_nets` |

---

## High Priority

### 1. Fix DRC violations (primary score bottleneck)

DRC violations are the #1 barrier to score improvement. Partially addressed so far:
- Increased `placement_clearance_mm` 2.0→2.5, added `courtyard_padding_mm` (0.5mm)
- DRC scoring weight increased 0.10→0.20
- `"GND"` added to `freerouting_ignore_nets` for zone routing

Remaining work:
- **Unconnected items** (17-28/round): Investigate whether additional copper zones/fills would resolve remaining unconnected pads. Consider adding `VBAT` and `VBUS` to `freerouting_ignore_nets`.
- **Courtyard overlaps**: Monitor whether increased clearance resolves these, or if footprint courtyard modifications are needed.
- **Clearance violations** (24-34/round): May require per-net clearance rules or trace width adjustments.

### 2. Scoring formula tuning

The pad containment enforcement (80/20 pad/body weight in `_score_board_containment`) changed the scoring dynamics. The overall score mean dipped slightly (88.82 → 87.25) despite clear quality improvements. Consider:
- Re-evaluating sub-score weights to reflect actual quality better
- Possibly reducing containment weight further since it's now always 100%
- Adding a placement connectivity sub-score to reward net-topology-aware layouts

---

## Medium Priority

### 3. Deduplicate force simulation in placement.py

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
