# Handoff — 2026-04-17 — Scheduling Upgrade + Parallel Failure Handling + GUI Surfacing Closeout

## 1. What was completed

This session continued the LLUPS hierarchical leaf-subcircuit scheduling and failure-handling work, then followed through into the GUI / monitor path, and finally closed the intermittent timing-summary extraction issue. The main result is that scheduling is no longer just a simple prior-round ordering hint, parallel leaf failure handling now preserves successful work instead of broadly re-running everything, the GUI now has first-pass scheduling / long-pole surfacing, and bounded hierarchical runs now again persist stable populated timing summaries.

### Scheduling work completed
- Re-read and verified the recent scheduling-related changes in:
  - `LLUPS/.claude/skills/kicad-helper/scripts/solve_subcircuits.py`
  - `LLUPS/.claude/skills/kicad-helper/scripts/autoexperiment.py`
  - `LLUPS/CHANGELOG.md`
- Upgraded the scheduling heuristic in `autoexperiment.py` beyond simple prior `leaf_total_s` ordering.
- The new scheduling score now combines multiple signals, including:
  - prior `leaf_total_s`
  - prior `route_total_s`
  - prior `freerouting_s`
  - trace count
  - via count
  - internal-net count
  - failed-round count
  - accepted-round count
  - whether the leaf had failures
  - whether the leaf is a long-pole candidate
  - whether the leaf is historically trivial / zero-internal-net
- The new heuristic is intended to:
  - prioritize historically slow routed leaves first
  - prioritize failure-prone leaves early enough to fail fast
  - deprioritize trivial leaves later when they are unlikely to affect tail latency
- Added persisted scheduling detail into round artifacts via:
  - `leaf_timing_summary.schedule_recommendation`
  - `leaf_timing_summary.scheduled_leafs`
  - score-note summaries such as `leaf_schedule_top5=...`

### Leaf metadata / timing extraction work completed
- Extended `solve_subcircuits.py` so each solved leaf now persists:
  - `scheduling_metadata`
  - `failure_summary`
- Added per-leaf scheduling metadata fields including:
  - `sheet_name`
  - `instance_path`
  - `internal_net_count`
  - `external_net_count`
  - `historically_trivial_candidate`
  - `trace_count`
  - `via_count`
  - `effective_rounds`
  - `fast_smoke_mode`
  - `best_round_index`
  - `best_score`
  - `leaf_total_s`
  - `route_total_s`
  - `freerouting_s`
  - `accepted_round_count`
  - `failed_round_count`
- Added per-leaf failure summary fields including:
  - `had_failures`
  - `failure_count`
  - `accepted_round_count`
  - `failed_round_count`
  - `unique_reasons`
  - per-failure rows with round / seed / reason / failed nets / timing
- Persisted this metadata into:
  - `solved_layout.json`
  - leaf debug payloads
  - round-level timing summaries extracted by `autoexperiment.py`

### Parallel failure-handling work completed
- Changed the process-pool worker path in `solve_subcircuits.py` so worker failures are returned as structured per-leaf failures instead of immediately collapsing the whole batch.
- Preserved successful parallel leaf results even when one or more leaves fail.
- Changed infrastructure-failure recovery behavior so serial recovery is limited to unfinished leaves after a pool/infrastructure problem, instead of broad full serial re-execution.
- Added clearer aggregated failure reporting when failures remain after preserving successful work.
- This reduces wasted work and makes failures easier to interpret without silently weakening correctness.

### JSON extraction robustness completed
- Hardened `autoexperiment.py` JSON extraction from `solve_subcircuits.py` stdout.
- This was necessary because leaf solving emits mixed stdout logs before the final JSON payload.
- The previous extraction path could miss the JSON payload and produce empty `leaf_timing_summary`.
- The extraction logic was first updated to scan decodable JSON objects from mixed output and keep the last successfully decoded dict-shaped payload.
- To make this stable, `solve_subcircuits.py` now emits explicit JSON markers when `--json` is used:
  - `===SOLVE_SUBCIRCUITS_JSON_START===`
  - `===SOLVE_SUBCIRCUITS_JSON_END===`
- `autoexperiment.py` now prefers:
  - explicit solve JSON markers first
  - dict payloads containing `leaf_subcircuits` or `results` before generic fallback parsing
- This closed the main intermittent timing-summary extraction issue caused by mixed stdout logs.

### GUI / monitor surfacing completed
- Extended `gui/db.py` so round records now persist and return `leaf_timing_summary`.
- Added a new Scheduling tab in `gui/pages/analysis.py`.
- The analysis Scheduling tab now surfaces:
  - latest recommended leaf order
  - latest long-pole leaves
  - latest imbalance / max-leaf / total-leaf timing summary cards
  - recent per-round scheduling trend summaries
