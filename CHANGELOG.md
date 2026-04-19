# LLUPS Engineering Changelog


## 2026-04-19: Session 3 -- pcbnew fix, full pipeline verified, test expansion

### Environment fix
- Fixed venv: changed include-system-site-packages from false to true in .venv/pyvenv.cfg
- pcbnew (KiCad 9.0.8) now accessible from venv at /usr/lib64/python3.13/site-packages/
- Fixed list_footprints.py: added argparse so --help works without loading a board

### Full pipeline verification
- All 6 leaves solve, route, and get accepted (USB INPUT, CHARGER, BATT PROT, BOOST 5V, LDO 3.3V, BT1)
- Parent composition works: 37 components, 233 child traces, 18 parent interconnect traces
- Parent stamped, routed via FreeRouting, accepted -- Phase 4 MVP complete
- solve-hierarchy end-to-end in 41s with --skip-leaves --route

### New modules
- brain/leaf_acceptance.py: configurable acceptance gate module (7 gates: board_exists, no_python_exception, no_shorts, no_illegal_geometry, drc_clearance, anchor_completeness, routed_board)

### Test expansion (187 tests, up from 158)
- tests/test_subcircuit_extractor.py (14 tests): extraction, net partition, envelope, translation
- tests/test_hierarchy_levels.py (6 tests): _compute_levels for 1-4 level hierarchies
- tests/test_subcircuit_composer.py (7 tests): composition, copper preservation, interconnects
- tests/test_leaf_acceptance.py (10 tests): all gate paths, config from dict

### Project rules
- Added text formatting rule to AGENTS.md: no special Unicode characters (emdash, smart quotes, etc.)

### Files touched
- .venv/pyvenv.cfg (venv config)
- AGENTS.md (new formatting rule)
- ROADMAP.md (updated checkboxes and handoff)
- CHANGELOG.md (this entry)
- KiCraft/kicraft/cli/list_footprints.py (argparse fix)
- KiCraft/kicraft/autoplacer/brain/leaf_acceptance.py (new)
- KiCraft/tests/test_subcircuit_extractor.py (new)
- KiCraft/tests/test_hierarchy_levels.py (new)
- KiCraft/tests/test_subcircuit_composer.py (new)
- KiCraft/tests/test_leaf_acceptance.py (new)


## 2025-07-12: KiCraft v0.1.0 — Published to GitHub + CI + Tests

### Completed
- **Published KiCraft to GitHub**: https://github.com/laforestlabs/KiCraft
- **Updated LLUPS submodule URL** from local path to GitHub remote
- **GitHub Actions CI**: ruff lint + pytest on Python 3.10/3.12/3.13
- **Expanded test suite**: 96 tests (7 import, 39 config, 47 types, 10 CLI help)
- **Lint cleanup**: ruff auto-fixed 90 issues (unused imports, f-strings); added ignore rules for E402/E702/E741
- **Tagged v0.1.0** on KiCraft repository

### Files touched
- KiCraft: `.github/workflows/ci.yml`, `tests/test_config.py`, `tests/test_types.py`, `tests/test_cli_help.py`, `pyproject.toml`, 30 source files (lint fixes)
- LLUPS: `.gitmodules`

### Verification
- CI green on GitHub Actions (all 3 Python versions)
- `pytest -v` — 96 passed, 2 skipped (pcbnew-dependent)
- `ruff check kicraft/` — all checks passed
- Fresh clone with `--recurse-submodules` works correctly


## 2025-07-12: Phases 6b + 6c — KiCraft extracted to standalone package

### Completed
- **Phase 6b: Extract KiCraft to standalone repository**
  - Created `/home/jason/Documents/KiCraft/` with proper Python package
  - `kicraft/` package: autoplacer, scoring, gui, cli subpackages
  - `pyproject.toml` with 30+ CLI entry points (solve-subcircuits, autoexperiment, etc.)
  - All imports converted from bare `autoplacer.*` to `kicraft.autoplacer.*`
  - Removed all `sys.path` hacks (kept pcbnew path helper)
  - 7/7 import smoke tests pass
  - Git repo initialized (`9992d38`)

- **Phase 6c: Reintegrate into LLUPS**
  - Removed `.claude/skills/KiCraft/scripts/` (62 files) and `gui/` (19 files) from LLUPS
  - Added `KiCraft/` as git submodule
  - `pip install -e KiCraft/` provides all CLI entry points
  - Updated AGENTS.md and SKILL.md for new paths
  - Pipeline verification: 6 leaves solved + routed, parent assembled, zero tracebacks

### Files touched
- Removed: `.claude/skills/KiCraft/scripts/**`, `gui/**` (81 files)
- Added: `KiCraft/` (submodule, 91 files)
- Modified: `AGENTS.md`, `.claude/skills/KiCraft/SKILL.md`, `docs/CLEANUP_PLAN.md`

### Verification
- `solve-subcircuits LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route` — all leaves routed, parent composed
- `python -m pytest tests/test_import.py -v` — 7/7 pass
- CLI entry points working: `solve-subcircuits --help`, `clean-experiments --help`, `render-pcb --help`

## 2026-04-18: Final Timing-Summary Extraction Fix + Closeout

### Completed
- Added explicit JSON payload markers to `solve_subcircuits.py` when `--json` is used:
  - `===SOLVE_SUBCIRCUITS_JSON_START===`
  - `===SOLVE_SUBCIRCUITS_JSON_END===`
- Updated `autoexperiment.py` solve-output parsing to prefer:
  - explicit solve JSON markers first
  - dict payloads containing `leaf_subcircuits` or `results` before generic fallback parsing
- This closes the main intermittent timing-summary extraction issue caused by mixed stdout logs from leaf solving.
- Re-ran bounded hierarchical verification after the marker-based fix.
- Confirmed that round artifacts again persist populated:
  - `leaf_timing_summary.leafs`
  - `leaf_timing_summary.long_pole_leafs`
  - `leaf_timing_summary.schedule_recommendation`
  - `leaf_timing_summary.scheduled_leafs`
- This also means the earlier GUI / monitor scheduling surfacing now has stable upstream data to display.

### Verification findings
- Re-ran:
  - `python3 .claude/skills/KiCraft/scripts/autoexperiment.py LLUPS.kicad_pcb --schematic LLUPS.kicad_sch --rounds 2 --leaf-rounds 1 --fast-smoke --workers 0`
- Confirmed:
  - no Python traceback
  - hierarchical run completed successfully
  - round 2 completed with populated `leaf_timing_summary`
  - long-pole leaves were again visible in round artifacts
  - the latest bounded run produced a better round-2 score than round 1
- In the latest successful bounded run, visible long-pole leaves included:
  - `CHARGER`
  - `LDO 3.3V`
  - `BOOST 5V`

### Closeout status
- The immediate scheduling / failure-handling / GUI-surfacing thread is now in a reasonable stopping state.
- The pipeline has:
  - improved scheduling heuristics
  - better parallel failure preservation
  - stable timing-summary extraction
  - GUI / monitor surfacing for scheduling and long-pole data
- Remaining issues are now more refinement-oriented than unblockers.

### Remaining follow-up
1. If this work resumes later, refine topology-count quality in scheduling metadata (`trace_count` / `via_count` are still weaker than ideal in some extracted rows).
2. Optionally enrich the Scheduling tab with:
   - failure-prone leaf summaries
   - scheduling-score columns
   - acceptance/failure history badges
3. If focus shifts elsewhere, this branch is now in a good enough state to pause without losing the main scheduling/timing thread.

## 2026-04-18: GUI Scheduling + Long-Pole Surfacing Follow-Through

### Completed
- Extended the GUI data path so round records can persist `leaf_timing_summary` in the local experiment database.
- Updated `gui/db.py` to store and return `leaf_timing_summary` alongside existing hierarchical round metadata.
- Added a new Scheduling tab in the analysis view.
- The analysis Scheduling tab now surfaces:
  - latest recommended leaf order
  - latest long-pole leaves
  - latest imbalance / max-leaf / total-leaf timing summary cards
  - recent per-round scheduling trend summaries
- Updated the monitor view so live status can show:
  - top scheduled leaves
  - top long-pole leaves
  - next-priority scheduling hint
- Extended the live status payload in `autoexperiment.py` so `hierarchy.leaf_timing_summary` is available to the monitor path.

### Verification findings
- Re-ran bounded hierarchical verification with:
  - `python3 .claude/skills/KiCraft/scripts/autoexperiment.py LLUPS.kicad_pcb --schematic LLUPS.kicad_sch --rounds 2 --leaf-rounds 1 --fast-smoke --workers 0`
- Confirmed:
  - no Python traceback
  - hierarchical run still completed
  - live status payload now includes `hierarchy.leaf_timing_summary`
  - GUI-facing persistence path for `leaf_timing_summary` is now wired through the DB layer
- During verification, the run still showed an existing upstream limitation:
  - some bounded runs continue to produce empty `leaf_timing_summary.leafs` rows even though scheduling recommendation fields are still present

### Current limitation
- GUI surfacing is now in place, but the underlying timing payload is still inconsistent in some runs.
- In particular, some bounded hierarchical runs still persist:
  - empty `leaf_timing_summary.leafs`
  - empty `long_pole_leafs`
  while still producing `schedule_recommendation` / `scheduled_leafs`
- This means the GUI can now display the scheduling structures, but the upstream extraction path still needs another debugging pass for full fidelity.

### Why this mattered
- The user asked for GUI improvements next.
- This pass makes scheduling and long-pole information visible without opening raw round JSON.
- It also closes an important observability gap between:
  - pipeline artifact generation
  - DB persistence
  - analysis view
  - monitor/live-status view

### Remaining follow-up
1. Debug why some bounded hierarchical runs still produce empty `leaf_timing_summary.leafs` despite valid scheduling recommendation output.
2. Once the upstream payload is stable, enrich the Scheduling tab with:
   - failure-prone leaf summaries
   - scheduling-score columns
   - acceptance/failure history badges
3. Consider adding a dedicated monitor card for:
   - current long pole
   - next scheduled leaf
   - current imbalance ratio

## 2026-04-17: Scheduling Heuristic Upgrade + Parallel Leaf Failure Preservation

### Completed
- Upgraded hierarchical leaf scheduling beyond simple prior-round ordering.
- Extended `solve_subcircuits.py` to persist per-leaf scheduling metadata and failure summaries alongside solved leaf artifacts.
- Added scheduling-related leaf metadata including:
  - `internal_net_count`
  - trivial-leaf detection
  - accepted / failed round counts
  - per-leaf total timing
  - routed timing
  - FreeRouting timing
- Extended `autoexperiment.py` timing extraction so round-level `leaf_timing_summary` rows now also carry:
  - trace / via counts
  - internal-net counts
  - failure-history signals
  - trivial-leaf signals
  - long-pole flags
  - embedded scheduling / failure metadata
- Replaced the lightweight ordering heuristic with a weighted scheduling score that prioritizes:
  - historically slow routed leaves first
  - leaves with high `freerouting_s` and routed time first
  - leaves with heavier topology earlier
  - historically failure-prone leaves early enough to fail fast
  - trivial / zero-internal-net leaves later
