# Routing failure modes — investigation & improvement plan

Status: **plan** — written 2026-04-23 after observing repeated leaf and
parent routing failures on the `fast 2` preset.

## Observed failure modes

Four distinct failures are showing up. Signatures and reproducer notes
below.

### 1. Leaf: `illegal_unrepaired_leaf_placement` (seen on BOOST 5V, CHARGER)

```
warning: parallel leaf solve failed for /1dfeec7c-...:
  No accepted routed leaf artifact produced after N round(s):
  leaf_pre_stamp_legality_repair
```

Per-round signature in `debug.json`:

```json
{"round_index": 0, "routed": false,
 "routing": {"reason": "illegal_unrepaired_leaf_placement",
             "failed_internal_nets": ["/+5V", "/VBAT"]}}
```

What's happening: the force-directed placer + passive-ordering pass
produce a layout the legality repair can't fix in its budget of passes
(`leaf_legality_repair_passes`, default 24). When acceptance requires
"legal placement before stamping," the round is rejected outright and
the PCB never reaches FreeRouting.

### 2. Leaf: silent failures when a worker raises

When one leaf's solve raises, `solve_subcircuits` re-raises a
`RuntimeError` for the whole round, so **other leaves that succeeded in
that round never get `_persist_solution` called**. Their
`debug.json` keeps older data, so from the GUI's point of view the
experiment round produced zero leaf artifacts. This is what makes R2
in the current run look like "6/7 accepted" on the score plot but zero
persisted leaves on disk.

### 3. Parent: `parent_geometry_validation_failed before stamping`

Signature in `compose_subcircuits` stderr:

```json
{"parent_geometry_validation_failed": true,
 "geometry_validation": {
   "outside_components": [
     {"ref": "BT1", "bbox": {...}, "outside_body": true},
     {"ref": "BT2", "bbox": {...}, "outside_body": true}]}}
```

Cause: `enable_board_size_search=True` mutates `board_width_mm` /
`board_height_mm` each round. Some mutations produce a board too small
for the composed leaf bounding boxes. The packer still places leaves,
but at least one leaf extends past the board outline. The validator
catches it before stamping. Rounds with dimensions like
`99.5 × 70.3 mm` for a `76.8 × 43.7` battery holder + 5 other leaves
are the typical trigger.

### 4. Parent: `illegal_routed_geometry`

Signature in stdout: `parent_status: rejected (illegal_routed_geometry)`.
Board was routed but acceptance gate rejected the resulting geometry —
usually overlapping traces, clearance violations, or a fill/zone that
extended past the edge.

---

## Improvement plan

Ordered by expected impact ÷ effort.

### A. Constrain the board-size mutation to feasible ranges  *(biggest win)*

The mutator for `board_width_mm` / `board_height_mm` has a fixed
uniform range from `CONFIG_SEARCH_SPACE`. It doesn't know the minimum
size needed to hold the current leaves.

Fix: at the start of each experiment round, compute the
"tight-packing lower bound" from the solved leaf bounding boxes
(sum of areas × a fudge factor, or a simple bin-packing width/height
floor), and clamp the mutation to at least that. Only relax when the
user explicitly widens `_mutation_bounds.board_*`.

Files to touch:
- `kicraft/cli/autoexperiment.py` — around the `_mutate_config` call
  site; compute the floor from `accepted_leaf_artifacts` if available,
  otherwise from the previous round's accepted leaves.
- `kicraft/autoplacer/config.py` — add a `min_feasible_from_leaves()`
  helper that returns a `(min_w, min_h)` pair given solved leaf bboxes.

Expected effect: no more "BT1/BT2 outside" rejections; parent geometry
rejections drop to near zero.

### B. Decouple leaf persistence from round-level failures  *(fix #2 above)*

When a worker fails in parallel solve, persist the ones that succeeded
before raising. Currently `main()` raises before the `for solved in
solved_results: persisted.append(_persist_solution(solved, cfg))`
block runs.

Fix: move the persistence loop before the `RuntimeError` raise so
every leaf that completed gets its debug.json + renders written, then
raise afterwards with the partial result still on disk. The runner
still sees a non-zero exit (autoexperiment marks the round as failed)
but the Monitor tab has real per-leaf data to display.

Files to touch:
- `kicraft/cli/solve_subcircuits.py` — the `main()` function around
  lines 1215–1230 (the `if failed_by_path: raise` block).

Expected effect: selecting a partially-failed round on the plot no
longer shows blanket "failed" leaves; the user sees which leaves
actually failed vs. which succeeded.

### C. Render the pre-route leaf PNG even when acceptance rejects  *(UI-facing)*

The leaf solver only emits `round_NNNN_routed_*.png` after a
successful route. When the acceptance gate rejects a placement before
routing, there is no PNG for that round at all — the Round Timeline
in the Monitor shows an empty placeholder.

Fix: unconditionally render `round_NNNN_pre_route_front_all.png`
after placement, before the acceptance decision. The render is ~100 ms
and is already implemented — it's just gated on success. Ungate it.

Files to touch:
- `kicraft/autoplacer/brain/leaf_routing.py` around line 359, 379 —
  the render calls that build `round_prefix`.

Expected effect: every round in the Round Timeline has a thumbnail,
failed rounds included. Clicking a failed round shows the placement
that got rejected, which is exactly what the user needs to diagnose
the rejection.

### D. Loosen `leaf_pre_stamp_legality_repair` budget when needed  *(diagnostic)*

24 passes isn't always enough on a dense leaf with a narrow board.
The repair isn't doing anything silly — it's just running out of
budget. Rather than a blanket increase (which slows every leaf), make
it adaptive: if the repair hasn't converged, retry with 2× the budget
once.

Files to touch:
- `kicraft/autoplacer/brain/leaf_size_reduction.py` — the
  `leaf_legality_repair_passes` computation.
- `kicraft/autoplacer/brain/leaf_placement.py` — the retry logic
  around the repair loop.

Expected effect: fewer
`illegal_unrepaired_leaf_placement` rejections at the cost of ~50 ms
per retry on hard cases.

### E. Surface the rejection reason in the Monitor tab  *(UI polish)*

When a leaf round fails, the user currently sees a red "FAILED TO
ROUTE" badge with no reason. The reason is already in `debug.json` at
`extra.all_rounds[N].routing.reason`. Surface it in the node detail
panel, alongside the pre-route render.

Files to touch:
- `kicraft/gui/components/node_detail.py` — when `status ==
  "routing_failed"`, pull the dominant `routing.reason` from
  `node.rounds` and render it below the main image.

Expected effect: user knows at a glance whether a leaf failed because
of legality, FreeRouting timeout, acceptance gate, etc.

---

## Rough order of work

1. **B** (persistence) — small, unblocks better Monitor data
2. **A** (board-size floor) — medium, eliminates parent-geometry
   rejections
3. **C** (always-render pre-route) — small, fills the last
   thumbnail gap
4. **E** (surface reason) — small, cosmetic but high value
5. **D** (adaptive repair) — larger, do last; want telemetry from
   A–C first

No code changes in this doc — only the plan. Implementation would be
separate commits per item above.
