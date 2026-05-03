# Plan: make `PlacementScorer` area-aware against the placed bbox

## Status

Follow-up to the parent-area-reduction work landed in `KiCraft 072ceb6` (`feat(compose): slide edge/corner-pinned components to cluster post-solve`) and tracked at LLUPS `56253f7`. That commit added a post-solve `_slide_constrained_to_cluster` pass that pulls drifting edge-/corner-pinned components back into the cluster bbox, dropping parent area by 18-29% across seeds 4/7/42.

This plan addresses the *follow-up* identified during that work: the placement solver's own scorer (`PlacementScorer` in `KiCraft/kicraft/autoplacer/brain/placement_scorer.py`) is blind to the area cost of leaves drifting inside the seed frame, so SA refinement does not actively shrink the layout -- it relies entirely on the post-pass cleanup. Closing this gap should let SA find tighter pre-slide configurations, reducing the work the slide step has to do and, in good seeds, beating Change A's standalone numbers.

## Context an implementer needs

### Where in the pipeline this fires

The parent placement flow (`KiCraft/kicraft/cli/compose_subcircuits.py::_compose_artifacts`):

1. `_seed_outline_dimensions(...)` -> a 2.5x-area-slack seed rectangle. **Load-bearing for routing feasibility** -- changelog 2026-05-02 records that shrinking it to 1.8x produced 0/4 routed rounds. Do not change this.
2. `PlacementSolver(state_in, ...).solve()` -> force-directed + SA refinement. This is what scores against the seed frame today.
3. `_slide_constrained_to_cluster(solved, derived, synthetic_refs)` -> Change A. Slides edge/corner-pinned components back to the cluster.
4. `_compute_final_outline(...)` -> the outline that becomes the actual PCB.
5. `build_parent_composition(..., board_outline=exact_outline)` -> the round-level score (`_score_parent_composition`) which **already** uses the final outline and reports an area-aware `area_utilization`.

The gap is step 2: the SA refinement loop inside `solve()` is the only thing that reorders blocks, but its scoring frame is the fixed seed.

### How `PlacementScorer` is wired

- `PlacementScorer.score()` returns a `PlacementScore` (see `KiCraft/kicraft/autoplacer/brain/types.py:244-296`) whose `compute_total()` weights 12 sub-metrics.
- `_score_compactness` (`placement_scorer.py:86-95`) returns `min(100, fill * 150 + 25)` where `fill = total_component_area / board_area`. `board_area` here is `state.board_width * state.board_height`, i.e. the seed frame -- *fixed for the entire solve*, so this metric contributes a constant. SA cannot move it.
- `_score_smt_opposite_tht`, `_score_block_opposite_side`, `_score_courtyard_overlap` are position-dependent and *do* drive SA, but none of them penalise leaves drifting outward into empty seed-frame space; an isolated leaf parked in a corner just doesn't overlap anything, so those metrics shrug.
- `compute_total` weights live in `PlacementScore.compute_total` (`types.py:269-294`). Touching weights in this dict is the only way to give a new metric authority.

`PlacementScorer` is shared between **leaf placement** and **parent placement**. Any change applies to both. Leaf placements typically already fill most of their leaf-PCB so the new metric will mostly read as "near full" for leaves; the meaningful work happens during parent placement where there is real spread.

## What to change

### Change 1 -- add a new score metric `bbox_packing`

Add a new sub-metric that measures how tightly placed components fill the *placed bbox*, not the seed frame. This is essentially `_score_parent_composition`'s `packing_density` (`subcircuit_composer.py:1133-1149`) lifted into `PlacementScorer`. Because it is computed from `state.components`' positions, it changes every time SA moves a component -- exactly the signal SA needs.

**Files to edit**

1. `KiCraft/kicraft/autoplacer/brain/types.py` -- add a `bbox_packing` field on the `PlacementScore` dataclass and a weight in `compute_total`'s default dict.

2. `KiCraft/kicraft/autoplacer/brain/placement_scorer.py` -- add `_score_bbox_packing` and call it from `score()`.

**Suggested implementation**

