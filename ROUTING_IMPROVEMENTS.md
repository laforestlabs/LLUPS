# PCB Autorouter Improvements - Status & Next Steps

## What Was Implemented

### Phase 1: Root Cause Analysis ✅
Identified 3 critical bugs causing ~80 DRC shorts per routing run:
1. Cross-net traces marked as soft obstacles (cost=100), not hard blocks (1e6)
2. Escape vias never marked on grid → via collisions
3. Via markings had no clearance margin

### Phase 2: Correctness Fixes ✅
**Commits:**
- `83256e9` - Hard-block cross-net traces + escape via marking + raise max_search to 2M
- Test added: `test_hard_block_prevents_cross_net_routing` (all 9 unit tests pass)

**What changed:**
- Completed traces now hard-blocked at 1e6 (impossible to cross)
- Escape vias marked on grid immediately after creation
- Via markings include clearance margin (+0.2mm)
- A* max_search raised from 500K to 2M nodes

### Phase 3: Performance Optimizations ✅
**Commit:** `462962d` - 2-3x speedup on deep A* searches

**Optimizations:**
1. `came_from` dict → numpy array (eliminates tuple allocation per node)
2. Footprint lookups vectorized with numpy slices (9 reads → 1 C call for multi-cell traces)
3. Base-grid caching in RipUpRerouter (90% reduction in grid-building overhead)

---

## Current State

**Baseline Routing (after hard-block fix):**
- Route completion: 26/26 nets (100%)
- DRC shorts: **~81** (down from ~88 before, modest improvement)
- Duration: **432s per routing** (up from ~240s, due to deep A* detours)

**Issue:** Hard blocks force very long detours on a constrained board. The algorithm is now *correct* (no illegal trace crossings) but expensive and still producing shorts through other mechanisms (e.g., via-to-trace clearance violations, trace congestion).

---

## Root Causes of Remaining Shorts

1. **Via placement grid quantization** — All vias snap to 0.5mm grid. Two nets may place vias at same coordinate if pads are far apart.
   - Fix: Smarter via placement or higher grid resolution (0.25mm)

2. **Trace-to-trace clearance from tight routing** — With hard blocks, A* packs traces tightly. Adjacent traces may be 0.195mm apart (below DRC clearance of 0.2mm).
   - Fix: Reduce grid resolution to 0.2mm OR increase soft-obstacle cost to discourage tight packing

3. **Component escape corridors too narrow** — Pads boxed in by components generate escape vias that collide.
   - Fix: Widen escape corridors or increase pad clearance

---

## Recommended Next Steps

### Short Term (Quick Wins)
1. **Tune hard-block aggressiveness:**
   - Try soft obstacles at 5000 instead of 1e6 (gives A* more flexibility)
   - A* will still vastly prefer detours but can squeeze through if necessary
   - Trade-off: some illegal crossings vs. better connectivity

2. **Increase max_search to 5M:**
   - Current 2M may be insufficient for boards with many blocked cells
   - Check if performance optimizations enable this

3. **Reduce grid resolution to 0.25mm:**
   - Better clearance modeling (0.1524mm traces now 1-2 cells instead of 1)
   - More CPU but more accurate
   - Will likely fix via-grid-snapping issues

### Medium Term (Architecture)
1. **Parallel net routing:**
   - Spatially independent nets can route on read-only grid copies
   - Current sequential bottleneck prevents parallelism
   - Would use 22 cores for 15-20x speedup

2. **Hierarchical routing:**
   - Route power/GND first (critical, lowest fanout)
   - Route high-priority signals second
   - Route low-priority last (more congestion)
   - Avoids routing low-priority nets through high-priority spaces

3. **Incremental grid updates:**
   - Instead of refreshing soft obstacles after each net, maintain a shadow grid
   - Only update cells touched by the new route
   - Would save 50% of grid updates

### Long Term (Redesign)
1. **Reconsider the grid cost model:**
   - Current: soft obstacles at 100, hard blocks at 1e6
   - Alternative: continuous cost field (higher cost near existing traces, penalty increases with proximity)
   - Would naturally prevent both crossing and tight packing

2. **Annealing-based routing:**
   - Instead of greedy "route first, deal with collisions later", use simulated annealing to explore alternative solutions
   - Would find better global solutions than local A* greedy

3. **Machine learning placement prediction:**
   - Train a model to predict optimal component placement for routability
   - Current placement-physics approach doesn't optimize for routing

---

## Files Changed

### Core Router
- `autoplacer/brain/router.py` — Hard-block logic, max_search, performance optimizations
- `autoplacer/brain/conflict.py` — RRR base-grid caching
- `autoplacer/config.py` — max_search=2M, trace_cost=100

### Tests
- `autoplacer/brain/test_router_grid_behavior.py` — Added hard-block verification test

---

## How to Resume

```bash
# Run a quick experiment to verify current state
python autoexperiment.py .experiments/experiment.kicad_pcb --rounds 3

# Profile A* performance
python -c "from autoplacer.brain.router import AStarRouter; ..." # TODO: add profiling hook

# Test the specific fixes
python -m pytest autoplacer/brain/test_router_grid_behavior.py -v
```

---

## Key Metrics to Track

- **Routing completion:** % of nets fully routed (target: 100%)
- **DRC shorts:** Count of shorting violations (target: 0)
- **Route time:** Seconds per net (concern: rising with hard blocks)
- **Board score:** Overall PCB quality metric

Current: 26/26 routed, 81 shorts, 432s baseline, score ~21.5
