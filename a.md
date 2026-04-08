# Autorouter Improvement Plan

## Biggest Issues (High Impact)

### 1. Duplicated `_build_grid` and `_path_to_traces` logic (~120 lines of duplication)

`RoutingSolver._build_grid()` (router.py:411-492) and `RipUpRerouter._build_grid()` (conflict.py:124-201) are nearly identical — same pad escape corridor logic, same obstacle marking, same COMPONENT_COST constant. `_path_to_traces` is also copy-pasted verbatim in both files. Every bug fix has to be applied twice.

**Fix**: Extract `GridBuilder` class with a single `build(traces, vias, exclude_net)` method. Extract `_path_to_traces` as a standalone function (it's pure, needs no `self`). Both router and RRR call it.

**Files**: `router.py`, `conflict.py`

---

### 2. No incremental grid update in RRR — full rebuild every iteration

`RipUpRerouter.solve()` rebuilds the entire routing grid from scratch on every iteration (conflict.py:63, :93). For a 90x58mm board at 0.5mm resolution that's ~167K cells × component scan × trace scan per retry. With up to 50 iterations this dominates runtime.

**Fix**: Build grid once in `RoutingSolver._build_grid()`, expose it. In RRR, instead of rebuilding: mark removed traces back to 0, mark new traces as obstacles. Use a stack for delta tracking so rollback is O(1) per segment.

**Tradeoff**: More complex grid state management. For the current board size the full rebuild is ~200ms, so this matters more on larger boards. Implement with a simple dirty-flag approach: track which cells changed, restore on rollback.

---

### 3. Greedy MST routing — wrong topology for congested areas

Both routing passes use geometric MST (Prim's) to connect multi-pad nets (router.py:531). MST minimizes total wire length but knows nothing about obstacles. A net with pads A, B, C might route A→B first (which blocks C), when A→C→B would succeed.

**Fix**: After MST fails for a net, retry with different MST root / Steiner-aware ordering. Specifically:
- Try MST from each pad as root (k variants, where k = #pads in net)
- Pick the variant that routes the most edges successfully
- Only falls back to "net failed" if all variants fail

This is simple, bounded, and catches the common "wrong first edge" failure mode without a full Steiner tree implementation.

**Files**: `router.py:_route_net`, `conflict.py:_try_route`

---

### 4. Victim selection in RRR is too simple

`_find_victims` (conflict.py:265-308) picks victims purely by "shortest trace in bounding box." It doesn't account for:
- How many times a victim was already ripped (thrashing)
- Whether the victim itself has alternate layer choices that would free space
- Victims that are part of a cycle (ripping A to route B, then ripping B to route A)

**Fix**: Add a `rip_count` factor to the victim score so nets that have been ripped many times become progressively less likely to be ripped again. Also add a cycle detection: if a net's re-route would block the same nets it previously blocked, don't rip them.

---

### 5. `skip_gnd_routing` is hard-coded, no GND strategy at all

GND is skipped entirely (`skip_gnd_routing: true`). For 2-layer boards this is reasonable (fill zones for GND), but the autorouter never reserves GND pad access zones or validates that pads are reachable by a copper pour later.

**Fix**: Before routing, mark GND pad cells + escape corridors on both layers as passable (they already are), but also add a pre-check that after all signal routing, no GND pad is completely surrounded by high-cost trace. Add a simple flood-fill connectivity check for GND pads.

---

## Medium Impact

### 6. Diagonal routing produces KiCad-hostile geometry

The router uses 8-connected A* (diagonals at 45°) which is good for manufacturability, but the `_path_to_traces` conversion is fragile: it detects direction changes by comparing consecutive deltas. When the path has mixed cardinal + diagonal segments, the segmentation can produce very short "micro-segments" that KiCad chokes on in DRC.

**Fix**: Post-process trace segments: merge segments shorter than a threshold (e.g., 2x grid resolution) into adjacent segments, and snap segment endpoints to 45° snaps (grid-snapped angles: 0°, 45°, 90°).

### 7. No net ordering learning from failures

Current ordering is static: power nets first, then signal nets by connection count (router.py:494-509). When a net fails and gets ripped+re-routed, the system never remembers that this net is hard-to-route and should go earlier next time.

**Fix**: After initial pass, reorder remaining unroutable nets to start of queue for the RRR pass. Track which nets consistently fail across experiments and give them higher priority in future runs.

### 8. Scoring disconnect between `ExperimentScore` and placement scoring

`ExperimentScore` weights (0.50 route, 0.20 trace, 0.10 via, 0.20 placement) differ from the individual `PlacementScore` weights. The autoexperiment loop can optimize for the experiment score while making the actual placement quality worse in ways that matter.

**Fix**: Unify the scoring. Make `ExperimentScore.total` be a direct weighted sum of named sub-scores, not two separate scoring systems bolted together.

---

## Low Impact / Nice-to-Have

### 9. Pure Python fallback is slow and untested regularly

The numpy-free fallback path in `AStarRouter.find_path` (router.py:267-324) exists but is ~2x slower and may diverge in behavior from the numpy path.

**Fix**: Skip. Numpy is available everywhere the experiments run. If needed later, make numpy a hard dependency.

### 10. `grid_resolution_mm` set twice (config.py says 0.5, router.py default is 0.25)

`config.py:5` sets `grid_resolution_mm: 0.5` but `router.py:363` defaults to `0.25`. Similar mismatch for `signal_width_mm` (0.15 vs 0.25) and `power_width_mm` (0.5 vs 1.0). The config wins but this is confusing.

**Fix**: Remove hardcoded defaults from `RoutingSolver.__init__` and require config dict to always provide them, or make the defaults match `DEFAULT_CONFIG` exactly.

### 11. RRR has no absolute timeout

The RRR loop is bounded by `max_iterations` (50) and `stagnation_limit` (5), but on a pathological board with many interleaved failures, 50 iterations of full-grid rebuild could take >30 seconds.

**Fix**: Add a wall-clock timeout (e.g., 60s) that breaks the loop if exceeded.

---

## Priority Order

| # | Impact | Effort | Description |
|---|--------|--------|-------------|
| 1 | High | Low | Deduplicate `_build_grid` and `_path_to_traces` |
| 3 | High | Low | Retry MST from different roots on failure |
| 2 | High | Medium | Incremental grid deltas in RRR |
| 4 | Medium | Low | Rip-count-aware victim selection |
| 5 | Medium | Medium | GND pad reachability pre-check |
| 10 | Low | Trivial | Align config defaults |
| 11 | Low | Low | RRR wall-clock timeout |
| 8 | Medium | Medium | Unify scoring systems |
| 6 | Medium | Medium | Post-process trace segments for KiCad compatibility |
| 7 | Low | Medium | Net ordering learning from failures |

## Recommendation

Start with **#1 (dedup)** and **#3 (MST retry)** — they're high-impact, low-risk, and simplify the code simultaneously. #3 directly addresses real routing failures without adding complexity. Together they touch ~200 lines but make the codebase significantly easier to reason about.