- Updated `gui/pages/monitor.py` so live status can show:
  - top scheduled leaves
  - top long-pole leaves
  - next-priority scheduling hint
- Extended `autoexperiment.py` live-status payloads so `hierarchy.leaf_timing_summary` is available to the monitor path.

## 2. What remains next, in priority order

### Priority 1 — optional GUI refinement
The GUI / monitor surfacing is now in place and the upstream timing-summary extraction is stable again in bounded verification.

Recommended next work:
- add failure-prone leaf summaries
- add scheduling-score columns / badges
- add acceptance / failure history badges
- consider adding a dedicated monitor card for:
  - current long pole
  - next scheduled leaf
  - current imbalance ratio

### Priority 2 — refine scheduling inputs further
The first-pass GUI surfacing is useful, and the next highest-value work is now refinement rather than recovery.

Recommended next work:
- add failure-prone leaf summaries
- add scheduling-score columns / badges
- add acceptance / failure history badges
- consider adding a dedicated monitor card for:
  - current long pole
  - next scheduled leaf
  - current imbalance ratio

### Priority 3 — refine scheduling inputs further
The new heuristic is materially better than simple ordering, but it is still static.

Recommended next work:
- add acceptance history across multiple rounds, not just the current extracted leaf payload
- consider parent-impact weighting
- consider richer topology signals beyond current counts
- consider whether zero-trace / zero-via leaves should be penalized differently from zero-internal-net leaves
- consider whether scheduling should use rolling history instead of max-only aggregation

### Priority 4 — improve failure classification in round artifacts
Parallel failure handling is better, but the round artifacts still do not clearly distinguish all failure classes.

Recommended next work:
- distinguish:
  - infrastructure failures
  - expected routed-leaf validation failures
  - smoke-mode acceptable partial outcomes
- persist a clearer per-round failure summary into hierarchical round JSON
- consider adding a top-level `leaf_failure_summary` section to round artifacts

## 3. Exact files touched in this session

- `LLUPS/.claude/skills/kicad-helper/scripts/solve_subcircuits.py`
- `LLUPS/.claude/skills/kicad-helper/scripts/autoexperiment.py`
- `LLUPS/gui/db.py`
- `LLUPS/gui/pages/analysis.py`
- `LLUPS/gui/pages/monitor.py`
- `LLUPS/CHANGELOG.md`
- `LLUPS/.claude/skills/kicad-helper/scripts/HANDOFF_2026-04-17_timing_verification_and_smoke_mode.md`

## 4. Exact verification commands run and outcomes

### Diagnostics
Ran diagnostics on:
- `LLUPS/.claude/skills/kicad-helper/scripts/solve_subcircuits.py`
- `LLUPS/.claude/skills/kicad-helper/scripts/autoexperiment.py`
- `LLUPS/gui/db.py`
- `LLUPS/gui/pages/analysis.py`
- `LLUPS/gui/pages/monitor.py`

Outcomes:
- `autoexperiment.py` was clean in the checked environment after the live-status follow-through.
- GUI / DB files showed environment-related unresolved-import diagnostics in the checker environment.
- `solve_subcircuits.py` still showed environment-related / legacy warnings, including unresolved `pcbnew` import in static analysis and some unused-import / module-order warnings.
- No new blocking diagnostics from the GUI scheduling surfacing changes were identified.
- No new blocking diagnostics were introduced by the final timing-summary extraction fix.

### Required leaf-pipeline verification
Ran:
- `python3 .claude/skills/kicad-helper/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route --fast-smoke --workers 0`

Outcome:
- completed successfully
- no Python traceback
- real routed leaf path remained active
- accepted artifacts were written under `.experiments/subcircuits/`
- canonical `leaf_routed.kicad_pcb` artifacts persisted
- `solved_layout.json` persisted
- all six accepted leaf subcircuits completed and were summarized

### Required hierarchical verification
Ran:
- `python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb --schematic LLUPS.kicad_sch --rounds 2 --leaf-rounds 1 --fast-smoke --workers 0`

First outcome:
- completed without traceback
- but `leaf_timing_summary` was empty because mixed stdout logs prevented JSON extraction from the leaf solver output

Follow-up fix:
- hardened JSON extraction in `autoexperiment.py`

Re-ran:
- `python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb --schematic LLUPS.kicad_sch --rounds 2 --leaf-rounds 1 --fast-smoke --workers 0`

Second outcome:
- completed successfully
- no Python traceback
- `leaf_timing_summary` persisted in round artifacts
- scheduling notes remained present
- scheduled ordering metadata persisted
- round 2 scored higher than round 1 in that bounded run