- Persisted scheduled ordering details into round artifacts via:
  - `leaf_timing_summary.schedule_recommendation`
  - `leaf_timing_summary.scheduled_leafs`
  - score-note summaries such as `leaf_schedule_top5=...`
- Improved parallel leaf failure handling in `solve_subcircuits.py` so worker-level leaf failures are captured per leaf instead of immediately discarding all successful parallel work.
- Preserved successful parallel leaf results when individual routed leaves fail.
- Limited serial recovery to missing leaves after infrastructure-level parallel failures instead of broad full serial re-execution.
- Raised clearer aggregated leaf-failure summaries when failures remain after preserving successful work.
- Hardened `autoexperiment.py` JSON extraction so mixed stdout logs from leaf solving no longer suppress `leaf_timing_summary` parsing.

### Verification findings
- Verified bounded routed leaf solving still completes successfully with:
  - `python3 .claude/skills/KiCraft/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route --fast-smoke --workers 0`
- Confirmed from the completed bounded leaf run:
  - no Python traceback
  - real routed leaf solving remained active
  - accepted artifacts were written under `.experiments/subcircuits/`
  - canonical `leaf_routed.kicad_pcb` artifacts persisted
  - `solved_layout.json` persisted
- Verified bounded hierarchical execution with:
  - `python3 .claude/skills/KiCraft/scripts/autoexperiment.py LLUPS.kicad_pcb --schematic LLUPS.kicad_sch --rounds 2 --leaf-rounds 1 --fast-smoke --workers 0`
- Confirmed from the completed hierarchical run:
  - no Python traceback
  - `leaf_timing_summary` persisted in round artifacts
  - scheduling notes remained present
  - scheduled ordering metadata was persisted
  - round 2 completed with a better overall score than round 1 in the latest bounded run
- The latest completed hierarchical run showed meaningful long-pole timing structure, with leaves such as:
  - `CHARGER`
  - `LDO 3.3V`
  - `USB INPUT`
  still dominating routed tail time mainly through `freerouting_s` and validation cost.

### Current limitation
- The new scheduling score is stronger than simple ordering, but it is still a static heuristic rather than a true adaptive runtime scheduler.
- The latest bounded run showed sensible ordering and preserved metadata, but it is still too early to claim a stable wall-clock improvement across runs.
- Per-leaf topology counts in the extracted timing summary currently depend on persisted scheduling metadata and may still need refinement if richer topology signals are desired.
- GUI / monitor surfacing of the new scheduling and long-pole metadata is still pending.
- Parallel failure handling is improved, but hard infrastructure failures can still force partial serial recovery for unfinished leaves.

### Why this mattered
- This pass moves the pipeline closer to failure-aware, tail-latency-aware leaf scheduling instead of simple submission reordering.
- The pipeline now preserves more useful work when parallel leaf solving encounters failures.
- Round artifacts now better explain why a given leaf was prioritized, which makes later tuning more evidence-driven.
- The bounded hierarchical run now provides clearer evidence for how CPU utilization should improve over time:
  - long-pole routed leaves are pushed earlier
  - trivial leaves are delayed
  - failure-prone leaves are surfaced earlier instead of wasting the tail of the batch

### Remaining follow-up
1. Surface `leaf_timing_summary`, long-pole leaves, and scheduling recommendations in the GUI / monitor path.
2. Refine scheduling inputs further, potentially adding:
   - acceptance history across rounds
   - parent-impact weighting
   - richer topology / net-complexity signals
3. Distinguish infrastructure failures vs expected routed-leaf validation failures more explicitly in hierarchical round artifacts.
4. Consider whether the live-status payload should expose scheduled order and long-pole leaves directly during execution.
5. Re-run more bounded experiments to determine whether the new heuristic consistently improves tail behavior.

## 2026-04-17: Next-Agent Continuation Prompt

The following prompt was prepared for the next agent and should be copied into a durable handoff file if the next session starts fresh:

Continue the LLUPS hierarchical subcircuit scheduling / timing / hardware-utilization work.

Context:
- `solve_subcircuits.py` now supports:
  - `--fast-smoke`
  - worker auto-selection via `--workers 0`
  - preferred leaf ordering via `--leaf-order`
- `autoexperiment.py` now supports:
  - worker auto-selection via `--workers 0`
  - fast-smoke passthrough to leaf solving
  - extraction of `leaf_timing_summary` from `solve_subcircuits.py` JSON output
  - persistence of long-pole leaf timing summaries into round artifacts
  - passing previous-round scheduling recommendations into the next round’s leaf solve command
- Completed hierarchical fast-smoke runs confirmed:
  - bounded routed verification works
  - long-pole leaves are dominated mainly by `freerouting_s` and validation time
  - scheduling hints are now persisted and passed forward
- Current limitation:
  - scheduling is still lightweight and has not yet shown a clear runtime win
  - routed-leaf failure sensitivity is still present
  - GUI surfacing of `leaf_timing_summary` is still pending

Your tasks:
1. Read and verify the recent scheduling-related edits in:
   - `LLUPS/.claude/skills/KiCraft/scripts/solve_subcircuits.py`
   - `LLUPS/.claude/skills/KiCraft/scripts/autoexperiment.py`
   - `LLUPS/CHANGELOG.md`
2. Improve the scheduling heuristic beyond simple prior-round ordering. Consider weighting:
   - prior `leaf_total_s`
   - prior `freerouting_s`
   - trace / via counts
   - failure history
3. Improve routed-leaf failure handling so one failing leaf does not waste as much parallel work or force broad serial re-execution.
4. Verify the updated behavior with bounded runs, preferably including:
   - `python3 .claude/skills/KiCraft/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route --fast-smoke --workers 0`
   - `python3 .claude/skills/KiCraft/scripts/autoexperiment.py LLUPS.kicad_pcb --schematic LLUPS.kicad_sch --rounds 2 --leaf-rounds 1 --fast-smoke --workers 0`
5. Confirm that round artifacts still persist:
   - canonical `leaf_routed.kicad_pcb`
   - `solved_layout.json`
   - `leaf_timing_summary`
   - scheduling notes / long-pole notes
6. If time permits, surface `leaf_timing_summary` into the GUI / live status path.
7. Update `CHANGELOG.md` and leave another concise durable handoff before stopping.

## 2026-04-17: Long-Pole Leaf Timing Extraction + Scheduling Hints

### Completed
- Extended `autoexperiment.py` so it now extracts per-leaf timing summaries from the JSON output of `solve_subcircuits.py`.
- Added long-pole leaf timing extraction that records, per accepted leaf:
  - `leaf_total_s`
  - `route_total_s`
  - `freerouting_s`
  - render time contribution
  - placement-side time contribution
- Added a leaf timing summary payload to hierarchical round records so round artifacts now persist:
  - total leaf time
  - average leaf time
  - max leaf time
  - imbalance ratio
  - top long-pole leaves
  - per-leaf timing rows
- Added scheduling-hint generation that recommends a leaf solve order biased toward historically slower / heavier leaves first.
- Added first-pass scheduling support in `solve_subcircuits.py` via `--leaf-order`, allowing the hierarchical runner to pass a preferred leaf execution order by sheet name, sheet file, or instance path.
- Updated `autoexperiment.py` to pass the previous round’s recommended leaf order into the next round’s leaf solve command.
- Persisted these scheduling hints and long-pole summaries into round detail metadata and score notes.
- Kept the earlier worker auto-selection and fast-smoke passthrough improvements in place so the new timing summaries can be observed under practical bounded runs.

### Investigation findings
- The main low-CPU-utilization issue is not simply “parallelism missing everywhere”.
- After smoke-mode improvements, the strongest remaining bottleneck is a combination of:
  - long-pole routed leaves
  - per-leaf routing / validation cost
  - failure sensitivity in the routed acceptance path
- A completed hierarchical fast-smoke run now produces enough timing structure to identify which leaves are dominating wall-clock time.
- In the latest completed run, the extracted long-pole leaves were dominated by routed leaves such as:
  - `CHARGER`
  - `BOOST 5V`
  - `LDO 3.3V`
- The extracted timing breakdown showed that these long-pole leaves are dominated primarily by:
  - `freerouting_s`
  - routed / pre-route validation time
  rather than by render work in fast-smoke mode.
- The resulting imbalance ratio and long-pole list now give the pipeline a concrete basis for future scheduling policy instead of guessing from CPU graphs alone.

### Verification findings
- A completed hierarchical fast-smoke run was used to verify the new long-pole extraction path.
- The run completed successfully and produced round artifacts under `.experiments/rounds/`.
- The round detail payload now includes a top-level `leaf_timing_summary` section.
- The round score notes now include:
  - `leaf_timing_total_s=...`
  - `leaf_timing_avg_s=...`
  - `leaf_timing_max_s=...`
  - `leaf_timing_imbalance_ratio=...`
  - `leaf_schedule_recommendation=...`
  - `leaf_long_poles=...`
- A two-round hierarchical fast-smoke run was also used to verify that scheduling recommendations are now passed forward into subsequent leaf solve commands.
- This confirms that the hierarchical runner can now persist machine-readable scheduling hints and begin applying them across rounds.

### Current limitation
- The new scheduling support is still lightweight:
  - it reorders leaf submission order
  - it does not yet implement a richer adaptive scheduler or failure-aware queue management
- Parallel execution can still be dominated by one difficult leaf, leaving other cores idle near the end of a batch.
- Routed-leaf failure sensitivity is still present.
- Full GUI surfacing of the new `leaf_timing_summary` payload is still pending.
- The latest two-round verification did not yet show a clear runtime win from the applied ordering, so more iterations and better scheduling heuristics are still needed.

### Why this mattered
- The user explicitly wants better CPU utilization and better use of available hardware.
- These changes move the project from intuition-based tuning toward evidence-based scheduling.
- The new long-pole extraction makes it much easier to answer:
  - which leaves are dominating wall-clock time?
  - is routing or validation the real bottleneck?
  - which leaves should be scheduled earlier to reduce tail latency?
- The new `--leaf-order` plumbing means the system can now start turning those answers into actual execution-order changes.
- This creates a concrete foundation for the next scheduling and robustness pass.

### Remaining follow-up
1. Improve the scheduling heuristic beyond simple prior-round ordering, likely weighting:
   - prior `leaf_total_s`
   - prior `freerouting_s`
   - trace / via counts
   - failure history
2. Improve routed-leaf failure handling so one failing leaf does not waste as much parallel work or force broad serial re-execution.
3. Surface `leaf_timing_summary` in the GUI / live status path so long-pole leaves are visible without opening raw round JSON.
4. Verify the updated worker behavior and long-pole timing persistence through the experiment-manager data path end-to-end.
5. Use a durable next-agent prompt so the next session can continue directly from the new scheduling support instead of re-discovering it.

## 2026-04-17: Parallelization Investigation + Worker Auto-Selection Follow-Through

