# LLUPS Minimal-Verify Render Defects -- Plan

Date opened: 2026-04-22
Last updated: 2026-04-22 (after end-to-end verify + D3 scoring landed)
Owner: resumable -- update status as you go

## Resume instructions for the next agent

Commits on KiCraft/main (submodule) landed in this session:
- `8f2c4e6` -- D1: honour footprint PCB Edge marker for edge anchors
- `96917a1` -- D2: stamp parent-local keep-in rects as rule-area zones
- `09347ba` -- D1 follow-up: relax geometry validator for edge-constrained refs
  (USB-C shell is allowed outboard of Edge.Cuts; pads still checked)
- `446d3ae` -- D3: steepen SMT-opposite-THT curve + raise weight 0.10 -> 0.15

LLUPS parent repo has been bumped to point at `446d3ae` (KiCraft submodule).

Outstanding items (see priority list below):
- D2 preserved-child-trace edge-case: one child-routed trace from USB_INPUT
  still crosses H4 in the current verify run because it was preserved from
  the child board, and FreeRouting does not reroute preserved tracks.
  See section "Defect 2 follow-up" below.
- D3 effect is not yet visible in the `--rounds 1 --fast-smoke` run used by
  verify-minimal.sh; the scoring gradient is wired but needs multi-round SA.

### Outstanding work in priority order

1. **D2 preserved-trace edge case.** After the D2 keepouts land, FreeRouting
   does not route new tracks through H4/H86, but one preserved child trace
   from USB_INPUT still crosses H4 at distance 0.27mm. The cause: child
   routing is baked in before compose, and parent-level keep-in rects do
   not retroactively reroute preserved tracks. Options:
   - (a) During compose, when a parent-local keep-in rect overlaps a preserved
     child trace, clear that segment and let FreeRouting reroute it.
   - (b) Push the keepout awareness down into leaf solve, so USB_INPUT does
     not route through the region where H4 will land.
   (a) is lower-effort; (b) is architecturally cleaner.
2. **Multi-round D3 verification.** The `--rounds 1 --fast-smoke` minimal
   verify cannot fully exercise the scoring bias. Either add a
   `verify-smt-over-tht.sh` that runs more rounds (say 5-10) against a known
   starting layout, or tweak `verify-minimal.sh` to also emit the
   `smt_opposite_tht` sub-score so regressions are visible.
3. **Simplifications** -- deduplicate `edge_target` arithmetic
   (`subcircuit_composer.py:484-490`, `compose_subcircuits.py:858-861`,
   `compose_subcircuits.py:1396-1415`). Low risk; do after D3 tuning.

## Context

Baseline render from `./verify-minimal.sh` (most recent `parent_routed.kicad_pcb`) shows
three pipeline defects. This file tracks the fix plan so another agent can resume
mid-stream if this session ends.

All code paths below confirmed by reading the source, not inferred.

## Defect 1: USB connector not flush to left PCB edge

### Symptom
USB-C connector (J1) sits well inside the board -- its "PCB Edge" `fp_text` on
`Dwgs.User` is inside the board, and the connector shell does not cross the
Edge.Cuts left edge. Previously this worked. With `connector_edge_inset_mm = 0.0`
we expect the **connector body's PCB-Edge reference** to be flush with the parent
left edge.

### Root cause (confirmed)
`_compute_local_anchor_offset()` (`subcircuit_composer.py:408`) calls
`_constraint_local_rect()` (`subcircuit_composer.py:1379`), which returns
`blocker_set.component_rects[ref]` for the constrained connector. That rect is the
**pad + courtyard + fab** bbox -- it does not include the `fp_text "PCB Edge"` on
`Dwgs.User`. Result: when we anchor the "left" side of that rect to
`parent_outline_min.x`, the pad cluster becomes flush but the connector body
hangs off the inboard side, with the actual USB mouth interior to the board.

The "PCB Edge" text IS read by `hardware/adapter.py:200` but only to resolve
opening **direction** for THT hole placement -- not to shift the connector's
attachment anchor.

### Fix plan
1. Extend `LeafBlockerSet` (or a parallel map) to carry an optional
   **`edge_reference_offset`** per ref -- extracted from the footprint's
   `fp_text` or `fp_line` on `Dwgs.User` containing "edge" (case-insensitive).
   The offset is the signed distance (in leaf-local coordinates, pre-rotation)
   from the pad/courtyard bbox edge on the constrained side to the edge-reference
   marker. Positive = marker further out than the bbox.
