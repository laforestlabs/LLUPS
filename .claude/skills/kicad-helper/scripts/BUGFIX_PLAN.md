# Autoexperiment Bugfix & Improvement Plan

Date: 2026-04-09
Context: 20-round autoexperiment produced 0 kept rounds. Every worker process crashes in RRR phase. Baseline score stuck at 0.0.

---

## Bug 1: RRR `PathResult` type mismatch (CRITICAL)

**File:** `.claude/skills/kicad-helper/scripts/autoplacer/brain/conflict.py`
**Lines:** 230–252 (inside `_try_route` method)
**Severity:** Crashes every pipeline run that triggers RRR

### Problem

`router.find_path()` returns a `PathResult(path, expansions, cost)` NamedTuple (see `types.py:151–155`). The code in `_try_route` assigns the full `PathResult` to a variable called `path`, then:

1. Checks `if path is None:` — always False because `PathResult` is never `None`
2. Passes the `PathResult` object (not the inner `.path` list) to `path_to_traces()`
3. `path_to_traces()` iterates expecting `GridCell` objects → hits `curr.layer` on the `int` field `expansions` → `AttributeError: 'int' object has no attribute 'layer'`

### Reference (correct pattern)

`router.py:_route_net()` (lines 419–468) does this correctly:
```python
pr = router.find_path(start, end, width_cells, self.max_search)
if pr.path is not None:
    ...
segs, path_vias = path_to_traces(pr.path, grid, ...)
```

### Fix

Replace the `_try_route` method's path-handling block (conflict.py lines ~230–252). Change all occurrences of the variable `path` to `pr` and access `.path` for the cell list:

**Before** (lines 230–252):
```python
            start = grid.to_cell(a_pos, a_layer)
            end = grid.to_cell(b_pos, b_layer)
            path = router.find_path(start, end, width_cells)

            if path is None:
                for try_layer in [Layer.FRONT, Layer.BACK]:
                    alt_s = GridCell(start.x, start.y, try_layer)
                    alt_e = GridCell(end.x, end.y, try_layer)
                    path = router.find_path(alt_s, alt_e, width_cells)
                    if path:
                        if try_layer != a_layer:
                            vias.append(Via(a_pos, net.name,
                                            self.via_drill, self.via_size))
                        if try_layer != b_layer:
                            vias.append(Via(b_pos, net.name,
                                            self.via_drill, self.via_size))
                        break

            if path is None:
                all_ok = False
                continue

            segs, pvias = path_to_traces(
                path, grid, net.name, width, self.via_drill, self.via_size)
```

**After:**
```python
            start = grid.to_cell(a_pos, a_layer)
            end = grid.to_cell(b_pos, b_layer)
            pr = router.find_path(start, end, width_cells)

            if pr.path is None:
                for try_layer in [Layer.FRONT, Layer.BACK]:
                    alt_s = GridCell(start.x, start.y, try_layer)
                    alt_e = GridCell(end.x, end.y, try_layer)
                    pr = router.find_path(alt_s, alt_e, width_cells)
                    if pr.path:
                        if try_layer != a_layer:
                            vias.append(Via(a_pos, net.name,
                                            self.via_drill, self.via_size))
                        if try_layer != b_layer:
                            vias.append(Via(b_pos, net.name,
                                            self.via_drill, self.via_size))
                        break

            if pr.path is None:
                all_ok = False
                continue

            segs, pvias = path_to_traces(
                pr.path, grid, net.name, width, self.via_drill, self.via_size)
```

Also add `PathResult` to the imports at the top of conflict.py (line 11–13):
```python
from .types import (
    Point, Layer, BoardState, Net, TraceSegment, Via, GridCell, RoutingResult,
    RRRIteration, RRRSummary, PathResult
)
```

### Test

```bash
# In-process test (no multiprocessing complications):
cd /home/jason/Documents/LLUPS
python3 -c "
import sys, os, shutil
sys.path.insert(0, os.path.abspath('.claude/skills/kicad-helper/scripts'))
shutil.copy2('LLUPS.kicad_pcb', '/tmp/bugtest.kicad_pcb')
from autoplacer.pipeline import FullPipeline
from autoplacer.config import DEFAULT_CONFIG
pipeline = FullPipeline()
result = pipeline.run('/tmp/bugtest.kicad_pcb', '/tmp/bugtest.kicad_pcb',
                      config=dict(DEFAULT_CONFIG), seed=0)
es = result['experiment_score']
print(f'Score: {es.total:.2f}')
print(f'Routed: {es.routed_nets}/{es.total_nets}')
print(f'Failed: {es.failed_nets}')
print(f'Placement: {es.placement.total:.2f}')
print(f'Containment: {es.placement.board_containment:.2f}')
" 2>&1 | grep -E '(Score:|Routed:|Failed:|Placement:|Containment:|Error|Traceback)'
```

**Pass criteria:**
- No `AttributeError` or traceback
- `Routed:` shows >0 nets (was 0/0 before)
- `Score:` is non-negative (was 0.0 or -1.0 before)

---

## Bug 2: `board_containment` penalty too harsh — zeroes all scores

