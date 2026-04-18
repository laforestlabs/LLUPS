# Handoff — 2026-04-17 — Timing Instrumentation + Hardware Utilization Follow-Through

## 1. What was completed

This session continued the observability work and then pivoted into timing instrumentation because the user reported that the smoke test was taking far too long and CPU utilization was poor.

### A. Board-first observability work completed earlier in the session
The following observability improvements were implemented before the timing pivot:

- leaf candidate-round metadata was extended to expose:
  - round-specific KiCad board snapshot paths
  - round-specific preview image paths
  - compact machine-readable routing/log summary fields
- analysis UI leaf candidate-round inspector was extended to show:
  - board source paths
  - router / reason / failed / skipped state
  - routed and failed internal-net summaries
  - routed copper length summary
- live monitor / status payloads were extended to expose:
  - leaf round board paths
  - parent stamped board path
  - parent routed board path
- parent artifact metadata/debug payloads were extended to expose:
  - `parent_pre_freerouting.kicad_pcb`
  - `parent_routed.kicad_pcb`
  - parent preview paths
  - parent board paths
- analysis parent inspector was extended to show stamped/routed parent board paths
- round-detail payloads in `autoexperiment.py` were extended to carry parent preview-path and parent board-path context

### B. Timing instrumentation work completed in this session
The user then asked for:
1. instrumentation showing timing breakdown of the pipeline
2. a timing tab in the experiment manager
3. a plan to improve hardware utilization / parallelization

Implementation work completed:

#### `solve_subcircuits.py`
Added timing instrumentation to leaf solve / route flow, including fields such as:

- `placement_solve_s`
- `passive_ordering_s`
- `post_ordering_legality_repair_s`
- `placement_scoring_s`
- `legality_repair_s`
- `stamp_pre_route_board_s`
- `freerouting_s`
- `pre_route_validation_s`
- `pre_route_render_diagnostics_s`
- `import_routed_copper_s`
- `routed_validation_s`
- `routed_render_diagnostics_s`
- `route_local_subcircuit_total_s`
- `leaf_extraction_s`
- `local_solver_config_s`
- `leaf_size_reduction_s`
- `leaf_total_s`
- `persist_solution_s`
- `solve_one_round_total_s`

Also:
- `SolveRoundResult` now carries `timing_breakdown`
- `SolveRoundResult.to_dict()` now includes `timing_breakdown`
- `_route_local_subcircuit(...)` was changed from returning only a routing dict to returning:
  - `(routing_dict, route_timing_dict)`

#### `autoexperiment.py`
Added round-level timing instrumentation for:

- `solve_subcircuits_total`
- `compose_subcircuits_total`
- `parent_route_total`
- `score_round_total`
- `round_total`

Also:
- `HierarchyRound` now has `timing_breakdown`
- `_write_round_detail(...)` persists `timing_breakdown`
- `_write_frame_metadata(...)` persists `timing_breakdown`
- `_score_round(...)` now accepts optional `timing_breakdown`
- timing helper utilities were added:
  - `_timing_now()`
  - `_record_timing(...)`
  - `_format_timing_breakdown(...)`
- timing notes are appended into `score_notes`
- console timing logs were added, e.g.:
  - `[timing] round N solve_subcircuits_total=...s`

#### `gui/db.py`
Added DB persistence for timing data:

- new column:
  - `timing_breakdown_json`
- migration support in `_ensure_round_columns()`
- `Round.timing_breakdown` property
- `Database.add_round(...)` now stores timing breakdown
- `Database.get_round_dicts(...)` now returns timing breakdown

#### `gui/components/score_chart.py`
Added timing chart builders:

- `build_timing_figure(...)`
- `build_leaf_timing_figure(...)`
- `build_timing_summary_figure(...)`

#### `gui/pages/analysis.py`
Added a new `Timing` tab under experiment analysis with:

- round timing breakdown chart
- leaf pipeline timing chart
- timing summary chart
- timing summary panel
- “most render-heavy rounds” summary

### C. Documentation / continuity updates completed
Updated:

- `CHANGELOG.md`
- `docs/monitoring-guide.md`
- `docs/subcircuits_pipeline_design.md`
- `.claude/skills/kicad-helper/scripts/NEXT_STEPS.md`