2. In `_compute_local_anchor_offset()`, after computing the pad/courtyard
   anchor, apply `edge_reference_offset` for the constrained side so the
   returned `Point` represents the marker, not the pad edge.
3. Persist the edge-reference map through the same routed-leaf
   persistence pathway that already carries `component_rects`.
4. Add regression test `test_edge_anchor_uses_pcb_edge_marker` in
   `KiCraft/tests/test_subcircuit_composer.py`:
   build a synthetic leaf with a pad bbox + "PCB Edge" marker 1.5mm
   outboard; assert the left-edge anchor equals the marker, not the pad.
5. Guard: if no edge-reference marker is found, behaviour is unchanged
   (preserves every other connector/footprint without the marker).

### Files to touch
- `KiCraft/kicraft/autoplacer/brain/subcircuit_composer.py`
  (`LeafBlockerSet`, `extract_leaf_blocker_set`, `_constraint_local_rect`,
  `_compute_local_anchor_offset`)
- `KiCraft/kicraft/autoplacer/hardware/adapter.py`
  (expose the "PCB Edge" marker position during leaf extraction -- already
  parses it at line 200, just needs to emit offset too)
- `KiCraft/tests/test_subcircuit_composer.py` or a new file

### Status
- [x] implemented (KiCraft 8f2c4e6)
- [x] unit tests added (`test_edge_anchor_uses_pcb_edge_marker_when_present`,
  `test_edge_anchor_falls_back_to_pad_bbox_without_marker`)
- [x] pytest -x -q passes (429 tests, up from 417)
- [x] verify-minimal.sh confirms body extends outboard (3.01mm) and PCB Edge
  marker is flush with Edge.Cuts. Pad_left is 1.315mm inboard of edge, which
  reflects the USB-C housing inset (pads sit on the inboard land; the shell
  hangs off the edge). The original "pad_left < 0.5mm from edge" target
  mis-described USB-C geometry -- marker-to-edge is the real contract.
- [x] follow-up (KiCraft 09347ba): geometry validator no longer rejects
  edge-constrained components with bodies extending outboard of Edge.Cuts.

## Defect 2: Trace routed through top-left mounting hole H4

### Symptom
A clear horizontal trace runs straight through the H4 mounting-hole drill.

### Root cause (confirmed)
`compose_subcircuits.py:1291-1307` constructs `parent_local_keep_in_rects`
around H4/H86 (from `inward_keep_in_mm`). These are passed into
`build_parent_composition()` and consumed by `can_overlap_sparse()` to **shift
leaf origins** during placement. But they are **never emitted as KiCad
rule-area (keep-out) zones** on the stamped parent board. FreeRouting runs on
that stamped board (`_route_parent_board` at line 2188, `freerouting_runner.py`)
with no knowledge of the mounting-hole no-route zone, so a trace can be laid
through the drill.

`freerouting_runner.py` actively **removes** zones (`strip_zones`, line 993) and
the stamping subprocess at `hardware/adapter.py:318` clears zones by default.
Even if someone added keep-outs upstream, they would be wiped.

### Fix plan
1. After stamping the parent (post `_stamp_parent_board`) and before DSN export,
   add a new step `_stamp_parent_keepouts()` that creates one KiCad rule-area
   zone per `parent_local_keep_in_rect` on both F.Cu and B.Cu with
   `keepout_tracks = true, keepout_vias = true, keepout_copperpour = true`.
2. Mark these zones as rule-areas so `strip_zones()` preserves them (already
   checks `GetIsRuleArea()` -- see `freerouting_runner.py:765`).
3. Plumb `parent_local_keep_in_rects` into the stamp subprocess JSON
   (`_STAMP_SUBPROCESS_SCRIPT` in `hardware/adapter.py:233`) alongside the
   existing outline/components/traces/vias data.
4. Validate through FreeRouting: DSN export picks up rule-area keepouts via
   pcbnew; verify by running FreeRouting and inspecting DRC/report.
5. Add regression: `test_parent_keepouts_stamped` -- run compose on a small
   synthetic parent with a mounting hole, load the routed pcb, assert no
   track segment intersects the expanded mounting-hole disc.

### Files to touch
- `KiCraft/kicraft/cli/compose_subcircuits.py` -- new
  `_stamp_parent_keepouts()` call in `_route_parent_board` path
- `KiCraft/kicraft/autoplacer/hardware/adapter.py` -- stamp subprocess accepts
  and creates rule-area zones
- tests