In `placement_scorer.py`, near the existing `_score_compactness` (line 86):

```python
def _score_bbox_packing(self) -> float:
    """Reward tight clustering measured against the placed-component bbox.

    `_score_compactness` divides total component area by the *seed* board
    area, which is fixed for the whole solve and therefore contributes a
    constant -- SA cannot move it. This metric divides by the dynamic
    bbox of placed components, so an isolated leaf parked in a corner
    inflates the bbox and reduces the score, giving SA a real signal
    that drift costs PCB area.

    Mirrors `subcircuit_composer._score_parent_composition`'s
    `packing_density` so the in-loop SA score and the post-compose round
    score agree about what "tightly packed" means.

    Returns 100 when the placed bbox tightly hugs the components' total
    area, scaling linearly down. Returns 100 (no opinion) when the
    state has fewer than 2 components -- single-leaf placement has no
    spread to score.
    """
    comps = list(self.state.components.values())
    if len(comps) < 2:
        return 100.0
    total_area = sum(c.area for c in comps)
    if total_area <= 0.0:
        return 100.0
    bboxes = [c.physical_bbox() for c in comps]
    xmin = min(b[0].x for b in bboxes)
    ymin = min(b[0].y for b in bboxes)
    xmax = max(b[1].x for b in bboxes)
    ymax = max(b[1].y for b in bboxes)
    placed_area = max(1.0, (xmax - xmin) * (ymax - ymin))
    fill = total_area / placed_area
    # Mirror packing_density from _score_parent_composition: a 1.0 fill
    # ratio is essentially impossible in practice, so amplify slightly.
    # 0.66 fill -> 100 score, 0.33 fill -> 50, 0.10 fill -> 15.
    return max(0.0, min(100.0, fill * 150.0))
```

In `score()` (line 28), append:

```python
s.bbox_packing = self._score_bbox_packing()
```

**Type changes** (`types.py`):

In `PlacementScore` (line 244):

```python
bbox_packing: float = 100.0  # tight packing against placed bbox; 100 when <2 comps
```

In `compute_total`'s default weight dict (line 270):

```python
"bbox_packing": 0.05,
```