**File:** `.claude/skills/kicad-helper/scripts/autoplacer/brain/placement.py`
**Lines:** 186–220 (`_score_board_containment` method)

### Problem

The containment penalty is `pads_outside * 10.0 + bodies_outside * 3.0`, clamped to `[0, 100]`. Just 10 out-of-board pads → penalty of 100 → containment = 0.0. Then in `ExperimentScore.compute()` (types.py line 347): `self.total = raw * containment_frac` → all scores become 0.

This is too aggressive for an optimization loop where early placements naturally have components partially outside.

### Fix

Change the penalty to proportional (percentage-based) rather than absolute counts.

**Before** (placement.py lines 216–219):
```python
        if total_pads == 0 and total_bodies == 0:
            return 100.0

        penalty = pads_outside * 10.0 + bodies_outside * 3.0
        return max(0.0, min(100.0, 100.0 - penalty))
```

**After:**
```python
        if total_pads == 0 and total_bodies == 0:
            return 100.0

        pad_frac = pads_outside / max(1, total_pads)
        body_frac = bodies_outside / max(1, total_bodies)
        # Weighted: 60% pad containment, 40% body containment
        score = 100.0 * (1.0 - 0.6 * pad_frac - 0.4 * body_frac)
        return max(0.0, min(100.0, score))
```

This changes the penalty from "10+ pads out → score 0" to a gradual curve: 50% of pads out → containment ~70, all pads out → containment 0. The optimizer can now distinguish between "slightly out" and "completely out."

### Also fix: Multiplicative containment kill in `ExperimentScore.compute()`

**File:** `.claude/skills/kicad-helper/scripts/autoplacer/brain/types.py`
**Lines:** 346–348

The `raw * containment_frac` multiplier is too aggressive — it zeroes everything when containment is 0. Change to an additive blend:

**Before** (types.py lines 340–348):
```python
        raw = (
            0.15 * self.placement.total +   # placement quality
            0.65 * route_pct +              # routing completion (dominant)
            0.10 * via_score +              # fewer vias
            0.10 * 50.0                     # reserved / neutral
        )
        # Hard penalty: pads outside board
        containment_frac = self.placement.board_containment / 100.0
        self.total = raw * containment_frac
```

**After:**
```python
        raw = (
            0.15 * self.placement.total +   # placement quality
            0.65 * route_pct +              # routing completion (dominant)
            0.10 * via_score +              # fewer vias
            0.10 * self.placement.board_containment  # containment as a scored dimension
        )
        self.total = raw
```

This makes containment one dimension of the score (10% weight) rather than a gating multiplier that can zero everything.

### Test

After both Bug 1 and Bug 2 are fixed, repeat the in-process test from Bug 1. Additionally:

```python
# Unit test for containment scoring
from autoplacer.brain.types import ExperimentScore, PlacementScore
es = ExperimentScore(routed_nets=10, total_nets=20, failed_nets=10,
                     trace_count=50, via_count=10)
es.placement = PlacementScore(total=50.0, board_containment=30.0)
es.compute()
print(f'Score with 30% containment: {es.total:.2f}')
assert es.total > 0, "Score should be positive even with low containment"
```

**Pass criteria:**
- Score > 0 even when containment is low
- Optimizer can differentiate between placements with varying containment

---

## Bug 3: `ExperimentScore.compute()` ignores `weights` parameter

**File:** `.claude/skills/kicad-helper/scripts/autoplacer/brain/types.py`
**Lines:** 321–348 (`compute` method)

### Problem

The method signature accepts `weights: Optional[dict] = None` but uses hardcoded `0.15/0.65/0.10/0.10`. The `program.md` score_weights are parsed by `autoexperiment.py` and passed via `exp_score.compute(score_weights)` but have no effect.

### Fix

Use the `weights` parameter when provided. The keys from program.md are `placement`, `route_completion`, `trace_efficiency`, `via_penalty`.

**Before** (types.py lines 321–348):
```python
    def compute(self, weights: Optional[dict] = None) -> float:
        """Compute unified score. Route completion dominates, then placement."""
        # Route completion: most important — must get all nets routed
        if self.total_nets > 0:
            route_pct = ((self.total_nets - self.failed_nets)
                         / self.total_nets) * 100
        else:
            route_pct = 100.0

        # Via penalty: fewer vias per routed net = better
        if self.routed_nets > 0:
            vias_per_net = self.via_count / self.routed_nets
            via_score = max(0, min(100, 100 - vias_per_net * 20))
        else:
            via_score = 50.0

        raw = (
            0.15 * self.placement.total +   # placement quality
            0.65 * route_pct +              # routing completion (dominant)
            0.10 * via_score +              # fewer vias
            0.10 * self.placement.board_containment  # containment as a scored dimension
        )
        self.total = raw
        return self.total
```