The changelog now records:
- board-first observability work
- parent-stage board-path observability extension
- timing instrumentation + timing tab work

---

## 2. What remains next, in priority order

### Priority 1 — verify and debug the timing implementation
The timing work was implemented, but not fully verified end-to-end.

Next agent should:

1. read the edited files carefully
2. run diagnostics on the edited files
3. fix any issues introduced by the timing work
4. run the required verification command with a bounded timeout:
   - `python3 .claude/skills/kicad-helper/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route`
5. confirm that timing data is actually present in:
   - leaf debug payloads
   - round payloads
   - GUI DB round records
   - analysis timing tab inputs

### Priority 2 — implement a faster smoke-test mode
The user explicitly said the smoke test is taking too long and appears render-heavy.

Next agent should add a fast smoke-test / minimal-render mode, likely by:

- minimizing or skipping per-round render generation
- skipping contact sheets in smoke mode
- skipping DRC overlays in smoke mode
- keeping only:
  - canonical board snapshots
  - minimal accepted/final previews
  - essential validation / artifact persistence

Likely places to inspect:
- `solve_subcircuits.py`
- `autoplacer/brain/subcircuit_render_diagnostics.py`
- any CLI/config plumbing for route/render behavior

### Priority 3 — improve hardware utilization / parallelization
The user reported low CPU utilization and wants better use of hardware resources.

Next agent should:

1. inspect current leaf parallelization behavior in `solve_subcircuits.py`
2. determine whether the bottleneck is:
   - render/export subprocesses
   - serial leaf round execution
   - worker under-allocation
   - queue imbalance / long-pole leaves
3. propose and, if safe, implement improvements such as:
   - better leaf task scheduling
   - separate compute/router/render concurrency controls
   - more aggressive leaf parallelization
   - optional parallel candidate rounds for expensive leaves
4. surface enough timing/utilization data in the GUI to justify the changes

### Priority 4 — optionally extend timing visibility into monitor page
The analysis timing tab may be enough, but if the user wants live timing visibility, consider adding timing summaries to `gui/pages/monitor.py`.

---

## 3. Exact files touched

### Pipeline / scripts
- `LLUPS/.claude/skills/kicad-helper/scripts/solve_subcircuits.py`
- `LLUPS/.claude/skills/kicad-helper/scripts/autoexperiment.py`
- `LLUPS/.claude/skills/kicad-helper/scripts/compose_subcircuits.py`
- `LLUPS/.claude/skills/kicad-helper/scripts/NEXT_STEPS.md`

### GUI
- `LLUPS/gui/db.py`
- `LLUPS/gui/components/score_chart.py`
- `LLUPS/gui/pages/analysis.py`
- `LLUPS/gui/pages/monitor.py`

### Docs / continuity
- `LLUPS/docs/monitoring-guide.md`
- `LLUPS/docs/subcircuits_pipeline_design.md`
- `LLUPS/CHANGELOG.md`

---

## 4. Exact verification commands already run and outcomes

### Required subcircuit pipeline verification command
Ran multiple times:

```bash
python3 .claude/skills/kicad-helper/scripts/solve_subcircuits.py LLUPS.kicad_sch \
  --pcb LLUPS.kicad_pcb \
  --rounds 1 \
  --route
```

### Outcomes observed across attempts
- earlier attempts timed out before full completion
- later attempt was manually stopped by the user because it was taking too long for a smoke test
- in all captured runs before stop/timeout:
  - no Python traceback was visible in captured output
  - leaf solving was going through the real routed path
  - repeated pre-route and routed render generation was visible
  - real leaf boards were being stamped under `.experiments/subcircuits/`
  - round-specific KiCad board snapshots were confirmed on disk

### Confirmed artifact evidence
Confirmed files existed under a leaf artifact directory such as:

- `round_0000_leaf_pre_freerouting.kicad_pcb`
- `round_0000_leaf_routed.kicad_pcb`

This confirms board-first round snapshot persistence is functioning.

### Important caveat
No fully completed end-to-end verification run was captured after the timing changes. The next agent must not assume the timing implementation is correct until verified.

---

## 5. Open bugs, misleading behaviors, or known limitations