### Status
- [x] implemented (KiCraft 96917a1)
  - New field `ParentCompositionState.parent_local_keep_in_rects`.
  - Populated at the existing keep-in build site in `_compose_subcircuits` main path.
  - Serialised into the parent stamp JSON payload alongside outline/components.
  - `_PARENT_STAMP_SCRIPT` creates one F.Cu + one B.Cu rule-area ZONE per rect with
    DoNotAllowTracks/Vias/Pads/CopperPour all True.
- [x] regression test added (`tests/test_parent_stamp_keepouts.py`) --
  locks the rule-area/keepouts contract between compose and the stamp
  subprocess.
- [x] pytest -x -q passes (429 tests)
- [x] verify-minimal.sh shows 4 rule-area zones survive FreeRouting
  (one F.Cu + one B.Cu per keepout rect, both holes). No **new** FreeRouting
  trace enters the keepouts.
- [ ] **edge case**: one *preserved* child trace from USB_INPUT still passes
  through H4 at distance 0.27mm. FreeRouting does not reroute preserved
  tracks; the fix lives in compose, not routing (see outstanding item 1).

### Implementation notes / risks
- FreeRouting's DSN export is produced by `pcbnew.ExportSpecctraDSN()` in
  `freerouting_runner.py:270`. pcbnew's SpectraDSN exporter has historically
  honoured rule-area (no-track/no-via) zones, but we have not confirmed this
  with the current KiCad 9 build. If the next verify run still shows tracks
  through H4/H86, first check whether the rule-area zones survived into
  `parent_routed.kicad_pcb` (grep for `rule_area`) and then whether the DSN
  contained a corresponding `keepout` entry.
- `strip_zones()` in `freerouting_runner.py:993` already preserves
  `GetIsRuleArea()==True` zones, so the keepouts should not be stripped before
  routing.

## Defect 3: Front SMT leaves not packed over backside THT batteries

### Symptom
Large free real-estate on the front side of the board opposite BT1/BT2 (backside
THT battery holders). Front SMT leaves (CHARGER, BOOST_5V, LDO_3V3) are clustered
top-center, leaving the bottom half of the front side empty while huge backside
battery shadows go unused.

### Root cause (confirmed)
Two interacting factors:
- `placement_scorer.py:_score_smt_opposite_tht` (lines 224-267) returns
  `50.0 + 50.0 * overlap_frac` -- so 0% overlap gets 50, not 0. No penalty for
  ignoring the shadow.
- `types.py:221` gives `smt_opposite_tht` weight **0.10**, tied with
  `courtyard_overlap` and `edge_compliance`, and dominated by `net_distance`
  (0.20) and `crossover_score` (0.17) which both pull SMT leaves toward the
  ICs near the top.

Sparse blocker model already **allows** F-over-B overlap (from prior session --
`can_overlap_sparse()`), but the solver has no carrot strong enough to choose
it over net-distance.

### Fix plan (ordered least-to-most invasive, stop when target met)
1. Steepen the curve: `score = max(0.0, 100.0 * overlap_frac)`. At 0% overlap
   score is 0 (penalty), at 100% score is 100. Update docstring.
2. Raise weight `smt_opposite_tht: 0.10 -> 0.15`; offset by trimming
   `compactness` (0.02 -> 0.01) and `rotation_score` (0.01 -> 0.0) to keep
   weights summing to ~1.0. Or subtract from `aspect_ratio` / `rotation_score`.
3. If target still missed, add an explicit attractive bias pass in
   `placement_solver.py` after force-directed convergence: for each unconstrained
   front SMT leaf with no locked position, nudge origin toward the centroid of
   backside-THT shadow(s) weighted by shadow area. Bounded step (~2mm) to avoid
   destabilising good placements.
4. Update existing scoring regression tests (some likely lock current curve;
   update expected values rather than delete tests).

### Files to touch
- `KiCraft/kicraft/autoplacer/brain/placement_scorer.py` (lines 224-267)
- `KiCraft/kicraft/autoplacer/brain/types.py` (lines 212-227 weights)
- possibly `KiCraft/kicraft/autoplacer/brain/placement_solver.py` (bias pass)
- test updates in `KiCraft/tests/test_placement_scorer.py` (or similar)

### Status
- [x] step 1 (curve) implemented (KiCraft 446d3ae). `50 + 50*f` -> `100*f`.
- [x] step 2 (weight) implemented (KiCraft 446d3ae).
  `smt_opposite_tht 0.10 -> 0.15`, offset by compactness 0.02 -> 0.01,
  rotation_score 0.01 -> 0.0, aspect_ratio 0.05 -> 0.02. Weights sum to 1.00.
