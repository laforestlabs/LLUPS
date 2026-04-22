# Session Handoff: Parent Composition Quality

Date: 2026-04-22
Pushed: yes -- LLUPS main at 82d9581, KiCraft main at 88231c1

## Scope

User originally wanted:
1. SMT leaves preferentially placed opposite battery (BT1) on front side
2. Shrink the parent board now that stacking works
3. Mounting hole (H4) interfering with connector leaf (USB INPUT) -- find the root cause and fix

All three done and pushed to main.

## Fixes shipped (in order)

### 1. Max-overlap candidate selection (KiCraft 831be3b, LLUPS 70a020b)

`_find_non_overlapping_origin` returned the first legal overlap from a
y-major raster. That's the position where candidate bboxes just start
touching an existing leaf (0.1 mm overlap). Score candidates by total
bbox overlap area, return max. Empty fallback only when no overlap
legal.

Result on LLUPS: CHARGER and BOOST 5V moved from a 20 mm strip above
the batteries onto the front side opposite BT1/BT2.

### 2. Opposite-side overlap weighting (KiCraft dbe021a, LLUPS 5d14253)

Same-side SMT leaves could overlap each other in pad gaps (legal per
sparse rect check) instead of moving onto back-dominant leaves.
Weight overlap 1.0 for opposite-side (front vs back dominant), 0.5 if
either leaf is dual-side, 0.2 for same-side.

Result: BATT PROT moved from y=19-26 (overlapping CHARGER) to y=29-36
(fully inside BT2's back-side footprint). All three unconstrained SMT
leaves now on the front opposite the batteries.

### 3. Mounting hole clears leaf component bodies (KiCraft 08ba7a3, LLUPS 1a5ad4d)

`_placed_item_blocker_rects` only exposed pads + THT drills to the
parent-local keep-in check. Result: H4 sat visually inside USB INPUT's
silkscreen box because no individual pad was at that exact spot -- but
the USB-C receptacle housing (which projects past its pads) was right
there. Mechanically the screw head would collide with the connector body.

Added `blocker_set.component_rects` (courtyard bboxes) to the keep-in
check. Also raised `mounting_hole_keep_in_mm` default from 2.5 to 5.0
mm (M3 screw head + washer clearance).

Result: H4 moved from (7.8, -1.2) [inside USB INPUT box] to (27.8,
1.3) [clear of leaf]. Parent status also changed from
`illegal_routed_geometry` to **accepted** as a side-effect.

### 4. Post-iteration free-axis compaction (KiCraft 88231c1, LLUPS 82d9581)

Constrained leaves' non-constrained axes defaulted to `frame_min` --
leaves with only an x-constraint (USB INPUT on left edge, LDO 3.3V on
right edge) all hugged the top of the frame, forcing a large empty
strip between the top edge and the battery area.

Added `_compact_free_axes`: after the placement iteration converges,
for each leaf, binary-search the max safe shift along each
unconstrained axis toward the cluster centroid. Updates entries,
placed_envelopes, placed_child_bboxes, child_artifact_placements, and
transformed_payloads so the actual stamping sees the shifted positions.
Recomputes outline from the new bboxes.

Result on LLUPS:
- USB INPUT y: -2..10 -> 16..25 (down 18 mm)
- LDO 3.3V y: -2..4 -> 19..25 (down 21 mm)
- H4/H86 follow via subsequent _reposition_parent_local_components
- **Board: 114x79 mm -> 114x64 mm (-18.7% area)**
- Composition score: 66.9 -> 71.0
- Parent status: accepted

## Final metrics

| Metric | Pre-session | Post-session |
|--------|-------------|--------------|
| Board dimensions | 99 x 79 mm | 114 x 64 mm |
| Board area | 7821 mm^2 | 7315 mm^2 (-6.5%) |
| SMT leaves on front opposite BT1 | 0 / 3 | 3 / 3 |
| H4 inside USB INPUT silkscreen | yes | no |
| Parent acceptance | rejected (illegal_routed_geometry) | accepted |
| Composition score | 66.9 | 71.0 |
| KiCraft tests | 429 pass | 429 pass |

Width went UP (99->114) because the edge-pinned connector constraints
(J1 USB-C housing overhang on left, J3/H86 on right) drive the board
width. The remaining width is largely fixed by those constraints.

## Remaining work (not required)

1. **Width shrink.** Right edge sits at ~107 mm because H86 mounting hole
   (bottom-right corner constraint) + J3 edge=right + keep-in combine
   there. If H86's corner placement is computed from the outline _after_
   compaction, H86 could shift left and the outline could follow. Worth
   trying: move `_reposition_parent_local_components` into the compaction
   loop so it runs iteratively.

2. **Per-leaf rotation search.** Current `_make_unconstrained_model` uses
   a static rotation per leaf index. Real rotation search would let each
   leaf pick the orientation that maximizes overlap / minimizes the
   cluster bbox.

3. **x-axis compaction for BT1.** BT1 is zone-constrained (zone=bottom),
   which my `_constraint_axes_used` treats as a y-constraint. Its x is
   free but probably doesn't shift because the only bboxes in its row
   are itself. Verify and refine if BT1 position matters.

4. **Mounting hole keep-in as per-ref override.** `mounting_hole_keep_in_mm`
   is now a global default (5.0 mm). Users may want M2 vs M3 vs M4 per
   hole. Add `component_zones.<ref>.keep_in_mm` override.

5. **Autoexperiment re-baseline.** Score jumped from ~66 to 71 post-fix.
   Existing elite_configs.json may be stale and drag new runs toward the
   old layout. Consider invalidating or adding a migration.

## Reproduction

```bash
cd /home/jason/Documents/LLUPS
timeout 120 solve-hierarchy LLUPS.kicad_sch --pcb LLUPS.kicad_pcb \
  --rounds 1 --skip-leaves --route
xdg-open .experiments/subcircuits/subcircuit__8a5edab282/renders/parent_stamped.png
```

## Test gate

```bash
cd KiCraft && python -m pytest -x -q
# 429 passed expected
```

## Files modified

KiCraft:
- `kicraft/cli/compose_subcircuits.py` -- max-overlap selection,
  opposite-side weighting, component-bodies in keep-in,
  `_compact_free_axes` + wiring, `_constraint_axes_used`, `_bbox_overlap_area`
- `kicraft/autoplacer/brain/subcircuit_composer.py` -- raised default
  `mounting_hole_keep_in_mm` from 2.5 to 5.0

LLUPS:
- `ROADMAP.md` -- Phase 7 tracker
- `HANDOFF.md` -- this file
- `KiCraft` submodule pointer -- four bumps

## Commit log (main)

LLUPS:
- 82d9581 chore: bump KiCraft -- post-iteration compaction for parent composition
- 1a5ad4d chore: bump KiCraft -- include leaf component bodies in parent-local keep-in
- 4258a38 docs: update handoff + roadmap for BATT PROT opposite-side fix
- 5d14253 chore: bump KiCraft -- opposite-side overlap weighting for parent compose
- 75a466d docs: handoff for SMT-over-THT stacking fix
- 70a020b fix(compose): SMT leaves now stack over back-dominant battery leaf

KiCraft:
- 88231c1 feat(compose): post-iteration free-axis compaction
- 08ba7a3 fix(compose): include leaf component bodies in parent-local keep-in
- dbe021a feat(compose): weight overlap scoring by opposite-side stacking
- 831be3b fix(compose): pick overlap candidate by max area instead of first
