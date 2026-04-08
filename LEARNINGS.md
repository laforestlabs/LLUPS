# Session Learnings: Shorts Reduction & Grid Resolution

## Key Findings

### 1. **Grid resolution is the bottleneck**
- **0.5mm**: trace+clearance (0.327mm) rounds to 1 cell. Router can't distinguish "fits" from "doesn't fit". 
  - Result: Either cheats (routes through other nets = 24 shorts) or fails (8/26 routed)
- **0.25mm**: trace+clearance ≈ 1.3 cells. Router can thread between existing routes honestly.
  - Result: 21/26 routed, 32 shorts, no cheating
- **Takeaway**: Finer grids > complex routing algorithms for congested 2-layer boards

### 2. **Hard-blocking is correct but exposes routing limits**
- RRR marking other nets' traces as HARD_BLOCK (1e6) instead of soft (100) prevents cheating
- Previously got "26/26 routed" by routing through other nets (hidden shorts)
- Hard-blocking revealed: placement + routing grid are the real constraints, not algorithm cleverness
- **Takeaway**: Honest metrics expose real problems; don't optimize for illusions

### 3. **Over-engineering makes things worse**
- Deleted: drc_sweep.py (complex nudge logic, didn't help)
- Reverted: mark_segment point-to-segment distance (bbox was safer)
- **Takeaway**: Start simple, add complexity only when measured to help

### 4. **Scoring weights drive optimization direction**
- Changed route_completion weight from 50% → 65%
- Bumped crossover_score in placement from 20% → 30%
- This alone improved convergence (fewer failed nets)
- **Takeaway**: Weights are hyperparameters; tune them like any other search lever

### 5. **Placement clearance was too conservative**
- 2.5mm gap between component bboxes meant parts too far apart
- Reduced to 1.5mm → components closer → shorter trace patches → more routing room
- **Takeaway**: Placement clearance ≠ routing clearance; tighter placement helps routing

## Current State
- **Best**: 27.5 score, 21/26 nets, 32 shorts, 0.25mm grid
- **Trade-off**: 5x slower than 0.5mm but honest routing worth it
- Shorts are DRC-hard (real clearance violations, not routing artifacts)

## Ideas to Explore Next

### High Priority
1. **Per-net adaptive grid resolution**: Use 0.25mm near congestion, 0.5mm elsewhere (speed + accuracy)
2. **Escape via optimization**: Place escape vias more intelligently (avoid collision clusters)
3. **Net routing order**: Try power-first + MST-based ordering (currently alphabetic)

### Medium Priority
1. **Thermal aware placement**: Pin high-current traces (boost output) for direct routing, not forced detours
2. **Clearance matrix by net pair**: Some nets can coexist in tight space (power/signal separation)

### Lower Priority (diminishing returns)
1. Simulated annealing RRR (current greedy rip selection is good enough)
2. ML placement seeding (genetic algorithm already explores well)

## Code Quality
- Session reduced -287 lines (drc_sweep.py deleted, mark_segment simplified)
- Simpler is better: hard-blocking + finer grid beats clever algorithms