### A. Timing implementation is not yet fully verified
The timing changes are broad and touch:
- pipeline payloads
- GUI DB persistence
- analysis charts

There may still be:
- diagnostics issues
- payload-shape mismatches
- chart assumptions that need cleanup

### B. Smoke test is still too slow
The user explicitly stopped the last run because it was taking too long for a smoke test.

Strong suspicion:
- render/export work is a major contributor

But this still needs to be confirmed with the new timing data.

### C. CPU utilization is still poor
The user provided a CPU graph showing:
- one core doing most of the work
- most cores mostly idle

This suggests:
- leaf work may not be parallelizing effectively
- or expensive stages are serial / subprocess-bound
- or render/export dominates and is not saturating CPU

### D. Parent-stage observability is improved but not fully audited
Board-path observability was extended into parent artifacts and analysis UI, but not every possible parent failure/intermediate path has been audited.

### E. The timing tab exists in analysis, but live monitor timing is still limited
If the user wants live timing visibility during a run, more monitor-side work may be needed.

---

## 6. Next recommended implementation step

### Immediate next step
Do a verification/debug pass on the timing work before adding more features.

Recommended sequence:

1. run diagnostics on:
   - `solve_subcircuits.py`
   - `autoexperiment.py`
   - `gui/db.py`
   - `gui/components/score_chart.py`
   - `gui/pages/analysis.py`
2. fix any issues introduced by the timing work
3. run the required verification command again with a bounded timeout
4. inspect persisted payloads to confirm timing data is present
5. once timing data is confirmed, implement a fast smoke-test / minimal-render mode
6. then use the timing data to improve hardware utilization / parallelization

---

## 7. Suggested prompt for the next agent

Use something close to this:

> Continue the LLUPS timing-instrumentation and hardware-utilization work.
>
> Context:
> - Timing instrumentation was added to `solve_subcircuits.py` and `autoexperiment.py`
> - Timing persistence was added to `gui/db.py`
> - Timing charts/tab work was added to `gui/pages/analysis.py` and `gui/components/score_chart.py`
> - Board-first observability work was already extended across leaf and parent artifacts
> - The user explicitly wants smoke tests to be faster and CPU utilization to be better
>
> Your tasks:
> 1. Read and verify the recent edits in:
>    - `LLUPS/.claude/skills/kicad-helper/scripts/solve_subcircuits.py`
>    - `LLUPS/.claude/skills/kicad-helper/scripts/autoexperiment.py`
>    - `LLUPS/gui/db.py`
>    - `LLUPS/gui/components/score_chart.py`
>    - `LLUPS/gui/pages/analysis.py`
>    - `LLUPS/CHANGELOG.md`
> 2. Run diagnostics on the edited files and fix any issues introduced by the timing work.
> 3. Run the required verification command:
>    - `python3 .claude/skills/kicad-helper/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route`
>    Use a bounded timeout, but gather enough evidence to validate timing payloads if possible.
> 4. Confirm timing data is actually persisted into leaf/debug/round payloads and visible to the GUI data path.
> 5. If timing data is working, implement a fast smoke-test / minimal-render mode:
>    - reduce or skip nonessential per-round render generation
>    - keep canonical board snapshots and essential accepted/final previews
> 6. Then inspect current leaf parallelization behavior and improve hardware utilization:
>    - identify why CPU utilization is low
>    - propose and, if safe, implement improvements to worker scheduling / concurrency controls
> 7. Update `CHANGELOG.md` and leave another concise handoff before stopping.
>
> Known caveats:
> - Do not assume the timing implementation is correct until verified.
> - Prefer board-first observability to remain intact while optimizing render cost.
> - The user wants both faster smoke tests and better CPU utilization.

---

## 8. Relevant continuity notes

### User intent that should remain central
The user wants:
- better observability for both human PCB review and machine log review
- KiCad board files to remain the visual source of truth
- smoke tests to be much faster
- better CPU utilization from leaf parallelization and calculations

### Design direction that should not be lost
- `.kicad_pcb` is the preferred visual source of truth
- `solved_layout.json` is the preferred machine-readable canonical artifact
- PNGs are derived convenience artifacts
- timing data should be used to justify optimization changes, not guessed from intuition alone

---