### Completed
- Added a first-pass fast smoke-test mode to `solve_subcircuits.py` via `--fast-smoke`.
- Threaded fast-smoke render controls into `subcircuit_render_diagnostics.py` so leaf diagnostic generation can selectively skip expensive outputs.
- Added configurable switches for:
  - board-view rendering
  - DRC JSON writing
  - DRC report writing
  - DRC overlay rendering
  - comparison contact-sheet generation
- Tightened fast-smoke behavior further so routed leaf verification uses a smoke-specific route-round policy instead of forcing the normal multi-round routed search.
- In fast-smoke mode, the leaf pipeline now preserves canonical board-first artifacts while reducing nonessential render work:
  - keep canonical `.kicad_pcb` artifacts
  - keep `solved_layout.json`
  - keep routed DRC report sidecars
  - skip contact sheets
  - skip DRC overlays
  - skip pre-route board-view rendering
  - skip routed board-view rendering
  - skip routed DRC JSON sidecars
  - quiet board-render stdout when rendering is enabled
- Confirmed the render-diagnostics helper file is clean in diagnostics after the smoke-mode changes.

### Verification findings
- Re-ran the required verification command in fast-smoke mode:

  `python3 .claude/skills/KiCraft/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route --fast-smoke`

- This fast-smoke verification run completed successfully within the bounded timeout.
- The completed run showed:
  - no Python traceback
  - real routed leaf solving, not heuristic fallback
  - accepted artifacts written under `.experiments/subcircuits/`
  - canonical routed leaf boards persisted as `leaf_routed.kicad_pcb`
  - canonical machine-readable artifacts persisted as `solved_layout.json`
  - all six leaf subcircuits solved through the routed path and summarized at the end of the run
- Confirmed artifact behavior after the completed run:
  - no `pre_vs_routed_contact_sheet.png` files were produced
  - no `*drc_overlay.png` files were produced
  - no `routed_front_all.png` preview files were produced
  - canonical `leaf_routed.kicad_pcb` files were produced for routed leaves
  - `solved_layout.json` files remained present
- Confirmed persisted debug payload behavior for fast-smoke artifacts:
  - timing data is present in `debug.json`
  - preview-path fields are empty as expected in fast-smoke mode
  - render-diagnostics payloads explicitly record skipped contact sheets, skipped board views, and skipped overlays

### Current limitation
- Fast smoke mode is now good enough for bounded routed verification, but it is intentionally less visually rich than the default path.
- GUI round-level timing persistence and timing-tab verification are still pending a completed end-to-end hierarchical experiment-manager run.
- `solve_subcircuits.py` still has some non-critical static-analysis complaints in the checker environment, mostly around environment-specific imports and a few legacy warnings.

### Why this mattered
- This change gives the project a practical routed smoke-test path that preserves board-first truth while cutting derived-artifact cost enough to complete verification quickly.
- It confirms that the biggest remaining smoke-test win came from combining render suppression with smoke-specific route-round throttling.
- It also provides a cleaner baseline for the next optimization pass on hardware utilization and worker scheduling.

### Remaining follow-up
1. Verify round-level timing persistence through the experiment-manager DB and analysis timing tab after a completed hierarchical run.
2. Continue refining the new applied scheduling support so prior-round long-pole timing actually improves later-round wall-clock time.
3. Revisit hardware utilization / worker scheduling now that a bounded routed smoke verification path exists.
4. Optionally add a second smoke tier that restores a minimal final routed preview for accepted leaves only.

## 2026-04-17: Timing Verification Follow-Through + Smoke-Test Bottleneck Confirmation

### Completed
- Performed a verification/debug pass on the recent timing-instrumentation follow-through.
- Fixed the main timing implementation breakage in `solve_subcircuits.py` where `_route_local_subcircuit(...)` now returns `(routing_dict, route_timing_dict)` but one size-reduction reroute call site was still treating the result as a plain dict.
- Added the missing `time` import required by the new monotonic timing instrumentation in `solve_subcircuits.py`.
- Tightened a small analysis-page typing issue in the leaf round preview helper so mixed metadata values no longer force an incorrect `dict[str, Path | None]` return type.
- Confirmed that timing data is being written into persisted leaf debug payloads through `debug.json` under `extra.best_round`, `extra.all_rounds`, and `extra.solve_summary`.

### Verification findings
- Re-ran the required verification command with a bounded timeout:

  `python3 .claude/skills/KiCraft/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route`

- The run still did not complete within the bounded timeout, but the captured output again showed:
  - no Python traceback before timeout
  - real routed leaf solving, not heuristic fallback
  - canonical leaf board stamping under `.experiments/subcircuits/`
  - repeated pre-route and routed render generation
- Confirmed persisted artifact files still exist for routed leaves, including `metadata.json`, `debug.json`, and `solved_layout.json` under `.experiments/subcircuits/...`.
- Confirmed `debug.json` now contains `timing_breakdown` payloads for solved rounds.
- Confirmed the current smoke-test bottleneck is still strongly consistent with render-heavy behavior: the timed run output showed repeated pre-route and routed PNG generation plus repeated duplicated render/export logging for the same leaf artifact.

### Current limitation
- A full completed end-to-end verification run still was not captured after the timing changes.
- GUI round-level timing persistence in the experiment-manager database and timing-tab rendering were not re-verified end-to-end in this pass because the bounded solve run did not complete through the full higher-level flow.
- Some static-analysis environment warnings remain dependency-related (`pcbnew`, GUI libs, ORM libs not importable in the checker environment) and were not treated as code regressions.
- There are still a few non-critical static-analysis complaints in `solve_subcircuits.py`; the highest-value runtime breakage was fixed first.

### Why this mattered
- This pass increased confidence that the timing work is at least partially live in persisted leaf artifacts instead of only existing in code.
- The verification output also strengthened the earlier suspicion that smoke-test runtime is being dominated by render/export work rather than by scoring or orchestration overhead alone.
- That means the next optimization pass should focus first on a minimal-render smoke mode before attempting broader concurrency redesign.

### Remaining follow-up
1. Verify that round-level timing data reaches the experiment-manager DB and analysis timing tab after a completed hierarchical run.
2. Continue improving current leaf scheduling / worker allocation now that:
   - fast smoke mode exists
   - worker auto-selection exists
   - long-pole timing extraction exists
   - first-pass applied leaf ordering exists
3. Improve routed-leaf failure handling so one failing leaf does not waste as much parallel work.
4. Add a durable next-agent continuation prompt near the affected pipeline code whenever this work is handed off again.

## 2026-04-17: Timing Instrumentation + Timing Tab Work

### Completed
- Began instrumenting the hierarchical/subcircuit pipeline so smoke-test runtime can be explained instead of guessed.
- Added timing breakdown fields to hierarchical round payloads in the autoexperiment flow.
- Added timing helper utilities and round-level timing capture for:
  - `solve_subcircuits_total`
  - `compose_subcircuits_total`
  - `parent_route_total`
  - `score_round_total`
  - `round_total`
- Began instrumenting the leaf solve pipeline in `solve_subcircuits.py` so round payloads can capture more detailed leaf-stage timings, including placement, legality repair, routing, validation, render diagnostics, size reduction, and persistence.
- Extended GUI persistence so round timing breakdowns can be stored in the local experiment-manager database.
- Added timing visualizations to the analysis UI, including:
  - a round timing breakdown chart
  - a leaf pipeline timing chart
  - a timing summary chart
  - a timing summary panel highlighting render-heavy rounds

### Why this mattered
- The latest smoke-test run took far too long for a verification pass.
- Observed CPU usage suggested the machine was not being utilized effectively.
- The user also observed that rendering/export likely dominates a large fraction of runtime.
- Before changing concurrency policy or smoke-test behavior, the pipeline needs enough timing visibility to show:
  - where time is actually going
  - whether rendering is the dominant bottleneck
  - whether leaf solving is truly parallelizing
  - whether parent stages or scoring are negligible compared with rendering and routing

### Current limitation
- This session focused on instrumentation and GUI surfacing, not yet on the actual smoke-test acceleration policy or concurrency redesign.
- The timing work is in progress and should be verified carefully because it touches both pipeline payloads and GUI persistence/visualization.
- A full completed verification run was not captured in this session after the timing changes.

### Remaining follow-up
1. Verify the timing payload shape end-to-end with a completed run.
2. Add or refine monitor-side timing surfacing if the analysis tab alone is not sufficient.
3. Use the new timing data to identify whether render/export is the dominant smoke-test bottleneck.
4. Implement a faster smoke-test mode, likely by minimizing or deferring nonessential renders.
5. Build a concrete hardware-utilization improvement pass once the timing data confirms where parallelism is being lost.

## 2026-04-17: Parent-Stage Board-Path Observability Extension

### Completed
- Extended the parent-stage observability work so parent artifacts now persist and expose explicit board-path metadata alongside preview images.
- Parent artifact metadata/debug payloads now describe the canonical parent board artifacts more directly, including:
  - `parent_pre_freerouting.kicad_pcb`
  - `parent_routed.kicad_pcb`
  - parent preview image paths when present
- The analysis-side parent inspector was extended so stamped and routed parent views can show the corresponding `.kicad_pcb` source path, not only the rendered PNG.
- Autoexperiment round-detail payloads were extended so round artifacts can carry parent preview-path and parent board-path context, improving correlation between:
  - optimizer logs
  - round summaries
  - live monitor state
  - exact persisted parent board artifacts

### Why this mattered
- The leaf-side observability work established the board-first direction, but parent-stage review still had a gap: the GUI and round payloads could show parent previews without always making the backing KiCad board path explicit.
- That made it harder to answer:
  - which exact parent board produced this preview?
  - is this the stamped parent or the routed parent?
  - which round payload should a machine reviewer correlate with that board?
- This change moves parent review closer to the same standard already being applied to leaf candidate rounds.

### Current limitation
- Parent-stage observability is improved, but not yet fully audited across every possible intermediate parent stage or failure path.
- The required full verification run still did not complete within the available timeout windows in this session, so this entry records implementation progress and partial verification evidence rather than a final end-to-end success claim.

### Remaining follow-up
1. Complete a full verification run that reaches the end of the required hierarchical/subcircuit flow.
2. Confirm final persisted round payloads and parent artifact payloads contain the expected board-path and preview-path fields after a completed run.
3. Continue tightening parent-stage failure-path observability so rejected or failed parent stages remain as inspectable as accepted ones.

## 2026-04-17: Continued Observability Work + Documentation Update

### Completed
- Continued the observability work after the first board-first leaf-round pass.
- Extended the documentation so the project now more explicitly states that:
  - persisted `.kicad_pcb` files are the preferred visual source of truth
  - PNG previews are derived convenience artifacts
  - `solved_layout.json` remains the preferred machine-readable canonical artifact
- Updated monitoring and pipeline-design documentation to describe:
  - round-specific leaf board snapshots
  - canonical accepted leaf and parent board artifacts
  - live status payloads carrying preview paths and board-source paths
  - the intended relationship between human PCB review and machine log review
- Updated the focused next-steps reference so future work stays aligned with the board-first observability direction.
- Tightened `solve_subcircuits.py` fallback routing payloads so routing-exception and routing-disabled cases also carry explicit round board-path fields, keeping the round metadata shape more consistent for downstream review surfaces.

