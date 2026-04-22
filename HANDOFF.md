# Session Handoff: Parent Composition SMT-over-THT Stacking Fix

Date: 2026-04-22
Pushed: no (local only on branch feat/project-plan-layer)

## This Session's Work

User reported: parent PCB is too large because SMT leaves aren't stacking onto the front side opposite the back-dominant battery leaf (BT1). The user wants SMT leaves preferentially placed opposite THT leaves to maximize dual-sided packing.

### Root cause

`_find_non_overlapping_origin` in `kicraft/cli/compose_subcircuits.py` returned the FIRST legal overlap candidate from its y-major raster. That's the position where the candidate bbox just starts touching an already-placed leaf (0.1 mm overlap), not the position that maximally stacks. Hundreds of better overlap positions deeper inside the battery footprint were collected but discarded.

Verified the rest of the side-aware machinery was already correct:
- `_assign_layers` correctly places BT1/BT2 on B.Cu (solved_layout confirms layer=B.Cu).
- `LeafBlockerSet` separates front_pads / back_pads / tht_drills per leaf.
- `can_overlap_sparse` allows front-only-vs-back-only stacking; the battery holder's 4 THT pad rects leave huge clean zones between them.
- Diagnostic found 641 legal overlap candidates vs 420 empty candidates for CHARGER over BT1 -- but only the first-found overlap was being returned.

### Fix

KiCraft `feat/project-plan-layer` 831be3b: score each legal candidate by total bbox overlap area with placed leaves, pick maximum. Empty fallback only if no overlap legal. Proximity to proposed point as tiebreaker.

### Result

Re-running `solve-hierarchy --skip-leaves --route`:

| Leaf | Before (x, y) | After (x, y) |
|------|---------------|--------------|
| CHARGER | y=13-25 (above batteries) | y=41-52 (over batteries) |
| BOOST 5V | y=13-25 (above batteries) | y=34-45 (over batteries) |
| BATT PROT | y=19-26 (above batteries) | y=19-26 (marginal -- placed last, cluttered by CHARGER+BOOST) |

Parent_stamped.png and parent_routed.png in `.experiments/subcircuits/subcircuit__8a5edab282/renders/` both confirm visually: BOOST 5V, CHARGER, and BATT PROT silkscreen outlines now sit INSIDE the BT1 footprint rectangle, not in a strip above it.

### Trade-offs observed

- Board width grew from 99.82 -> 114.25 mm. Caused by LDO 3.3V's edge-pinned J3/J2 connectors + H86 bottom-right corner constraint setting the right edge. Area 7821 -> 9006 mm^2 (+15%).
- Score 66.904 (same methodology as previous runs; direct comparison pending)
- Parent acceptance still rejected: `illegal_routed_geometry` (pre-existing, tracked in ROADMAP Phase 7)
- KiCraft tests: 429 pass (no regressions)

## Commits

- KiCraft `831be3b fix(compose): pick overlap candidate by max area instead of first`
- LLUPS   `70a020b fix(compose): SMT leaves now stack over back-dominant battery leaf` (submodule bump + ROADMAP)

Neither pushed yet.

## Known Remaining Work (Phase 7)

Listed in ROADMAP.md. Priority order:

1. **Allow the iterative frame to SHRINK when placements fit with slack.** Currently frame only grows on overflow. After successful stacking the seed frame is reset to last_outline on break, but placements don't re-run. A smaller initial seed (or explicit shrink-and-retry iteration) would push leaves tighter.

2. **Per-unconstrained-leaf rotation search.** `_make_unconstrained_model` uses a static rotation from the leaf index. Real rotation search would let each leaf pick the orientation maximizing overlap with placed leaves. BATT PROT in particular might fit inside remaining BT1 holes if rotated.

3. **BATT PROT sub-optimal placement** -- third unconstrained leaf gets squeezed between CHARGER and BOOST. Consider re-running unconstrained placement in reverse-size order, or iterating unconstrained placements until convergence.

4. Parent acceptance gate still rejects `illegal_routed_geometry` (existing issue, not caused by this fix).

## Reproduction

```bash
cd /home/jason/Documents/LLUPS
timeout 120 solve-hierarchy LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --skip-leaves --route
xdg-open .experiments/subcircuits/subcircuit__8a5edab282/renders/parent_stamped.png
```

## Test Gate

```bash
cd KiCraft && python -m pytest -x -q
# 429 passed expected
```

## Files Modified

- `KiCraft/kicraft/cli/compose_subcircuits.py` -- `_find_non_overlapping_origin` selection logic + new `_bbox_overlap_area` helper
- `ROADMAP.md` -- added Phase 7 tracker