Re-balance the dict so weights sum to 1.0. The cleanest re-balance is to take 0.05 from `compactness` (drop 0.01 -> 0.00, since it's already a constant during a solve) and 0.04 from `crossover_score` (0.17 -> 0.13). Crossover handling is overstated relative to its actual lift on routing -- net_distance at 0.20 already biases toward shorter ratsnest. Document the rebalance in the docstring of `compute_total`.

### Change 2 -- (optional) retire the dead `_score_compactness`

If the rebalance drops `compactness` weight to 0, leave the method in place but set its weight to 0 in the default dict. Do not remove the method -- leaves invoke the same scorer through `PlacementScore.compactness` and external callers may reference it. Just stop weighting it.

## Things to keep an eye on

- **Leaf placement quality**: `bbox_packing` returns `100.0` for any leaf placement where component count >= 2, and the leaf solver typically has 4-12 components, so the metric *will* fire on leaves too. Run `python -m pytest -x -q` from `KiCraft/` and watch the leaf solver tests; if any of the placement-quality regression tests degrade, the weight is too high.
- **SA stagnation**: `_sa_refine` (`placement_solver.py:2024+`) accepts a move on score-delta. A new strong attractor toward "tight bbox" might cause SA to over-prefer same-side stacking and miss the dual-layer overlap the existing `smt_opposite_tht` and `block_opposite_side` metrics reward. Watch the `stacked_fraction` reported by `tools/inspect_parent.py` -- if it drops vs the post-Change-A baseline (6.1% on seed 7), the new metric is fighting the stacking metrics.
- **Don't double-shrink**: once `bbox_packing` is in place, SA will tend to cluster blocks tightly inside the seed frame. The existing slide step (Change A) still runs after solve and will *also* slide edge-pinned outliers. Both are correct: the SA-tight pre-slide layout means fewer slides are needed, and the slide is a no-op when the layout is already inside the cluster span. Make sure the `Cluster-slide: ...` log line still shows `0` aligned components when SA produces a tight layout, indicating Change A is dormant rather than fighting Change B.

## Verification

In order. Use the same seeds the original work was verified at so the comparison is apples-to-apples.

1. **Unit tests**: from `/home/jason/Documents/LLUPS/KiCraft`, `python -m pytest -x -q`. The current count is 488 tests; the new metric should not change any of them. If any leaf placement scoring tests fail, lower the `bbox_packing` weight or zero it for leaf-only paths.

2. **Single-seed compose, seeds 4 / 7 / 42**: from `/home/jason/Documents/LLUPS`,

   ```bash
   python3 KiCraft/kicraft/cli/compose_subcircuits.py \
     --project /home/jason/Documents/LLUPS \
     --parent LLUPS \
     --pcb /home/jason/Documents/LLUPS/LLUPS.kicad_pcb \
     --spacing-mm 2.0 --stamp --seed <SEED> --rounds 1
   ```

   For each seed, capture (a) the `composition_mm` line, (b) the `Cluster-slide:` log line, (c) `python3 tools/inspect_parent.py .experiments/subcircuits/subcircuit__8a5edab282/parent_pre_freerouting.kicad_pcb --json` (extract `board_area_mm2`, `wasted_fraction`, `stacked_fraction`).

3. **Compare against the Change-A-only baseline** (which is the current `main`):

   | Seed | Change A only | Target with Change B |
   |------|---------------|----------------------|
   | 7    | 11,058 mm²    | <= 11,058 mm² (smaller is win) |
   | 42   | 12,311 mm²    | <= 12,311 mm² |
   | 4    | 12,628 mm²    | <= 12,628 mm² |

   Any regression on any seed means weights need tuning. The headline win to look for is a seed where SA itself produces a tight layout and `Cluster-slide:` reports `0 edge-constrained, 0 corner-constrained component(s) to the cluster` -- proof that SA is now doing the work pre-slide.

4. **Render check**: `tools/inspect_parent.py` and **read the rendered PNG** at `.experiments/subcircuits/subcircuit__8a5edab282/renders/parent_stamped.png`. Confirm leaves are still packing opposite the batteries (no regression on the dual-layer stacking the previous work fixed). Per the user's `inspect_renders` memory, this visual check is mandatory before claiming the change works.

5. **stamp_drc**: the run already reports `stamp_drc` in metadata. Confirm `clearance` count for non-J1 refs stays at 0 (J1 USB-C internal pad clearance is pre-existing footprint-local override noise; all 14 baseline clearance violations should remain J1-only).

## Out of scope for this plan

- **Don't** add bbox awareness to leaves' compactness scoring on top of this metric. The new `bbox_packing` already fires on leaves; doubling up would over-penalise leaves whose placed bbox legitimately matches the leaf-PCB outline.
- **Don't** thread constraints into `PlacementScorer`. The metric here is purely position-based; the constraint-aware logic lives in the slide step (Change A).
- **Don't** remove or modify Change A's `_slide_constrained_to_cluster`. Even with a perfect SA, edge-pinned leaves can still drift on the free axis if the score landscape has a flat region; Change A is the safety net.
- **Don't** retune the seed outline factor (still load-bearing for FreeRouting at 2.5x).

## Critical files at a glance

- `KiCraft/kicraft/autoplacer/brain/placement_scorer.py` -- add `_score_bbox_packing` near line 86; call from `score()` near line 28
- `KiCraft/kicraft/autoplacer/brain/types.py` -- add `bbox_packing` field on `PlacementScore` near line 244; add weight in `compute_total` defaults near line 270
- `KiCraft/kicraft/cli/compose_subcircuits.py::_slide_constrained_to_cluster` -- *do not modify*, but verify its log line shows `0` aligned components in the good cases as evidence the new SA metric is working

## Rollback

If verification fails, the rollback is `git revert` of the `bbox_packing` commit in KiCraft and a submodule bump on LLUPS. Change A is independently committed (`KiCraft 072ceb6`) and stays. The headline 18-29% win does not depend on this change.