### Verification status
- Re-ran the required verification command twice with longer time budgets:

  `python3 .claude/skills/KiCraft/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route`

- Both verification attempts timed out before full completion.
- In both runs, the captured output showed:
  - no Python traceback before timeout
  - active routed leaf solving through the real routed path
  - repeated pre-route and routed render generation
  - repeated stamping of real leaf boards under `.experiments/subcircuits/`
- Round-specific KiCad board snapshots were confirmed on disk under a leaf artifact directory, including files such as:
  - `round_0000_leaf_pre_freerouting.kicad_pcb`
  - `round_0000_leaf_routed.kicad_pcb`
- This confirms that the new board-first round snapshot persistence is functioning, even though a full end-to-end verification completion was not captured in this session.

### Current limitation
- Full required verification is still incomplete because the solve command did not finish within the available timeout windows.
- Because the run did not complete, this session does not yet record a final successful end-to-end confirmation that:
  - the entire hierarchical/subcircuit run completed
  - accepted routed leaf artifacts fully persisted all new observability fields in their final post-run payloads
  - the parent-stage path completed cleanly under the same verification run

### Remaining follow-up
1. Re-run the required verification flow with an even longer timeout or in a context where the full solve can complete.
2. Confirm final persisted `debug.json` / round payloads contain the new board-path and log-summary fields after a completed run.
3. Extend the same explicit board-first observability model across parent-stage artifacts and parent-stage review surfaces.
4. Keep documentation aligned as parent-stage observability becomes more explicit.

## 2026-04-17: Observability Upgrade for Human PCB Review + Machine Log Review

### Completed
- Continued the observability push so both the GUI reviewer and the optimizer/log reviewer can see more of the real pipeline state instead of inferred summaries alone.
- Extended leaf round metadata so candidate rounds can now carry:
  - round-specific KiCad board snapshot paths
  - round-specific preview image paths
  - compact machine-readable routing/log summary fields
- Tightened the direction that meaningful visual artifacts should point back to real `.kicad_pcb` files, not only copied PNGs or ad hoc JSON-derived preview assumptions.
- Extended analysis-page candidate-round inspection so a reviewer can see more than just score and preview images:
  - board source paths for illegal / pre-route / routed round stages
  - router/reason/failure/skipped state
  - routed and failed internal-net summaries
  - routed copper length summary
- Extended live-status preview discovery so monitor/status payloads can expose actual KiCad board paths alongside preview images for:
  - latest leaf round boards
  - parent stamped board
  - parent routed board
- Extended the monitor page so live preview panels and top-output panels can show the `.kicad_pcb` source paths backing the currently displayed images.

### Why this change mattered
- The user explicitly wants KiCad board files to be the visual source of truth.
- The previous state was better than before, but still too PNG-first and too dependent on nested diagnostic payload structure.
- Human review needs to answer:
  - what exact board file produced this image?
  - what stage is this board from?
  - did this round really route, fail, or get skipped?
- Machine/log review needs to answer:
  - which nets failed?
  - what router outcome was recorded?
  - what board snapshot corresponds to that outcome?
- These additions move the pipeline toward a more inspectable and less ambiguous artifact model.

### Current limitation
- This is not yet a full artifact-rule audit across every parent and round-specific stage.
- Leaf round observability was the first target because it most directly affects candidate-round inspection and search-trust UX.
- Parent-stage observability still needs a similar audit so every meaningful parent stage consistently persists and exposes board-first artifacts.

### Remaining follow-up
1. Finish the parent-stage observability audit so all meaningful parent stages expose explicit `.kicad_pcb` paths and board-derived renders.
2. Prefer round-specific board snapshots as the primary source for candidate-round previews everywhere, not only as supplemental metadata.
3. Add richer machine-readable summaries for parent routing outcomes and composition-stage transitions so log review can correlate failures with exact board artifacts.
4. Re-run the required hierarchical/subcircuit verification flow and record outcomes after the current code changes.
5. If the session ends before that verification and follow-up are complete, add a focused handoff note near the affected pipeline code in addition to this changelog entry.


## 2026-04-17: Legacy Parent Artifact Cleanup + Per-Round Preview Snapshot Fix

### Completed
- Deleted stale legacy `visible_parent/` round artifact directories under `.experiments/hierarchical_autoexperiment/round_000*/` after confirming they were leftover outputs from the removed parent path and were still misleading inspection.
- Confirmed that the current canonical parent artifact is the parent artifact written under `.experiments/subcircuits/subcircuit__8a5edab282/`, not the deleted legacy nested `visible_parent` tree.
- Confirmed from the canonical parent artifact debug/metadata payloads that:
  - the current canonical parent outline is internally consistent
  - geometry validation reports no children outside the composed board outline
  - preserved child copper accounting is present in the canonical parent artifact
- Fixed the per-round leaf preview snapshot persistence bug in `solve_subcircuits.py` by restoring the missing `shutil` import required for copying round-specific preview images.
- This unblocks the new candidate-round inspection UX so per-round preview snapshot persistence can proceed without the runtime `name 'shutil' is not defined` failure.

### Why this change mattered
- The user was inspecting parent boards and seeing children outside `Edge.Cuts` and missing child traces.
- Investigation showed those screenshots were coming from stale legacy parent artifacts that should no longer be treated as valid outputs of the current pipeline.
- Removing those stale artifacts reduces the chance of debugging the wrong pipeline output.
- The missing `shutil` import was also preventing the new per-round leaf preview snapshot work from functioning correctly, which weakened the visual feedback improvements.

### Verification / findings
- Canonical parent artifact inspected:
  - `.experiments/subcircuits/subcircuit__8a5edab282/`
- Key findings from canonical parent metadata/debug:
  - parent geometry validation was accepted
  - preserved child trace accounting was present
  - one child (`BT1`) legitimately had zero traces/vias because it has no internal nets, so not every zero-trace child is a bug
- Legacy nested parent artifacts removed:
  - `.experiments/hierarchical_autoexperiment/round_0001/visible_parent`
  - `.experiments/hierarchical_autoexperiment/round_0002/visible_parent`
  - `.experiments/hierarchical_autoexperiment/round_0003/visible_parent`
  - `.experiments/hierarchical_autoexperiment/round_0004/visible_parent`

### Remaining follow-up
- The current canonical parent artifact is still being rejected for real routed-parent DRC/shorting reasons, which is a separate active correctness issue from the stale legacy artifact confusion.
- The next debugging step should focus on canonical parent routing correctness:
  - why routed parent interconnect is creating shorts / solder-mask-bridge issues
  - whether parent interconnect routing is colliding with preserved child copper
  - whether parent validation/acceptance thresholds need refinement versus true geometry/copper defects

## 2026-04-17: Leaf Candidate-Round Visual Inspection UX

### Completed
- Extended the analysis-page leaf inspection flow so accepted leaf artifacts can now expose a candidate-round inspector sourced from persisted leaf debug metadata.
- The leaf gallery now loads per-leaf attempted round data from `debug.json` / `extra.all_rounds`, including:
  - `round_index`
  - `seed`
  - `score`
  - routed / accepted state
  - crossover count
  - net-distance score component
  - compactness score component
  - trace / via counts
- Added a new expandable candidate-round inspector under each accepted leaf card so the user can see whether the solver actually explored multiple alternatives before choosing a winner.
- Added winner highlighting in the candidate-round inspector so the selected best round is visually obvious.
- Added per-round preview slots in the analysis UI for:
  - pre-route front
  - routed front
  - routed copper
- Improved explanatory text in the leaf gallery so the user understands that the new inspector is intended to make search diversity visible rather than hidden behind only the final accepted artifact.

### Why this change mattered
- After fixing the routed leaf early-exit bug, the solver began exploring multiple candidate rounds, but the GUI still mostly showed only the final accepted/best artifact.
- That made the search look less dynamic than it really was.
- The new inspector is intended to make the leaf search feel inspectable and trustworthy by surfacing the attempted rounds, their seeds, and their scores directly in the UI.

### Current limitation
- The analysis-side candidate-round inspector is now wired to read per-round metadata, but true per-round image persistence still needs to be completed so each attempted round can always display its own unique preview snapshots instead of relying on shared artifact-level render outputs.
- The next follow-up should finish canonical per-round preview snapshot persistence in `solve_subcircuits.py` so the inspector can show distinct images for each attempted round with no ambiguity.

## 2026-04-17: Leaf Variation Fix + Routed Exploration Tuning

### Completed
- Fixed the leaf routed-search loop in `solve_subcircuits.py` so routed leaf solving no longer stops at the first accepted routed round.
- The leaf solver now evaluates all configured/effective routed rounds and keeps the best routed result after comparing the full candidate set.
- Increased default routed leaf exploration so candidate placements vary more meaningfully across rounds while still respecting subcircuit grouping:
  - lowered default leaf orderedness slightly
  - enabled randomized group layout by default for leaf solving
  - added round-dependent exploration mixing for routed rounds:
    - some rounds keep grouped placement with lighter ordering
    - some rounds switch to more exploratory random scatter
- Confirmed from live solve output that the same leaf now runs multiple distinct placement/routing attempts in one solve instead of exiting after the first routed success.

### Why this change mattered
- The user reported that leaf runs appeared visually identical, which made the search look fake or ineffective.
- The root cause was that routed leaf solving was effectively behaving like a first-success search rather than a multi-round optimization search.
- With the early exit removed and exploration increased, the leaf pipeline now has a real chance to discover better routed placements instead of repeatedly accepting the first viable one.

### Verification
- Re-ran syntax verification for `solve_subcircuits.py`.
- Re-ran the required pipeline verification command:

`python3 .claude/skills/KiCraft/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route`

Observed from captured output:
- repeated placement/routing attempts were visible for the same leaf within a single solve
- per-attempt placement scores differed across those rounds
- routed leaf artifacts continued to be written under `.experiments/subcircuits/`
- no traceback was visible in the captured output
- the command output was truncated by the session capture before the final tail

### Remaining follow-up
- The next useful UX improvement would be to expose per-leaf attempted rounds more clearly in the GUI so the user can inspect variation directly instead of only seeing the final accepted/best artifact.
- If more diversity is still desired after visual inspection, the next tuning levers are:
  - stronger round-to-round exploration scheduling
  - broader scatter-mode variation
  - explicit persistence of candidate preview snapshots per leaf round

## 2026-04-17: Continued Old-Router Purge Debug Pass + Verification Follow-Through

### Completed
- Continued the post-purge scan for stale whole-board/top-down router terminology and compatibility assumptions after the first deletion pass.
- Fixed a remaining scoring rename bug in `autoexperiment.py` where `absolute_score` still referenced the removed `top_level_score` name instead of `parent_routed_score`.
- Cleaned additional active GUI wording so the user-facing language now better matches the canonical parent-routing pipeline:
  - setup page now describes canonical parent routing instead of a visible top-level stage
  - monitor now labels the parent status card as `Parent Routing`
  - analysis summary/convergence labels now say `Parent Routed`