GUI follow-through verification:
- updated the GUI DB layer and monitor live-status path
- re-ran:
  - `python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb --schematic LLUPS.kicad_sch --rounds 2 --leaf-rounds 1 --fast-smoke --workers 0`

Latest outcome:
- completed successfully
- no Python traceback
- live status payload now includes `hierarchy.leaf_timing_summary`
- GUI-facing persistence path for `leaf_timing_summary` is now wired through the DB layer

Final extraction-fix verification:
- updated `solve_subcircuits.py` to emit explicit JSON markers for `--json`
- updated `autoexperiment.py` to prefer explicit solve JSON markers and solve-shaped payloads
- re-ran:
  - `python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb --schematic LLUPS.kicad_sch --rounds 2 --leaf-rounds 1 --fast-smoke --workers 0`

Final outcome:
- completed successfully
- no Python traceback
- round artifacts again contained populated:
  - `leaf_timing_summary.leafs`
  - `leaf_timing_summary.long_pole_leafs`
  - `leaf_timing_summary.schedule_recommendation`
  - `leaf_timing_summary.scheduled_leafs`
- the latest bounded run produced a better round-2 score than round 1
- visible long-pole leaves in the latest successful bounded run included:
  - `CHARGER`
  - `LDO 3.3V`
  - `BOOST 5V`

## 5. Open bugs, misleading behaviors, or known limitations

### A. Scheduling is improved but still heuristic
The new scheduling score is stronger than simple prior ordering, but it is still not a true adaptive runtime scheduler.

### B. Runtime improvement is not yet proven stable
The latest bounded run looked more sensible and round 2 scored better, but more runs are needed before claiming consistent wall-clock improvement.

### C. Some extracted topology fields are still weak
The extracted timing summary now carries more scheduling metadata, but some topology counts currently depend on persisted scheduling metadata and may need refinement if richer complexity signals are desired.

### D. GUI / monitor surfacing is now present and backed by stable bounded-run timing data
The new scheduling and long-pole metadata is now surfaced in the analysis / monitor path, and the marker-based extraction fix restored stable populated timing rows in bounded verification.

### E. Parallel failure handling is improved, not perfect
Successful parallel work is now preserved, and broad serial re-execution is avoided in more cases, but hard infrastructure failures can still require partial serial recovery for unfinished leaves.

### F. Static analysis still shows environment-related warnings
`solve_subcircuits.py` still reports some non-blocking static-analysis issues in the checker environment, especially around KiCad/runtime imports.

### G. Some scheduling metadata fields are still weaker than ideal
The main remaining quality issue in this thread is refinement-oriented:
- some extracted scheduling rows still show weak topology metadata such as `trace_count` / `via_count`
- this does not block the pipeline, but it is a good future refinement target if this work resumes later

## 6. Next recommended implementation step

This scheduling / timing / GUI thread is now in a reasonable stopping state.

Recommended sequence if this work resumes later:
1. refine topology-count quality in scheduling metadata (`trace_count` / `via_count`)
2. enrich the Scheduling tab with failure-prone leaf summaries and scheduling-score details
3. refine failure classification in round artifacts
4. run a few more bounded experiments to evaluate whether the heuristic consistently improves tail behavior

## 7. Suggested implementation direction for the next pass

A strong next pass would likely:
- keep the current weighted scheduling heuristic as the baseline
- keep the current GUI scheduling surfacing
- treat timing-summary extraction as stable unless new evidence appears
- add explicit round-level failure summaries
- distinguish infrastructure failures from expected routed validation failures
- preserve current correctness guarantees
- continue using bounded fast-smoke verification while iterating on scheduling policy

Good candidate files for the next pass:
- `LLUPS/.claude/skills/kicad-helper/scripts/autoexperiment.py`
- `LLUPS/gui/db.py`
- `LLUPS/gui/pages/analysis.py`
- `LLUPS/gui/pages/monitor.py`
- `LLUPS/gui/components/score_chart.py`

## 8. Continuity note

The main conclusion from this session is:

- leaf scheduling is now materially better than simple prior-round ordering
- per-leaf scheduling and failure metadata is now persisted
- successful parallel leaf work is now preserved when individual leaves fail
- broad full serial re-execution after parallel failure has been reduced
- the GUI and monitor path now have first-pass scheduling / long-pole surfacing
- explicit solve JSON markers now stabilize bounded timing-summary extraction
- bounded routed verification still passes
- bounded hierarchical fast-smoke verification still passes
- this thread is now in a good enough stopping state for a focus change
- the next highest-value step, if this work resumes later, is refinement: better topology metadata, richer GUI scheduling details, and clearer failure summaries