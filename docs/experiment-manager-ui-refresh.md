# Experiment Manager UI Refresh

Status: **in progress** — started 2026-04-23.

Two user-requested changes to the KiCraft experiment manager GUI:

1. **Unified placement/routing parameter table** — merge the "Placement & Routing Procedures" and "Mutation Search Bounds" sections in the Setup tab into a single per-group table where each parameter is one row with columns `Parameter | Start | Min | Max`.
2. **Parent-round score plot on the Monitor tab** — add a top-level plot tracking the parent score across experiment rounds; clicking a point filters the leaf cards and per-leaf round timelines below to only show that round's solves. Default to the best round so far.

---

## Part 1 — Unified parameter table (Setup → Placement & Routing)

### Current state
`KiCraft/kicraft/gui/pages/setup.py`:
- `_placement_routing_panel` (lines 163–192) — renders each `PLACEMENT_PARAMS` entry as a number/switch/input via `_render_param_control`, grouped into collapsible expansions.
- `_mutation_bounds_panel` (lines 258–334) — renders one row per entry in `CONFIG_SEARCH_SPACE` (a subset of the placement params) with min/max number inputs, grouped into a separate set of expansions.

These two panels are stacked separated by a `ui.separator()` (setup.py:34).

### Target
A single set of group expansions. Inside each expansion, a 4-column grid:

```
Parameter | Start | Min | Max
<label>   | <n>   | <n> | <n>
...
```

- "Start" column = the control from `_render_param_control` (number/switch/input). Bool and text/list types have no min/max — those rows render only a start-value cell spanning the remaining columns and display "—" in min/max, or the min/max cells are hidden per-row.
- Rows for parameters NOT in `CONFIG_SEARCH_SPACE` still show start value but min/max are not applicable ("—").
- Rows for parameters in `CONFIG_SEARCH_SPACE` wire the min/max inputs to `_on_bounds_change`.
- Bounds state still lives in `state.mutation_bounds`; start value still lives in `state.placement_config`.

### Implementation
- Drop `ui.separator` and the call to `_mutation_bounds_panel` from the `placement_tab` panel (setup.py:34–35).
- Rewrite `_placement_routing_panel` to iterate `PLACEMENT_PARAMS` grouped by `group`, and for each row render the 4-column layout. Keep the `CONFIG_SEARCH_SPACE` / `normalize_bounds` wiring from `_mutation_bounds_panel` inline.
- Move the "Reset All Bounds" button and the preamble copy from `_mutation_bounds_panel` into the unified panel header.
- Delete `_mutation_bounds_panel` (or keep as thin wrapper until callers are clean) and `_on_bounds_change` is reused as-is.
- Preserve tooltips and behavior: changing start value to the default still pops the overlay key (`_on_param_change`), and bounds normalize via `normalize_bounds`.

### Files touched
- `KiCraft/kicraft/gui/pages/setup.py`

---

## Part 2 — Parent-round score plot + round-filtered leaf view (Monitor tab)

### Current state
`KiCraft/kicraft/gui/pages/monitor.py` monitor layout:
- Top status row (Start/Stop/Kill/status/phase/timing/progress).
- Two-column body: pipeline graph (leaves + root) on left, node detail (score plot + round timeline) on right.
- Timer polls every 2 s and rebuilds graph/detail when fingerprint changes.

Leaf round data comes from `components/pipeline_graph.py::_build_rounds_from_debug` which reads `subcircuits/<leaf>/debug.json → extra.all_rounds` (list of round records with `round_index`, `score`, `routed`). Thumbnails are discovered from `renders/round_XXXX_{routed,pre_route}_front_all.png`.

Parent scores per experiment round live in `.experiments/experiments.jsonl` (one JSON line per parent round, key `score`, `round_num`).

There is no current link between a leaf round's `round_index` and the autoexperiment `round_num` it belongs to — `solve_subcircuits.py` fully overwrites `debug.json` each experiment round with `range(effective_rounds)` starting from 0, and the GUI currently just displays everything it finds.

### Target
On Monitor tab, above the existing pipeline graph row:
- **Parent Score vs Round** line+marker plot (plotly, same styling as `components/score_chart.py::build_score_figure`). One point per completed autoexperiment round. "Best so far" overlay dotted line. X-axis = round_num, Y-axis = score.
- Selecting a point (plotly click) sets `selected_round` state. Default = the round with the current best score.
- The pipeline graph (leaf cards + root card) and the detail panel (score plot + round timeline) below update to show only the data from the selected experiment round.

### Data-model change
Tag each leaf round record with the experiment round it belongs to so the GUI can filter. Two approaches:

- **Preferred**: add `--experiment-round N` flag to `cli/solve_subcircuits.py`, stamp each round's `to_dict()` output with `"experiment_round": N`. Autoexperiment passes its current `round_num`.
- **Fallback**: if the above is scoped out, the GUI can infer by grouping `round_index` values into buckets of `leaf_rounds` size per experiment round. Less accurate when `leaf_min_route_rounds` raises the effective count, so we avoid it.

`debug.json` is overwritten each experiment round, which means historical leaf renders for prior parent rounds will persist only via the `renders/round_XXXX_*.png` files — those are not wiped. So filtering requires that `all_rounds` contain entries for all historical rounds, not just the current experiment round. We therefore also need to **accumulate `all_rounds` across experiment rounds**:

- Before writing `debug.json`, read any existing `all_rounds` and prepend them, offsetting new `round_index` values so they continue from the last one.
- Each run's records get stamped with the new `experiment_round`.
- The "best round" pointer in `debug.json` is updated only if the new run beats the persisted best.

This is implemented in `cli/solve_subcircuits.py` around the `save_debug_payload` call (lines 893–929) and the `_solve_rounds`-style loop (lines 568+).

### Files touched
- `KiCraft/kicraft/cli/solve_subcircuits.py` — accept `--experiment-round`, stamp each round, merge with prior `all_rounds` in existing `debug.json`, adjust render filenames so they don't collide between experiment rounds (use absolute offset on `round_index` when writing `round_XXXX_*.png`).
- `KiCraft/kicraft/cli/autoexperiment.py` — pass `--experiment-round` when building the solve command (line ~1927 `_build_solve_cmd`).
- `KiCraft/kicraft/gui/components/pipeline_graph.py` — `RoundInfo` gains `experiment_round: int | None`; `_build_rounds_from_debug` reads it; `gather_pipeline_state` accepts optional `selected_round: int | None` that filters leaf `rounds` and picks `best_render` from that round's artifacts.
- `KiCraft/kicraft/gui/components/node_detail.py` — score plot and round timeline respect the filtered `rounds` list (no change needed if filtering happens upstream in `gather_pipeline_state`).
- `KiCraft/kicraft/gui/pages/monitor.py` — add parent-score plot at top; add `selected_round` state; wire plot click handler; pass `selected_round` into `gather_pipeline_state`; rebuild graph/detail on selection change.
- `KiCraft/kicraft/gui/components/score_chart.py` — reuse `build_score_figure` or add a compact variant `build_parent_round_figure(rounds, on_click)` with click handler wired for nicegui plotly.

### Best-round default
On load and on every new completed round, if no explicit user click, re-select the round with the maximum score. If the user has clicked a specific round, keep that selection until a new round lands AND that new round is the new best — then offer a "Jump to best" button rather than auto-jumping (user complained in the past about UI auto-resetting — verify in implementation).

---

## Rollout / safety
- Migrate-in-place: an existing `debug.json` without `experiment_round` stamps is still readable; treat missing stamps as belonging to round 0.
- Existing GIF/render artifact tests stay green (per user memory: never skip GIF render).
- Do NOT change default `render_png` or `save_round_details` toggles.

## Progress checklist
- [x] Part 1: unified parameter table in `setup.py` (commit `a43ff2f`)
- [x] Part 2a: `--experiment-round` flag + `all_rounds` accumulation in `solve_subcircuits.py` (commit `2704779`)
- [x] Part 2b: `autoexperiment.py` passes `--experiment-round round_num` (commit `2704779`)
- [x] Part 2c: `RoundInfo.experiment_round`, filter plumbing in `pipeline_graph.py` (commit `410840d`)
- [x] Part 2d: parent-score plot + round selection in `monitor.py` (commit `410840d`)
- [x] Part 2e: round-filtering respected in `node_detail.py` — no code change needed; detail panel already reads `node.rounds` which is filtered upstream by `gather_pipeline_state`.
- [ ] **Live smoke test pending**: needs a fresh 2-round × 2-leaf-rounds autoexperiment to confirm plot updates as rounds complete, click-to-filter works, and the "Auto-track best" button resets a pin. Unit-level tests pass: parent chart builds from real `experiments.jsonl`, `gather_pipeline_state(selected_round=N)` filters without raising.
- [x] Commit each part separately; HANDOFF.md written.

## Commit strategy
Four commits, in order:
1. `gui: unify placement/routing params and mutation bounds into one table`
2. `cli: accumulate all_rounds across experiment rounds with experiment_round stamp`
3. `gui: add parent-round score plot to monitor tab with round filtering`
4. `docs: handoff + close out UI refresh`