- Removed additional stale mode-color assumptions from the progression viewer that still referenced old router-era modes.
- Re-ran targeted scans over active GUI and hierarchical script code and confirmed no remaining matches for removed router-era names in active code, including:
  - `skip_visible`
  - `top_level_ready`
  - `visible_output_dir`
  - `visible_parent`
  - `parent_preloaded`
  - `parent_freerouted`
  - `demo_metadata`
  - `hierarchical_parent_smoke`
  - `visible_top_level`
  - `FullPipeline`
  - `PlacementEngine`
  - `RoutingEngine`

### Verification
- Re-ran Python compile checks for the edited GUI and hierarchical orchestration files.
- Re-ran the required subcircuit pipeline verification command:

`python3 .claude/skills/KiCraft/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route`

Observed outcome from captured output:
- routed leaf solve activity executed
- accepted/routed subcircuit artifacts were written under `.experiments/subcircuits/`
- no traceback was visible in the captured output
- the command output was truncated before the final tail, so final completion text was not fully visible in this session capture

### Remaining follow-up
- The active code has been purged of the removed router-era names that were found during this pass, but historical notes and previously written artifacts may still contain old terminology.
- The next cleanup target should be persistence/runtime hardening:
  - verify the SQLite schema and existing local rows behave cleanly after the field renames
  - decide whether to migrate or reset historical DB columns that still reflect removed names
  - continue checking GUI runtime behavior against mixed old/new imported experiment data

## 2026-04-17: Old Router Purge + Canonical Subcircuit-Only Cleanup

### Completed
- Deleted the old whole-board/top-down router entrypoints:
  - `.claude/skills/KiCraft/scripts/autopipeline.py`
  - `.claude/skills/KiCraft/scripts/autoplace.py`
  - `.claude/skills/KiCraft/scripts/autoroute.py`
  - `.claude/skills/KiCraft/scripts/demo_hierarchical_freerouting.py`
  - `.claude/skills/KiCraft/scripts/autoplacer/pipeline.py`
- Removed the old router compatibility switch from the GUI/runner path so the experiment manager no longer offers or forwards a “skip visible stage” mode.
- Continued renaming active hierarchical fields away from stale top-down/demo terminology:
  - `top_level_ready` → `parent_routed`
  - `visible_output_dir` → `parent_output_json`
- Removed old parent-preview compatibility assumptions from active GUI paths, including support for:
  - `visible_parent/`
  - `parent_preloaded.png`
  - `parent_freerouted.png`
  - `demo_metadata.json`
  - `hierarchical_parent_smoke`
- Tightened monitor, analysis, and progression-viewer preview discovery so they now target canonical parent outputs from the current subcircuit pipeline only.
- Updated score/chart/table/state terminology so the UI now reflects canonical parent-routing semantics instead of old “top-level ready” wording.

### Why this change mattered
- The project direction is now explicitly subcircuit leaf layout first, then canonical parent composition/routing from those routed leaves.
- Keeping the old whole-board router and its compatibility branches around increases maintenance cost, creates misleading UI/state semantics, and risks accidental fallback to a non-scaling architecture.
- This cleanup makes the codebase more honest: one supported routing architecture, one parent pipeline, no legacy whole-board fallback.

### Verification target
- GUI and active hierarchical scripts should still compile after the purge.
- Because this cleanup touches the hierarchical subcircuits/autoplacer pipeline and its orchestration, the required verification command remains:

`python3 .claude/skills/KiCraft/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route`

### Known limitations / next follow-up
- Some historical changelog and handoff notes still mention removed names such as `skip_visible`, `top_level_ready`, and old demo-era parent preview layouts. Those notes are historical, but the active code should continue being cleaned until only canonical terminology remains.
- Any local SQLite rows or imported historical artifacts that still use removed field names may need one more migration/cleanup pass if strict canonical naming is required everywhere.
- The active code should still be audited once more for any remaining comments, labels, or stage-order mappings that mention removed top-down/router-era concepts.

## 2026-04-17: Status Normalization + Nested Parent Preview Compatibility

### Completed
- Updated monitor status rendering so terminal states read sensibly even when the last persisted live-status payload is stale or internally inconsistent.
- Normalized terminal monitor presentation so a finished run no longer appears as:
  - `phase=done` while still showing `Route Parent`
  - `routing_top_level` after the run is already complete
  - active run workers after the run has already ended
- Added compatibility fallback for parent preview discovery so GUI panels can find parent images in nested legacy/current layouts such as:
  - `visible_parent/visible_parent/parent_preloaded.png`
  - `visible_parent/visible_parent/parent_freerouted.png`
- Extended monitor fallback preview discovery to look in recent autoexperiment round directories for parent previews when status-driven preview paths are missing or stale.
- Extended analysis-page parent preview discovery to search:
  - the base parent directory
  - nested `visible_parent/`
  - nested `renders/`

### Why this change mattered
- The previous monitor pass improved visibility, but stale terminal status could still make the UI look contradictory and untrustworthy.
- Parent preview images were present on disk in some runs, but the analysis page could miss them because it only checked one directory depth.
- These fixes make the GUI more robust against both stale status payloads and artifact-layout compatibility issues.

### Verification target
- GUI-side code should still be compile-checked after these monitor/analysis compatibility fixes.
- Because this branch continues to touch hierarchical orchestration visibility around the subcircuits pipeline, the required verification command remains:

`python3 .claude/skills/KiCraft/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route`

### Known limitations / next follow-up
- The root cause of stale terminal status is still in status production/persistence, not only in monitor rendering. A future pass should make the final emitted status payload fully self-consistent so the UI does not need to normalize it defensively.
- Parent preview discovery now handles nested compatibility layouts better, but the long-term goal should still be one canonical parent artifact layout and one canonical preview naming scheme.

## 2026-04-17: Realtime Monitor Preview-Path Source-of-Truth + Live Stage Visibility

### Completed
- Updated `gui/pages/monitor.py` so the live monitor now prefers status-emitted `preview_paths` as the primary source of truth for preview rendering.
- Removed hardcoded parent artifact slug assumptions from the monitor’s current-run preview selection path.
- Updated parent output discovery in the monitor to use `preview_paths.parent_artifact_dir` when available instead of assuming one fixed parent artifact directory.
- Improved the live preview panel so it distinguishes:
  - leaf preview
  - stamped parent preview
  - routed parent preview
  - status-driven vs fallback preview source
  - current-stage relevance vs fallback reuse
- Added clearer empty-state messaging for long-running stages so the UI can explain:
  - no new preview yet for this stage
  - using a previous preview while the current stage runs
  - current action / current command when no fresh image is available
- Improved monitor status/event presentation so the page reads more like a live operator console:
  - stage labels are normalized
  - current action is surfaced more prominently
  - latest event text now includes action context
  - the event panel includes a synthesized live status card with stage/action/command context

### Why this change mattered
- The previous monitor improvements were useful, but preview selection still depended too much on filesystem guessing and stale artifact-layout assumptions.
- That made the monitor vulnerable to showing stale or misleading images during long hierarchical runs.
- The cleaner architecture is for the pipeline to emit the current preview paths and for the monitor to render those exact paths first, with filesystem discovery retained only as backward-compatible fallback behavior.

### Verification target
- GUI-side code should still be compile-checked after these monitor changes.
- Because this branch continues to touch hierarchical orchestration/visibility around the subcircuits pipeline, the required verification command remains:

`python3 .claude/skills/KiCraft/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route`

### Known limitations / next follow-up
- The monitor event stream is improved, but it still synthesizes part of the operator-console view from current status rather than from a dedicated stage-transition event log.
- Additional cleanup is still desirable around semantically stale orchestration names such as `visible_output_dir`, `skip_visible`, and `top_level_ready`.
- A future pass should consider adding an explicit preview timestamp / last-preview-update indicator and possibly a dedicated command-console panel for long-running subprocess visibility.

## 2026-04-17: Packed Parent Composition + Preview Clarity + Hierarchical Render Readability

### Completed
- Replaced the naive max-cell parent `grid` composition default with a tighter packed composition mode in `compose_subcircuits.py`.
- Added a generic size-aware packing path for rigid child subcircuits so parent assembly now places larger children first and wraps rows using actual child dimensions instead of one global max cell size.
- Updated hierarchical orchestration in `autoexperiment.py` to use the tighter packed parent composition mode by default.
- Extended parent artifact persistence and preview metadata so parent inspection can better distinguish:
  - preserved child copper
  - total routed copper
  - newly added parent interconnect copper
- Improved parent preview presentation in `gui/pages/analysis.py` so the stamped/preloaded parent and routed/final parent are explained more explicitly as different inspection views with different semantics.
- Continued render-readability tuning for inspection-oriented PCB previews, especially for parent-level review and copper visibility.
- Recorded this session progress in the changelog for continuity.

### Why this change mattered
- Parent composition had still been wasting large amounts of space because `grid` mode sized every cell from the largest child width and height.
- That inflated whitespace made parent previews look sloppy, stretched apparent interconnect distances, and made routing screenshots harder to interpret.
- The routed parent preview could also mislead the viewer into thinking preserved child copper had disappeared, even when the stamped/preloaded board still contained it.
- The new packed default is intended to make parent boards materially tighter and make the preview story more truthful.

### Implementation direction
- The immediate implementation favors a generic packed rigid-module strategy rather than a hierarchy-specific heuristic.
- Children are packed using their real transformed dimensions with configurable spacing preserved between modules.
- The packed mode is intended as a practical intermediate step toward later parent-level placement optimization.

### Verification target
- Because this work touches the hierarchical subcircuits/autoplacer pipeline, the required verification command for this branch remains:

`python3 .claude/skills/KiCraft/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route`

### Known limitations / next follow-up
- Parent packing should still be evaluated further against real hierarchy cases to confirm bounding-box reduction and absence of overlaps across varied child sets.
- Preview semantics can still be improved further with dedicated preserved-child-copper-only and added-parent-interconnect-only renders if needed.
- Analysis-page inspection UX still has room for full-resolution expand/inspect workflows.
- Root cause identified for the “components outside the PCB in FreeRouting” failure mode: the visible parent preview/routing stage had diverged from the main parent composition pipeline and was able to move child modules into parent-composition coordinates while preserving an incompatible base-board `Edge.Cuts` outline.
- Consolidation direction for the next step: remove the separate visible-parent assembly path so there is only one parent pipeline. The hierarchical visible run must reuse the same parent composition, stamping, routing, validation, and artifact-writing flow as `compose_subcircuits.py`.
- Required behavior after consolidation:
  - either parent composition/stamping/routing succeeds through the single shared path
  - or the run fails explicitly with logged diagnostics and persisted artifacts that can be inspected afterward
- Invalid parent geometry must no longer silently proceed to DSN export / FreeRouting load. In particular, parent runs should fail fast when:
  - composed child modules fall outside the stamped board outline
  - the stamped `Edge.Cuts` outline does not match the composed parent bounding box
  - parent routing inputs are inconsistent with the persisted composition state