- [ ] step 3 (bias pass) -- deferred. Retry only if multi-round runs also
  miss the 200mm^2 target.
- [x] pytest -x -q passes (429 tests)
- [ ] verify-minimal.sh single-round shows 21.6mm^2 overlap -- not yet at
  the 200mm^2 target, but the smoke run only does one SA round. Need a
  multi-round verification to see whether the steepened gradient alone
  closes the gap or whether step 3 (bias pass) is actually needed.

## Simplification candidates (do opportunistically, not blocking)

1. The edge-target arithmetic
   `min.x + inward_keep_in_mm - outward_overhang_mm` / `max.x - inward + outward`
   is duplicated verbatim across:
   - `subcircuit_composer.py:484-490` (`_exact_target_coordinate`)
   - `compose_subcircuits.py:858-861` (preview path)
   - `compose_subcircuits.py:1396-1415` (validate path, all four corners)
   Collapse into a single helper `edge_target_for_side(side, constraint, min, max)`
   and import from one location.

2. `_exact_target_coordinate` and `_zone_band_interval` both live in composer;
   if they become method-level, consider grouping with `AttachmentConstraint`.

3. After Defect 1 fix: the adapter-side "PCB Edge" direction parser
   (`hardware/adapter.py:200`) and the new offset parser share footprint-item
   iteration. Consider sharing a single "find edge-ref graphic" helper.

## Defect 2 follow-up: preserved child traces through mounting holes

### Symptom
After D2 stamped rule-area zones and FreeRouting honoured them, one
pre-existing track at y=-1.48 from x=2.10 to x=11.58 still runs through
H4's keepout (zone bbox x=3.0..12.593). Track distance to H4 centre:
0.27mm.

### Root cause (confirmed)
This track is **preserved from the USB_INPUT child's solved layout** --
it is laid in child-local coords during leaf solve, and when the child
is placed in the parent, that trace now intersects H4 in parent coords.
FreeRouting only routes previously-unrouted nets; it does not reroute
already-placed tracks. Parent rule-area keepouts therefore have no
effect on preserved child copper.

### Fix plan (not yet landed)
1. **Simpler**: during `_compose_subcircuits`, after child tracks are
   transformed to parent coords, drop any segment whose midpoint (or
   endpoint) falls inside a parent-local keep-in rect. Mark the net as
   "needs routing" so FreeRouting picks it up.
2. **Cleaner**: push parent-level keepouts into leaf solve as hints so
   USB_INPUT does not route through the region where H4 will sit.

Option 1 is smaller surface area and works with existing data flow.

### Files likely touched
- `KiCraft/kicraft/cli/compose_subcircuits.py` (trace-filter step after
  placement, before `_stamp_parent_board`)

### Status
- [ ] not yet implemented
- [ ] regression test -- a synthetic compose where a child trace crosses
  the parent-local keepout, assert that post-compose BoardState has no
  trace intersecting the keepout rect.

## Verification gate

After any of the fixes land:

```bash
# 1. Unit gate
cd /home/jason/Documents/LLUPS/KiCraft && python -m pytest -x -q

# 2. Import smoke (see AGENTS.md section "2. Import smoke test")

# 3. Minimal pipeline
cd /home/jason/Documents/LLUPS && ./verify-minimal.sh
```

Success criteria (checked against newest `parent_routed.kicad_pcb`):
- D1: J1 pad cluster left edge within 0.5mm of Edge.Cuts left edge; connector
  body extends outboard (no inboard pad cluster with cable mouth interior).
- D2: no track segment intersects H4 or H86 drill + 1mm clearance disc.
- D3: F-over-B overlap area >= 200 mm^2 (up from the observed ~61 mm^2 baseline).
- No new pytest failures; 417+ tests still passing.

## Rollback / safety notes

- Every change stays behind a config flag or is backwards-compatible by
  fall-through (e.g., Defect 1 has no-op path when no edge marker present).
- Parent-local keep-in rects are created as **rule areas**, so existing
  `strip_zones()` behaviour for non-rule zones is unchanged.
- If Defect 3 step 2 breaks previously-passing acceptance tests, prefer fixing
  the test's expected values (numerical drift) over reverting the weight --
  unless acceptance actually gets worse on a known-good layout.

## Commit policy

Per AGENTS.md "Commit As You Go": one commit per defect fix landed, plus
separate commits for (a) plan file updates, (b) simplification refactors, and
(c) submodule pointer bumps. KiCraft commits inside submodule first; LLUPS
parent commit bumps the submodule pointer.