**After:**
```python
    def compute(self, weights: Optional[dict] = None) -> float:
        """Compute unified score. Route completion dominates, then placement."""
        w = weights or {}
        w_placement = w.get("placement", 0.15)
        w_route = w.get("route_completion", 0.65)
        w_via = w.get("via_penalty", 0.10)
        w_contain = w.get("containment", 0.10)

        # Route completion: most important — must get all nets routed
        if self.total_nets > 0:
            route_pct = ((self.total_nets - self.failed_nets)
                         / self.total_nets) * 100
        else:
            route_pct = 100.0

        # Via penalty: fewer vias per routed net = better
        if self.routed_nets > 0:
            vias_per_net = self.via_count / self.routed_nets
            via_score = max(0, min(100, 100 - vias_per_net * 20))
        else:
            via_score = 50.0

        raw = (
            w_placement * self.placement.total +
            w_route * route_pct +
            w_via * via_score +
            w_contain * self.placement.board_containment
        )
        self.total = raw
        return self.total
```

**Note:** Also update `program.md` to document the `containment` weight key and remove the unused `trace_efficiency` key (which was never wired up):

**File:** `.claude/skills/kicad-helper/scripts/program.md`, score_weights JSON block:
```json
{
  "score_weights": {
    "placement": 0.15,
    "route_completion": 0.65,
    "via_penalty": 0.10,
    "containment": 0.10
  }
}
```

### Test

```python
from autoplacer.brain.types import ExperimentScore, PlacementScore

es = ExperimentScore(routed_nets=20, total_nets=20, failed_nets=0,
                     trace_count=100, via_count=10)
es.placement = PlacementScore(total=80.0, board_containment=90.0)

# Default weights
es.compute()
default_score = es.total

# Custom weights emphasizing routing more
es.compute({"placement": 0.05, "route_completion": 0.80, "via_penalty": 0.10, "containment": 0.05})
custom_score = es.total

print(f'Default: {default_score:.2f}, Custom: {custom_score:.2f}')
assert abs(default_score - custom_score) > 0.5, "Custom weights should produce different score"
```

---

## Bug 4: Batch scheduling defeats plateau detection

**File:** `.claude/skills/kicad-helper/scripts/autoexperiment.py`
**Lines:** 913 (batch_size calculation)

### Problem

`batch_size = min(n_workers, args.rounds - round_num)` — with 22 workers and 20 rounds, the entire run is a single batch. The plateau counter (`minor_stagnant`) only increments after results return, so the `if minor_stagnant >= args.plateau: mode = "major"` check only fires during batch *generation*, not between result processing. Result: all 20 rounds are MINOR mutations of the same config. MAJOR mutations (new seed + aggressive params) never trigger.

### Fix

Cap `batch_size` to `args.plateau` so the loop generates a new batch after each wave completes. This gives the plateau counter time to accumulate. Also, guarantee at least 1 MAJOR mutation per batch when stagnation exceeds the threshold.

**Before** (autoexperiment.py line 913):
```python
            batch_size = min(n_workers, args.rounds - round_num)
```

**After:**
```python
            batch_size = min(n_workers, args.rounds - round_num, max(args.plateau, 1))
```

This caps batches to `plateau` size (default 5), letting the stagnation counter work properly between batches. With 22 workers, 20 rounds, plateau=5: 4 batches of 5 instead of 1 batch of 20.

### Test

Run a short autoexperiment and check the log for mode diversity:

```bash
cd /home/jason/Documents/LLUPS
python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb \
  --rounds 12 --plateau 3 --workers 4 \
  --program .claude/skills/kicad-helper/scripts/program.md 2>&1 \
  | grep -oP '\[(?:MINOR|MAJOR|EXPLO)\]' | sort | uniq -c
```

**Pass criteria:**
- At least 1 MAJOR mode appears (was 0/20 before)
- Not all rounds are MINOR

---

## Integration Test

After all 4 fixes are applied, run a full 10-round experiment to validate the system end-to-end:

```bash
cd /home/jason/Documents/LLUPS
python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb \
  --rounds 10 --workers 4 \
  --program .claude/skills/kicad-helper/scripts/program.md 2>&1 | tail -30
```

**Pass criteria (all must be true):**
1. No `AttributeError`, `Traceback`, or crash messages
2. `Routed X/Y nets` appears (Y > 0, X > 0) in round output
3. `score=` values are positive (not -0.3x or 0.00)
4. At least 1 round shows `[NEW BEST]` (kept > 0)
5. `Best score:` at the end shows `routed=X/Y` with Y > 0
6. `LLUPS_best.kicad_pcb` is updated

---

## Files Modified (Summary)

| File | Change |
|------|--------|
| `autoplacer/brain/conflict.py` | Fix `PathResult` handling in `_try_route` + add import |
| `autoplacer/brain/placement.py` | Proportional containment penalty |
| `autoplacer/brain/types.py` | Wire up `weights` param in `compute()`, remove multiplicative containment kill |
| `autoexperiment.py` | Cap `batch_size` to `plateau` for proper mode switching |
| `program.md` | Update score_weights keys to match implementation |

## Execution Order

Apply fixes in this order (each builds on the previous):
1. **Bug 1** first — without this, the pipeline crashes and nothing else matters
2. **Bug 2** — without this, scores are always 0 from the containment multiplier
3. **Bug 3** — makes program.md weights functional
4. **Bug 4** — enables exploration via MAJOR mutations
5. Run **Integration Test**