## 2026-04-17: Hierarchical Status + Copper Accounting + Balanced Defaults + Graded Parent Scoring + Leaf Size-Reduction Implementation

### Completed
- Added a durable session-continuity rule to `AGENTS.md` so long sessions must leave a concise continuation handoff in-repo before stopping.
- Extended hierarchical live status payloads in `autoexperiment.py` to include:
  - `current_node`
  - `current_parent`
  - top-level/composition status fields
  - richer leaf worker counters (`total`, `active`, `idle`, `queued`, `completed`)
  - copper-accounting section in the status schema
- Updated `gui/pages/monitor.py` to display richer hierarchical worker state and copper-accounting summaries.
- Extended parent composition persistence in `compose_subcircuits.py` with copper-accounting fields for:
  - expected preserved child traces/vias
  - preserved child traces/vias
  - routed total traces/vias
  - added parent traces/vias
- Parent artifact `debug.json` now includes hierarchical status and copper-accounting payloads for downstream inspection.
- Plumbed parent copper-accounting data back into hierarchical live status and round-detail artifacts in `autoexperiment.py`.
- Added balanced-default guidance to `gui/state.py` and updated setup-page copy in `gui/pages/setup.py` so the GUI reflects current recommended baseline settings and tuning philosophy.
- Replaced the old hierarchical round score with a new bounded `0..100` model in `autoexperiment.py`.
- Added score breakdown and score notes to round artifacts so each round explains why it scored the way it did.
- Added plateau-aware keep logic so tiny score noise no longer creates fake “new best” rounds.
- Completed a second-pass scoring redesign so the score now separates:
  - absolute quality
  - improvement versus baseline
  - improvement versus recent rounds
  - plateau-escape reward
- Added persistent scoring context to round artifacts:
  - `absolute_score`
  - `improvement_score`
  - `plateau_escape_score`
  - `parent_quality_score`
  - `baseline_score`
  - `rolling_score`
  - `improvement_vs_baseline`
  - `improvement_vs_recent`
- Added graded parent-quality scoring so parent/top-level evaluation is no longer only binary milestone based.
- Added design notes for an iterative board-size reduction loop at both the leaf and parent levels.
- Implemented a first-pass leaf-level post-acceptance size-reduction loop in `solve_subcircuits.py`.
- Added persistence for leaf size-reduction metadata into canonical solved layout, debug payloads, and metadata notes.
- Reworked leaf-local solver defaults to favor more structured layouts:
  - leaf grouping now uses netlist/manual group information instead of forcing `group_source = none`
  - leaf swap optimization is enabled
  - leaf orderedness is enabled at a moderate default instead of being disabled
  - leaf random scatter is reduced in favor of more stable grouped placement
- Added a generic topology-aware passive-ordering refinement for leaves so passive parts can line up in more readable electrically meaningful chains around anchor components.
- The topology-aware ordering is designed to be broadly applicable rather than LLUPS-specific:
  - it derives component-to-net membership from the extracted leaf netlist
  - it builds generic component adjacency from shared nets
  - it assigns passives to the best anchor component using shared-net and connectivity strength
  - it grows passive chains from connectivity instead of relying only on size or reference prefixes
  - it arranges those chains into modest rows/columns around anchors while preserving legality guards
- Added a new topology-aware placement objective term to the core placement scorer:
  - `topology_structure` now rewards passive-chain compactness around inferred anchors
  - the score is generic and based only on component/net topology, not function semantics
  - the placement objective now nudges the solver toward structured passive blocks during search instead of relying only on post-processing
- Tuned the passive-ordering refinement to be legality-aware and less aggressive:
  - lower default orderedness strength
  - minimum passive-count threshold before row alignment activates
  - capped displacement from the solver result
  - anchor-clearance guard so ordered rows do not collapse into the main IC body
  - post-ordering legality repair before routing
- Tuned the leaf size-reduction loop to reduce reroute churn:
  - lower attempt/pass limits
  - fast-path reuse of the previous accepted route for very small outline reductions
  - diagnostic rendering can be skipped during shrink-loop reroute attempts
- Cleaned up the experiment manager GUI to focus on current hierarchical workflow visibility:
  - removed the separate visual-feedback setup tab
  - removed the board tab from the main app shell by default
  - removed backward-compatibility import of older flat-pipeline best-config presets
  - hid legacy imported presets by default
  - simplified the monitor page to emphasize run state, worker activity, experiment history, accepted artifacts, and top-level outputs
  - removed the raw live status JSON panel from the monitor page to reduce clutter
- Updated best-round summaries and frame metadata so downstream analysis can distinguish “good board” from “better than before”.

### New Scoring Model
- The previous score was broken because independent bonuses could stack past `100`, which made the scale misleading and encouraged noisy “improvements”.
- The first-pass fix bounded the score and removed the obvious overflow problem.
- The second-pass redesign now treats scoring as three layers:

#### 1. Absolute quality
- `absolute_leaf_acceptance`: up to `34`
- `absolute_routed_copper`: up to `16`
- `absolute_parent_composition`: `0` or `8`
- `absolute_top_level_ready`: `0` or `8`
- `absolute_parent_quality`: up to `14`

This produces an `absolute_score` that reflects board quality in the current round without pretending that “more traces” alone means “better”.

#### 2. Improvement reward
- `improvement_vs_baseline`: bounded reward for beating the initial baseline
- `improvement_vs_recent`: bounded reward for beating the rolling recent reference

This produces an `improvement_score` so the system rewards progress, not just static quality.

#### 3. Plateau escape reward
- `plateau_escape`: only activates when the run has been flat long enough and a round meaningfully beats the recent rolling reference

This is intended to reward escaping a plateau instead of endlessly re-labeling noise as progress.

### Graded Parent Scoring
- Parent/top-level quality is now partially graded instead of being only binary.
- The new `absolute_parent_quality` term rewards:
  - preserved child trace fidelity
  - preserved child via fidelity
  - evidence of newly added parent copper
  - routed parent copper presence relative to expected preserved + added copper
- This is still an intermediate step, but it is closer to the real engineering goal than a pure `compose ok / top ready` milestone score.

- Round detail JSON now records:
  - `score_breakdown`
  - `score_notes`
  - `absolute_score`
  - `improvement_score`
  - `plateau_escape_score`
  - `parent_quality_score`
  - `baseline_score`
  - `rolling_score`
  - `improvement_vs_best`
  - `improvement_vs_baseline`
  - `improvement_vs_recent`
  - `plateau_count`

### Plateau-Aware Selection
- A round is now only kept when it beats the current best by a meaningful margin (`keep_threshold = 0.5`), not by tiny floating-point or routing-noise differences.
- Non-improving rounds increment a plateau counter.
- Once the plateau counter reaches the configured plateau threshold, status messaging explicitly reports plateau behavior instead of pretending every non-best round is equally informative.
- The second-pass scoring architecture now makes plateau handling more explicit:
  - baseline tracks where the run started
  - rolling score tracks recent local behavior
  - plateau escape only matters when recent progress has actually stalled
- This redesign is meant to reward real improvement while reducing churn and avoiding false progress signals.

### Iterative Board-Size Reduction Loop Design + First Leaf Implementation
- After a strong layout is found, the next optimization phase should be a dedicated outline-reduction loop rather than trying to discover the smallest board only during initial placement.
- This should exist at both levels:
  - **leaf level**: shrink the local synthetic board after a routed leaf is accepted
  - **parent level**: shrink the composed/stamped parent board after a routed parent/top-level candidate is accepted
- The first-pass leaf implementation is now in place in `solve_subcircuits.py`.
- Current leaf behavior:
  1. start from the accepted routed leaf outline
  2. compute a tight geometry envelope from solved components, pads, routed traces, and routed vias
  3. derive minimum legal width/height using a configurable outline margin and pad inset margin
  4. try smaller candidate outlines with width-only, height-only, and diagonal shrink steps
  5. rebuild the local extracted board at the smaller outline
  6. rerun placement legality checks and rerun the routed leaf path when needed
  7. keep the last passing reduced outline
- Current safeguards:
  - rejects candidates with pad-outside-board or overlap legality failures before rerouting
  - requires rerouted validation to remain accepted
  - skips the reduction loop for leaves with no internal nets
  - bounds runtime with configurable attempt/pass limits so the refinement loop does not grow without limit
  - can reuse the previous accepted route for very small shrink steps to avoid unnecessary reroute churn
- Persistence added for accepted leaves:
  - `size_reduction`
  - `original_outline`
  - `reduced_outline`
  - outline reduction mm/percent summaries
  - size-reduction validation details in debug/canonical artifacts
- Latest tuning outcome:
  - the required subcircuit pipeline command now completes again after reducing shrink-loop aggressiveness
  - current accepted leaves often retain the original outline because the loop is now conservative and legality-first
  - this is a safer baseline, but it means the next tuning pass should focus on finding more reductions without destabilizing routing/runtime
- Remaining work:
  - improve shrink-step strategy so more leaves actually reduce in size
  - tune the reroute/reuse threshold based on real accepted artifacts
  - implement the same pattern for parent/top-level boards
- This loop should still be treated as a post-optimization refinement pass, not as a replacement for the main placement/routing search.

### Recommended Balanced Defaults
- experiment rounds: `10`
- leaf solve rounds: `2`
- leaf workers: `2`
- plateau threshold: `2`
- compose spacing: `12 mm`
- score weights:
  - `leaf_acceptance = 0.55`
  - `leaf_routing_quality = 0.20`
  - `parent_composition = 0.10`
  - `top_level_ready = 0.15`

### Reasonable Bounds
- `leaf_rounds`: `1..6` for normal tuning
- `top_level_rounds`: `1..3` until top-level routing is more trustworthy
- `compose_spacing_mm`: `8..20` for balanced runs
- `workers`: `1..4` on typical developer machines
- `plateau_threshold`: `1..3` for interactive use

### Quick Estimation Method
- Start from the balanced defaults.
- Run a 1-round smoke test.
- Compare only 2-3 nearby variants at a time:
  - `leaf_rounds`: `1 vs 2 vs 3`
  - `workers`: `1 vs 2 vs 4`
  - `compose_spacing_mm`: `10 vs 12 vs 16`
- Keep the smallest setting that preserves stable outcomes.
- Promote a new default only when it improves accepted leaves or top-level readiness consistently with modest runtime cost.

### How Defaults Should Be Refined Over Time
- Treat the current defaults as the control.
- Re-evaluate after meaningful pipeline changes, especially:
  - leaf routing behavior
  - parent composition behavior
  - top-level routing fidelity
  - artifact/status truthfulness
- Use short benchmark batches and compare:
  - score
  - accepted leaves / total leaves
  - top-level readiness
  - runtime
  - failure / hang rate
- Tighten bounds when extremes repeatedly underperform.
- Change defaults only when a candidate is consistently better across multiple runs, not just one favorable seed.

### Verification
- Earlier in the session, ran required subcircuit pipeline verification:
  - `python3 .claude/skills/KiCraft/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route`
  - Outcome: completed without Python exceptions; leaf artifacts written under `.experiments/subcircuits/`; routed leaf artifacts persisted canonical copper in `solved_layout.json`; run did not hang.
