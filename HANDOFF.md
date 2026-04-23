# Session Handoff: Experiment Manager UI Refresh

Date: 2026-04-23
Pushed: **not yet** — local commits on both repos.

## Scope

User asked for two Experiment Manager GUI changes:

1. **Setup → Placement & Routing tab**: merge the separate "placement
   procedures" and "mutation search bounds" sections into a single
   per-group table with columns `Parameter | Start | Min | Max`.
2. **Monitor tab**: add a parent-score plot at the top tracking score
   per autoexperiment round. Clicking a point filters the leaves below
   (renders and per-leaf round timelines) to that round's data. Default
   = the best round so far.

Full plan with per-file reasoning: `docs/experiment-manager-ui-refresh.md`.

## Commits (local only, KiCraft submodule)

1. `a43ff2f` gui(setup): unify placement params and mutation bounds into one table
2. `2704779` cli(solve): accumulate all_rounds across experiment rounds
3. `410840d` gui(monitor): parent-round score plot with per-round leaf filtering

LLUPS top-level repo still shows the submodule pointer drift + the new
plan doc as unstaged — not yet committed in LLUPS main.

## What changed

### Part 1 — Unified parameter table (`kicraft/gui/pages/setup.py`)

- `_placement_routing_panel` rewritten. One set of expansions (grouped by
  `group` in `PLACEMENT_PARAMS`); inside each expansion a 4-col grid
  (`2fr 1.5fr 1.5fr 1.5fr`) with header row `Parameter | Start | Min | Max`.
- `_render_param_row` renders one param as a row. Non-numeric (bool/text/
  list) params and params absent from `CONFIG_SEARCH_SPACE` show "—" in
  Min/Max cells.
- Old `_mutation_bounds_panel` deleted. "Reset All Bounds" button moved
  up to the unified panel header.
- `state.py`: added `parent_spacing_mm` to `PLACEMENT_PARAMS` — it's in
  `CONFIG_SEARCH_SPACE` but was previously only visible via the separate
  bounds panel.

### Part 2a+b — Round accumulation (`kicraft/cli/solve_subcircuits.py`, `kicraft/cli/autoexperiment.py`)

Existing behavior: each autoexperiment round invokes `solve_subcircuits`
which **overwrites** each leaf's `debug.json` with fresh `all_rounds`
indexed `0..effective_rounds-1`. Prior rounds were lost.

New behavior:
- `solve_subcircuits` takes `--experiment-round N` (default 0 = unknown).
- Before the round loop in `_solve_leaf_subcircuit`, it reads any prior
  `debug.json` for the leaf, finds `max(round_index) + 1`, and uses that
  as `base_offset`. New rounds get indices `base_offset + 0..N-1`, so
  `round_NNNN_*.png` filenames never collide.
- `SolvedLeafSubcircuit` gained `experiment_round` and `prior_rounds`
  fields.
- `_persist_solution` stamps each new round dict with `experiment_round=N`,
  merges with `prior_rounds` (dedup by `round_index`), sorts, and writes.
- `autoexperiment._build_solve_cmd` gained `experiment_round` kwarg; both
  call sites pass `round_num`.

Backward-compat: rounds without `experiment_round` key → treated as 0.

### Part 2c+d+e — Monitor UI

- `kicraft/gui/components/parent_score_chart.py` (new): `build_parent_round_figure`
  (plotly), `parent_score_chart` (with `plotly_click` handler), `pick_best_round`.
- `kicraft/gui/components/pipeline_graph.py`: `RoundInfo.experiment_round`
  field, populated from debug.json. `gather_pipeline_state` gained
  `selected_round: int | None` kwarg. When set and the leaf has rounds
  matching that experiment round, rounds list is narrowed to that round
  and `best_render` is the highest-scoring thumbnail from it. Fallback
  to unfiltered when no matches (preserves display for legacy artifacts).
- `kicraft/gui/pages/monitor.py`: new parent-chart container above the
  graph/detail row. State dicts for `selected_parent_round` (value +
  `user_pinned` bool). On each tick: if user hasn't pinned, auto-follow
  the best round; if pinned, show "Auto-track best" button to revert.
  Plotly click fires `_on_parent_round_select`. Status label shows
  "Viewing R<N> (best is R<M>)" when a pinned selection isn't the best.

## Runtime validation — what is and isn't proven

- All modules `import` cleanly.
- Unit-level: loaded `.experiments/experiments.jsonl` (3 historical
  rounds), `pick_best_round` returned 2, `build_parent_round_figure`
  produced a 2-trace figure with x=[1,2,3] y≈[72.78, 78.46, 59.46].
- Unit-level: `gather_pipeline_state(selected_round=2)` on existing
  artifacts didn't raise; 6 leaves rendered with best_render populated.
  Historical debug.json has no `experiment_round` stamp so filtering
  matched 0 rounds and correctly fell back to showing all.
- **Not proven**: live browser render, plotly click handler firing,
  "Auto-track best" button behavior, multi-round accumulation with
  fresh experiment. Need to start a small experiment (2 rounds × 2
  leaf rounds, no fast-smoke so renders exist) and:
  1. Watch the plot grow from 1 → 2 points.
  2. Click the older point, confirm leaves below update to that round's
     renders only.
  3. Confirm "Auto-track best" button appears, click it, confirm
     selection snaps back to best.
  4. Inspect one leaf's `debug.json` — confirm rounds from both
     experiment rounds are present and stamped.

## How to resume

1. Start the GUI: `python -m kicraft.gui` (currently hardcoded port 8080
   — an earlier dev session may still hold the port; check with
   `ss -tlnp | grep :8080` and kill any stragglers).
2. Setup tab → Placement & Routing: visually confirm the new 4-column
   tables look right. Pay attention to:
   - Row widths on the Routing group (trace-width entries are a mix of
     searchable floats and non-searchable text like `gnd_zone_net`,
     which should dash out).
   - The "Reset All Bounds to Defaults" button still reloads the page.
3. Kick off a small autoexperiment (2 rounds × 2 leaf rounds). Watch
   the Monitor tab do its thing.
4. If anything looks off, `docs/experiment-manager-ui-refresh.md` has the
   change rationale file-by-file. `git log --oneline -4` inside `KiCraft`
   maps commits to parts.

## Follow-ups worth considering

- The `Zone Pour` group was missing from `group_icons` in the previous
  Setup code (it still rendered, just with the default `settings` icon).
  I added an entry; purely cosmetic.
- Legacy debug.json entries (written before this session) have no
  `experiment_round` stamp. The filter code treats them as round 0 and
  falls back to "show all" when no matches exist. If you want historical
  artifacts to surface too, we could group them into round 0 explicitly
  and add a "(pre-instrumentation)" badge on the plot. Not done.
- The parent-round plot doesn't persist the user's click across page
  reloads. That's fine for now; adding it would be an extra session-state
  entry.
- I did not push to remote — the user didn't ask, and the token budget
  is near the self-imposed limit for this session.

## Prior handoff

`HANDOFF.md` previously covered the parent-composition quality work
(finished and pushed on 2026-04-22). That content is fully superseded
by the next_agent handoff / commit log; intentionally removed here to
keep this doc scoped to the current session.
