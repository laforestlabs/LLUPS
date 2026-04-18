Continue the LLUPS hierarchical subcircuit scheduling / timing / hardware-utilization work.

## Context

Recent work established a practical bounded routed smoke path and began turning timing data into scheduling signals.

### What is already implemented

#### In `solve_subcircuits.py`
- `--fast-smoke` exists and completes bounded routed verification.
- `--workers 0` now means auto-select worker count.
- `--leaf-order` now exists and accepts repeated preferred leaf selectors by:
  - sheet name
  - sheet file
  - instance path
- leaf selection can now be reordered before execution using the preferred order list.
- parallel leaf solving already exists via process pool execution.
- if parallel leaf solving fails, there is now a serial fallback path with a warning.

#### In `autoexperiment.py`
- `--workers 0` now means auto-select.
- `--fast-smoke` is passed through to leaf solving.
- effective worker count is computed once and propagated into:
  - solve command construction
  - live status payloads
- per-leaf timing summaries are extracted from `solve_subcircuits.py` JSON output.
- hierarchical round artifacts now persist `leaf_timing_summary`, including:
  - `leaf_count`
  - `total_leaf_time_s`
  - `avg_leaf_time_s`
  - `max_leaf_time_s`
  - `imbalance_ratio`
  - `long_pole_leafs`
  - per-leaf timing rows
- scheduling hints are generated from prior timing data.
- previous-round scheduling recommendations are now passed into the next round’s leaf solve command via `--leaf-order`.

### What has been verified

#### Successful bounded routed smoke verification
This command completed successfully:
`python3 .claude/skills/kicad-helper/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route --fast-smoke`

Confirmed:
- no Python traceback
- real routed leaf solving, not heuristic fallback
- canonical `leaf_routed.kicad_pcb` artifacts persisted
- `solved_layout.json` persisted
- nonessential derived renders were skipped as intended

#### Successful hierarchical fast-smoke verification
This command completed successfully:
`python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb --schematic LLUPS.kicad_sch --rounds 1 --leaf-rounds 1 --fast-smoke --workers 0`

Confirmed:
- worker auto-selection was active
- round artifacts were written under `.experiments/rounds/`
- `leaf_timing_summary` was persisted in round JSON
- long-pole leaves were dominated mainly by:
  - `freerouting_s`
  - routed / pre-route validation time
- render work was no longer the dominant cost in fast-smoke mode

#### Two-round scheduling verification
This command also completed:
`python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb --schematic LLUPS.kicad_sch --rounds 2 --leaf-rounds 1 --fast-smoke --workers 0`

Confirmed:
- previous-round scheduling recommendations are now passed forward
- scheduling is now applied at the leaf submission order level
- however, the latest two-round run did not yet show a clear runtime win

## Current limitations

1. Scheduling is still lightweight.
   - It reorders leaf submission order.
   - It does not yet implement richer adaptive scheduling or failure-aware queue management.

2. Routed-leaf failure sensitivity is still present.
   - One failing routed leaf can still waste parallel work.
   - Serial fallback improves resilience but can duplicate work after a parallel failure.

3. The current scheduling heuristic is still too simple.
   - It should likely consider more than prior total leaf time.

4. GUI surfacing of `leaf_timing_summary` is still pending.

## Your tasks

### Priority 1 — improve the scheduling heuristic
Read and verify the recent scheduling-related edits in:
- `LLUPS/.claude/skills/kicad-helper/scripts/solve_subcircuits.py`
- `LLUPS/.claude/skills/kicad-helper/scripts/autoexperiment.py`
- `LLUPS/CHANGELOG.md`

Then improve scheduling beyond simple prior-round ordering.

Consider weighting:
- prior `leaf_total_s`
- prior `route_total_s`
- prior `freerouting_s`
- trace count
- via count
- failure history
- acceptance history
- whether a leaf is historically a long pole
- whether a leaf has zero internal nets and should be deprioritized

A good target is a scheduling score that prioritizes:
- historically slow routed leaves first
- historically failure-prone leaves early enough to fail fast
- trivial leaves later if they do not affect tail latency

### Priority 2 — improve routed-leaf failure handling
Reduce wasted work when one routed leaf fails.

Investigate whether you can safely improve one or more of:
- failure aggregation instead of immediate broad failure
- preserving successful parallel leaf results when one leaf fails
- avoiding full serial re-execution after a late parallel failure
- clearer per-leaf failure summaries in round artifacts
- distinguishing:
  - hard infrastructure failures
  - expected routed-leaf validation failures
  - smoke-mode acceptable partial outcomes

Be careful not to weaken correctness guarantees silently.

### Priority 3 — verify with bounded runs
Run bounded verification after changes.

Preferred commands:
- `python3 .claude/skills/kicad-helper/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route --fast-smoke --workers 0`
- `python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb --schematic LLUPS.kicad_sch --rounds 2 --leaf-rounds 1 --fast-smoke --workers 0`

Check for:
- no Python traceback
- real routed leaf path still active
- canonical artifacts still persisted
- `leaf_timing_summary` still present
- scheduling notes still present
- if possible, evidence that scheduling is improving tail behavior or at least producing more sensible ordering

### Priority 4 — optional GUI/status surfacing
If time permits, surface `leaf_timing_summary` into:
- GUI analysis views
- live status payloads
- monitor-side summaries

At minimum, make long-pole leaves visible without opening raw round JSON.

## Important files likely involved

### Core pipeline
- `LLUPS/.claude/skills/kicad-helper/scripts/solve_subcircuits.py`
- `LLUPS/.claude/skills/kicad-helper/scripts/autoexperiment.py`

### Optional GUI follow-through
- `LLUPS/gui/db.py`
- `LLUPS/gui/components/score_chart.py`
- `LLUPS/gui/pages/analysis.py`
- `LLUPS/gui/pages/monitor.py`

### Continuity
- `LLUPS/CHANGELOG.md`
- `LLUPS/.claude/skills/kicad-helper/scripts/HANDOFF_2026-04-17_timing_verification_and_smoke_mode.md`

## Notes on current evidence

Recent completed hierarchical fast-smoke runs showed long-pole leaves such as:
- `CHARGER`
- `BOOST 5V`
- `LDO 3.3V`

And their dominant costs were mainly:
- `freerouting_s`
- validation time

This suggests the next scheduling pass should optimize for routed tail latency, not render cost.

## Required continuity before stopping

Before ending your session:
1. update `CHANGELOG.md`
2. update the durable handoff file
3. record:
   - what changed
   - what remains
   - exact files touched
   - exact verification commands run
   - outcomes
   - open limitations
   - next recommended step

## Success criteria for this next pass

A strong result would include most of:
- improved scheduling heuristic implemented
- better failure handling for parallel leaf solves
- bounded verification still passing
- persisted scheduling / long-pole metadata still intact
- clearer evidence for why CPU utilization should improve in later runs