- After the first-pass leaf size-reduction implementation, reran the required subcircuit pipeline command.
  - Outcome: no Python traceback was observed before timeout, and accepted leaf reroute/reduction activity was visible in the logs, but the command did not complete within the bounded runtime used for verification.
  - Interpretation at that point: the new loop was functionally active, but runtime/regression tuning was still needed before this could be considered fully re-verified against the required completion criterion.
- After tuning leaf ordering and shrink-loop behavior, reran the required subcircuit pipeline command again:
  - `python3 .claude/skills/KiCraft/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route`
  - Outcome: completed successfully without Python exceptions or hangs.
  - Observed behavior:
    - leaf artifacts were written under `.experiments/subcircuits/`
    - accepted routed leaf artifacts persisted canonical copper in `solved_layout.json`
    - leaf grouping/ordering logs were visible (`Found ... component clusters (with 6 IC groups)`, `Starting swap optimization`, `Orderedness (...)`)
    - the tuned shrink loop no longer caused the required verification command to time out
- After adding topology-aware placement scoring and experiment-manager GUI cleanup, reran the required subcircuit pipeline command again:
  - `python3 .claude/skills/KiCraft/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route`
  - Outcome: completed successfully without Python exceptions or hangs.
  - Observed behavior:
    - topology-aware ordering remained active during leaf solving
    - accepted routed leaf artifacts still persisted canonical copper in `solved_layout.json`
    - several accepted leaves retained reduced outlines from the tuned shrink loop
    - the placement objective changes did not break the required verification flow
- Additional observations from the latest verification runs:
  - the new ordering heuristics are active on several leaves and report aligned passive counts
  - the CHARGER leaf accepted with ordered passive placement and routed successfully
  - current size-reduction metadata shows the loop is attempted, and some accepted leaves now reduce while others still conservatively keep the original outline
- Ran hierarchical smoke tests:
  - `python3 .claude/skills/KiCraft/scripts/autoexperiment.py LLUPS.kicad_pcb --schematic LLUPS.kicad_sch --rounds 1 --leaf-rounds 1 --workers 2 --skip-visible`
  - Outcome 1: completed successfully with `score=97.81`, `leafs=6/7`, `compose=ok`, `top=ok`.
  - Outcome 2: completed successfully with `score=98.33`, `leafs=6/7`, `compose=ok`, `top=ok`.
  - Outcome 3: completed successfully with `score=100.55`, `leafs=6/7`, `compose=ok`, `top=ok`.
- Confirmed final `.experiments/run_status.json` now includes non-empty hierarchical copper-accounting data.
- Confirmed `.experiments/rounds/round_0001.json` now records parent copper-accounting data under `artifacts.parent_copper_accounting`.
- After the first-pass scoring redesign, ran:
  - `python3 .claude/skills/KiCraft/scripts/autoexperiment.py LLUPS.kicad_pcb --schematic LLUPS.kicad_sch --rounds 3 --leaf-rounds 1 --workers 2 --skip-visible --plateau 2`
  - Outcome:
    - Round 1: `score=76.88` `[KEPT]`
    - Round 2: `score=76.74` `[discard]`
    - Round 3: `score=76.11` `[discard]`
- After the second-pass scoring redesign, ran the same command again:
  - Outcome:
    - Round 1: `score=61.89` `[KEPT]`
    - Round 2: `score=62.51` `[KEPT]`
    - Round 3: `score=63.79` `[KEPT]`
- After adding graded parent scoring, ran the same command again:
  - Outcome:
    - Round 1: `score=60.36` `[KEPT]`
    - Round 2: `score=62.69` `[KEPT]`
    - Round 3: `score=61.79` `[discard]`
- Confirmed the new score remains bounded and now reflects:
  - absolute quality
  - parent-quality fidelity
  - improvement over the initial baseline
  - improvement over recent rounds
- Confirmed round artifacts now include score breakdown plus plateau/improvement metadata and persistent scoring context.

### Files Changed
- `AGENTS.md`
- `.claude/skills/KiCraft/scripts/compose_subcircuits.py`
- `.claude/skills/KiCraft/scripts/autoexperiment.py`
- `.claude/skills/KiCraft/scripts/solve_subcircuits.py`
- `gui/pages/monitor.py`
- `gui/state.py`
- `gui/pages/setup.py`

### Known Limitations / Open Issues
- The persisted parent artifact under `.experiments/subcircuits/subcircuit__8a5edab282/` still appears stale in the checked metadata path, so live copper accounting currently relies on fallback extraction from visible-parent metadata when needed.
- Current copper accounting is useful for observability, but it is still approximate in one important way: the visible-parent fallback can show that preserved child copper is not faithfully represented in the routed/final board counts.
- The FreeRouting visual issue remains: stamped parent boards preserve child copper, but the DSN/FreeRouting visual representation is still misleading.
- Parent validation is still failing on the checked artifact because required anchors are missing and DRC warnings/errors remain.
- The latest observed copper accounting showed:
  - expected preserved child traces/vias: `315 / 10`
  - preserved child traces/vias in preloaded board: `219 / 10`
  - routed total traces/vias in final board: `208 / 10`
  - added parent traces/vias: `0 / 0`
  This reinforces that the next step should focus on artifact truthfulness and preserved-copper accounting semantics, not just UI polish.
- The second-pass scoring redesign is a substantial improvement, but it is still not final:
  - parent composition and top-level readiness still retain some binary milestone behavior even though parent quality is now partially graded
  - the improvement rewards are heuristic and may still need retuning once top-level artifact truthfulness improves
  - plateau escape is now structurally supported, but current runs may not trigger it often because the search is still improving steadily in short tests
  - the score still does not directly incorporate richer parent-level truthfulness metrics such as anchor/interconnect completion quality and parent/top-level DRC burden
- Leaf ordering is improved, but still not where it should be:
  - some leaves now show more readable passive rows/blocks and topology-derived chains, but ordering can still reduce placement score or over-regularize a layout
  - topology-aware structure is now part of the placement objective, but the post-solve ordering pass still does a meaningful amount of cleanup work
  - the new topology-aware chain extraction is generic and broadly applicable, and intentionally stays at component/net connectivity level rather than function semantics
  - some leaves likely still need stronger in-search topology preservation so the solver naturally lands in structured blocks before the post-pass
- The board-size reduction story has advanced from design-only to first-pass leaf implementation plus runtime tuning, but it is not finished:
  - the required verification command now completes again after tuning
  - however, the shrink loop is currently conservative and many accepted leaves still keep the original outline
  - shrink-step strategy, acceptance heuristics, and route-reuse thresholds still need refinement
  - parent/top-level size reduction is still not implemented
- The experiment manager GUI is cleaner, but more focused visibility work remains:
  - the monitor is now more focused on active run visibility, but experiment history and comparison views can still be improved
  - some analysis components may still reflect older assumptions and should be reviewed for relevance to the current hierarchical workflow
  - the GUI should continue moving toward fewer tabs, fewer redundant toggles, and clearer run-state storytelling

### Next Recommended Step
1. Improve experiment manager functionality and visibility into running experiments:
   - tighten the monitor around active run state, worker utilization, accepted artifacts, and recent experiment history
   - review analysis components for vestigial or low-value panels and remove or simplify them
   - continue removing old GUI paths that no longer match the hierarchical workflow
2. Improve leaf ordering quality so passives line up in more truthful topology-aware electrical blocks:
   - strengthen topology-aware structure during search, not only after search
   - preserve legality and routing quality while increasing visual structure
   - keep the approach generic and connectivity-based rather than function-semantic
3. Tune the leaf size-reduction loop so more accepted leaves actually shrink while keeping the now-restored runtime stability:
   - refine shrink-step ordering/sizing
   - improve the route-reuse threshold
   - keep the smallest passing outline without excessive retry churn
4. Confirm reduced outlines are being persisted and reused canonically downstream for accepted leaves.
5. Implement the iterative board-size reduction loop for accepted parents/top-level boards.
6. Extend graded parent/top-level quality terms so scoring can distinguish:
   - preserved child copper fidelity
   - newly added parent interconnect quality
   - anchor/interconnect completion quality
   - DRC burden at the parent/top level
7. Make parent/top-level copper accounting canonical in the persisted parent artifact path, not just available through fallback metadata.
8. Separate preserved child copper from newly added parent interconnect copper in the user-visible artifact story.

## 2026-04-13: Connector Orientation Fix — Body Center Reference

### Bug Fix
- **`_best_rotation_for_edge()` used wrong reference point**: The function measured pad centroid direction from the footprint origin (`comp.pos`), which for connectors like USB-C (GCT USB4085) is at corner pad A1. The pad centroid from origin was at ~22.7° — close enough to snap to 0° delta — so the connector was left at 0° (opening downward instead of toward the board edge). Fix: use body center (courtyard bbox center) as reference. From body center, the pad centroid is at 270° (perpendicular to opening face), which correctly produces rotation 270° for a left-edge connector.

### Data Model
- **Added `body_center: Point | None` to `Component`**: Populated from courtyard bbox center during PCB load. Transformed alongside pads in `_update_pad_positions()`, `_swap_pad_positions()`, and `_shift_pads_inside()`.

### Orientation Validation
- **`orientation_check.py` rewritten**: Replaced hard-coded expected rotation table (`left→270°`, `right→90°`, etc.) with dynamic pad-centroid-vs-body-center check. Now correctly validates any connector footprint regardless of internal geometry.

### Files Changed
- `autoplacer/brain/types.py` — `body_center` field on Component
- `autoplacer/hardware/adapter.py` — populate body_center from courtyard/bbox center
- `autoplacer/brain/placement.py` — body_center in rotation calc, transform on move/rotate/swap/shift
- `scoring/orientation_check.py` — dynamic facing validation

---

## 2026-04-13: Rotation Convention Fix + Pad Containment + Connector Grouping

### Critical Bug Fixes
- **Rotation convention**: `_update_pad_positions()` and all rotation code fixed from CCW (standard math) to KiCad's CW convention (`x'=x·cos+y·sin, y'=-x·sin+y·cos`). This was the root cause of pads appearing outside the board — model computed pad positions on the wrong side vs where KiCad actually placed them.
- **Layer flip pad mirroring**: `_assign_layers()` now mirrors pad X offsets when flipping components to B.Cu, matching KiCad's `Flip()` behavior.
- **Step reordering**: Layer assignment now runs before edge pinning so connector positions account for flipped pad geometry.
- **`_best_rotation_for_edge`**: Rotation delta fixed from `desired - current` to `current - desired` (CW direction).

### Pipeline Hardening
- **Hard pad-containment gate**: Zero-tolerance rejection — any pad outside board boundary blocks routing. `pads_outside_board` count added to PlacementEngine output.
- **Post-restore clamp**: `_clamp_pads_to_board()` runs after `_restore_pinned_positions()` as defense in depth.

### New Features
- **Connector edge grouping**: Same-edge connectors placed in compact rows/columns with `connector_gap_mm` spacing. Auto-oriented via `_best_rotation_for_edge()` so pads face board center.
- **Orderedness parameter**: 0.0-1.0 strength for aligning passives into grid near IC group leaders. Added to minor/major mutation search space.
- **Edge-pinned rotation skip**: `_optimize_rotations()` skips components in `_pinned_targets` to preserve edge orientation.

### Results
- Best score: 92.7 (up from 91.1), 0 pads outside board (verified by KiCad reload)

---

## 2026-04-11: Codebase Cleanup — Old Python Router Removed

Removed all remnants of the custom Python A*/RRR autorouter. FreeRouting is now the sole routing engine.

### Files Deleted
- `simple_router.py` — old A* grid router
- `reroute_net.py` — old MST-based Python net rerouter
- `autoplacer/_apply_routing.py` — old routing application code
- `BUGFIX_PLAN.md`, `IMPROVEMENT_PLAN.md` — old planning docs
- `docs/freerouting-plan.md`, `docs/dashboard-automation.md` — completed migration plans

### Code Cleaned
- `autoroute.py`: removed dead `--no-rrr` flag and `rip_up` parameter
- `diff_rounds.py`: removed A\* Expansions and RRR timing fields
- `generate_report.py`: removed RRR timing display and per-net `a_star_expansions` column
- `plot_experiments.py`: removed RRR bar from stacked timing chart

### Documentation Updated
- `docs/next-steps.md`: rewritten to reflect current state (150-round experiment complete, old items removed)
- `docs/monitoring-guide.md`: removed rip-up-reroute reference from timing chart description

---

## 2026-04-09: Autoplacer Improvement Plan — Implementation & Validation

### Changes Implemented (from IMPROVEMENT_PLAN.md)

**program.md (1A):** Fixed param ranges — `clearance_mm` floor raised to 0.2 (DRC min), removed useless `existing_trace_cost` tunable, added `grid_resolution_mm` [0.25–0.5], widened `force_repel_k` to 50–500, `max_rips_per_net` to 3–20. Added `net_priority` for 3 always-failing nets (`/CHG_N`, `/NTC_SENSE`, `Net-(F1-Pad2)`).

**config.py (1C, 2A):** Grid default 0.5→0.25mm, `max_search` 1M→2M, added `net_priority: {}` default.

**autoexperiment.py (1B, 3A, 3B, 3C):**
- Shorts penalty changed from multiplicative log-scale (÷2.5 at 31 shorts) to additive (−0.5/short, max −15). Preserves routing-completion signal.
- `grid_resolution_mm` added to minor (0.25–0.5) and major (0.2–0.5) tunable ranges.
- 20% of each batch reserved for pure exploration (random config + seed).
- Per-net failure counts tracked and written to round detail JSON.
- `net_priority` from program.md injected into all candidate configs.

**conflict.py (2D):** RRR made more aggressive — default iterations 5→25, max victims per rip 2→4, stagnation limit 2→6, timeout 8→60s, victim search bbox ±5→±10mm.

**router.py (2B):** `_prioritize_nets` now applies `net_priority` overrides from config, boosting historically-failing signal nets.

**grid_builder.py (2C):** Escape corridors carved in all 4 directions from each pad (was nearest-edge only). Corridor width scales with grid resolution: `max(2, ceil(3·res/0.25))` cells.

### Validation Run (20 rounds, still in progress as of writing)

- **Baseline score: 41.02** (was 21.83 — 88% improvement from additive penalty alone)
- **Best after 5 rounds: 56.72** — 21/26 nets routed (was 13/26), from an explore config with `force_repel_k=129.5`, `cooling_factor=0.94`
- Round 1 (minor): score=51.7, 18/26 routed, 77 shorts
- Round 4 (explore): score=56.7, **21/26 routed**, 96 shorts ← new best
- `Net-(F1-Pad2)` now routes consistently (was never-routed); `/CHG_N` and `/NTC_SENSE` routed in some rounds
- 2 of 5 rounds kept (40% acceptance, was 10.7%)

### Performance Problem: Rounds Too Slow

Each round takes **14–22 minutes** (was ~2 min at 0.5mm grid). Root causes:

1. **4× grid cells** (0.25mm): ~167K cells/layer → A* expansions jumped from ~5M to 55–91M per round
2. **RRR timeout 60s**: each failed net burns up to 60s in rip-up cycles (was 8s)
3. **max_search 2M**: A* explores 4× more nodes before giving up on impossible paths
4. **Wider escape corridors in all 4 directions**: more cells to clear per pad, slower grid construction

The experiment was running correctly but appeared stuck because the first batch of 5 workers took ~14 min each. The status file only updates on batch completion, so there was no visible progress for long stretches.

**Mitigation ideas for next run:**
- Try `grid_resolution_mm=0.35` as a compromise (2× cells vs 4×)
- Lower `rrr_timeout_s` to 30s (diminishing returns past 30s)
- Cap `max_search` at 1M (enough for 0.25mm, most failures hit the cap anyway)
- Add per-worker progress heartbeats to status file so long rounds don't look hung

---

## 2026-04-09: 45-Round Autoexperiment Audit

- Ran `python3 .claude/skills/KiCraft/scripts/autoexperiment.py LLUPS.kicad_pcb --rounds 45 --program .claude/skills/KiCraft/scripts/program.md`
- Live monitoring used `.experiments/run_status.json`, `.experiments/run_status.txt`, and the Flask dashboard on port 5000
- Run completed in about 12 minutes with 22 workers; artifacts written to `.experiments/` including `experiments.jsonl`, `rounds/`, `progress.gif`, and `experiments_dashboard.png`
- Baseline reported `score=0.00`, `shorts=38`, `drc_total=393`
- No candidate rounds were kept; final best stayed the baseline (`Best config delta from default: {}`)
- All 45 round detail files show `routing.total = 0`, `routing.routed = 0`, `routing_ms = 0.0`, `rrr_ms = 0.0`, and empty `per_net` data
- Representative round JSONs also show `placement.total = 0.0` and `placement.board_containment = 0.0`, so the experiment is not producing valid placed-and-routed candidates
- The negative scores in `experiments.jsonl` are failure sentinels from `autoexperiment.py` worker handling (`score.total = -1.0`) plus downstream penalty logic, not genuine improvements
- Score ordering is therefore misleading in this run: the highest logged round score (`-0.358`, round 33) coincided with worse DRC (`61` shorts, `438` total violations) rather than a better board
- Main next step for follow-up: instrument or temporarily unmask worker exceptions in `autoexperiment.py` / `autoplacer.pipeline` to identify why the worker path returns sentinel failures while still emitting DRC snapshots

## Phase 3: Performance Optimizations

**Commit:** `462962d`

- `came_from` dict → numpy array (eliminates tuple allocation per node)
- Footprint lookups vectorized with numpy slices (9 reads → 1 C call for multi-cell traces)
- Base-grid caching in RipUpRerouter (90% reduction in grid-building overhead)
- Result: 2-3x speedup on deep A* searches

## Phase 2: Correctness Fixes (Hard-Block + Escape Via)

**Commit:** `83256e9`

- Completed traces now hard-blocked at 1e6 (impossible to cross)
- Escape vias marked on grid immediately after creation
- Via markings include clearance margin (+0.2mm)
- A* max_search raised from 500K to 2M nodes
- Test added: `test_hard_block_prevents_cross_net_routing` (all 9 unit tests pass)

## Phase 1: Root Cause Analysis

Identified 3 critical bugs causing ~80 DRC shorts per routing run:

1. Cross-net traces marked as soft obstacles (cost=100), not hard blocks (1e6)
2. Escape vias never marked on grid → via collisions
3. Via markings had no clearance margin

## Grid & Scoring Tuning

- Grid resolution: 0.5mm → 0.25mm. At 0.5mm the router can't distinguish "fits" from "doesn't fit" (trace+clearance rounds to 1 cell). At 0.25mm traces can thread between existing routes honestly.
- Route completion weight: 50% → 65%
- Crossover score in placement: 20% → 30%
- Deleted `drc_sweep.py` (complex nudge logic, didn't help; -287 lines)
- Reverted `mark_segment` point-to-segment distance → bbox (simpler, safer)

## Code Cleanup

- Extracted `GridBuilder` class and `build_grid()` / `path_to_traces()` into `autoplacer/brain/grid_builder.py` — eliminated ~120 lines of duplication between `router.py` and `conflict.py`
- Rip-count-aware victim selection in RRR (nets ripped many times become less likely victims)

---

## Key Learnings

1. **Finer grids > complex algorithms** for congested 2-layer boards.
2. **Hard-blocking is correct** — honest metrics expose real routing constraints. Previously got "26/26 routed" by routing through other nets (hidden shorts).
3. **Over-engineering makes things worse** — start simple, add complexity only when measured to help.
4. **Scoring weights are hyperparameters** — tune them like any other search lever.
5. **Placement clearance ≠ routing clearance** — tighter placement (2.5mm → 1.5mm in experiments) helps routing by shortening traces.

---

## Current State

- **Best score**: 27.5 (21/26 nets, 32 shorts, 0.25mm grid)
- **Baseline at 0.5mm grid**: 26/26 nets (100%), ~81 DRC shorts, 432s per routing
- Trade-off: 0.25mm grid is 5x slower but produces honest routing
- Shorts are DRC-hard (real clearance violations, not routing artifacts)

## Root Causes of Remaining Shorts

1. **Via placement grid quantization** — vias snap to 0.5mm grid; two nets may collide
2. **Trace-to-trace clearance** — hard blocks force tight packing, traces can be 0.195mm apart (below 0.2mm DRC minimum)
3. **Component escape corridors too narrow** — escape vias collide near boxed-in pads

---

## Future Ideas

### High Priority
1. Per-net adaptive grid resolution (0.2mm near congestion, 0.5mm elsewhere)
2. Escape via optimization (avoid collision clusters)
3. Net routing order: power-first + MST-based ordering
4. Wider traces for power nets (dynamically thin at tight-pitch footprints)

### Medium Priority
1. Parallel net routing (spatially independent nets on read-only grid copies)
2. Hierarchical routing (power/GND first, then high-priority signals)
3. Thermal-aware placement (pin high-current traces for direct routing)
4. Incremental grid updates (shadow grid, only update touched cells)

### Lower Priority
1. Continuous cost field instead of binary soft/hard obstacles
2. Simulated annealing RRR
3. ML placement seeding

---

## Files Changed (Cumulative)

| File | Changes |
|------|---------|
| `autoplacer/brain/router.py` | Hard-block logic, max_search, numpy A*, imports grid_builder |
| `autoplacer/brain/grid_builder.py` | New — extracted grid construction + path_to_traces |
| `autoplacer/brain/conflict.py` | RRR base-grid caching, rip-count victims, imports grid_builder |
| `autoplacer/brain/types.py` | ExperimentScore weights (0.15/0.65/0.10/0.10) |
| `autoplacer/config.py` | max_search=1M, trace_cost=100, grid_resolution=0.5 |
| `autoplacer/brain/test_router_grid_behavior.py` | Hard-block verification test |
