# LLUPS Engineering Changelog

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

`python3 .claude/skills/kicad-helper/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route`

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
  - `python3 .claude/skills/kicad-helper/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route`
  - Outcome: completed without Python exceptions; leaf artifacts written under `.experiments/subcircuits/`; routed leaf artifacts persisted canonical copper in `solved_layout.json`; run did not hang.
- After the first-pass leaf size-reduction implementation, reran the required subcircuit pipeline command.
  - Outcome: no Python traceback was observed before timeout, and accepted leaf reroute/reduction activity was visible in the logs, but the command did not complete within the bounded runtime used for verification.
  - Interpretation at that point: the new loop was functionally active, but runtime/regression tuning was still needed before this could be considered fully re-verified against the required completion criterion.
- After tuning leaf ordering and shrink-loop behavior, reran the required subcircuit pipeline command again:
  - `python3 .claude/skills/kicad-helper/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route`
  - Outcome: completed successfully without Python exceptions or hangs.
  - Observed behavior:
    - leaf artifacts were written under `.experiments/subcircuits/`
    - accepted routed leaf artifacts persisted canonical copper in `solved_layout.json`
    - leaf grouping/ordering logs were visible (`Found ... component clusters (with 6 IC groups)`, `Starting swap optimization`, `Orderedness (...)`)
    - the tuned shrink loop no longer caused the required verification command to time out
- After adding topology-aware placement scoring and experiment-manager GUI cleanup, reran the required subcircuit pipeline command again:
  - `python3 .claude/skills/kicad-helper/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route`
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
  - `python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb --schematic LLUPS.kicad_sch --rounds 1 --leaf-rounds 1 --workers 2 --skip-visible`
  - Outcome 1: completed successfully with `score=97.81`, `leafs=6/7`, `compose=ok`, `top=ok`.
  - Outcome 2: completed successfully with `score=98.33`, `leafs=6/7`, `compose=ok`, `top=ok`.
  - Outcome 3: completed successfully with `score=100.55`, `leafs=6/7`, `compose=ok`, `top=ok`.
- Confirmed final `.experiments/run_status.json` now includes non-empty hierarchical copper-accounting data.
- Confirmed `.experiments/rounds/round_0001.json` now records parent copper-accounting data under `artifacts.parent_copper_accounting`.
- After the first-pass scoring redesign, ran:
  - `python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb --schematic LLUPS.kicad_sch --rounds 3 --leaf-rounds 1 --workers 2 --skip-visible --plateau 2`
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
- `.claude/skills/kicad-helper/scripts/compose_subcircuits.py`
- `.claude/skills/kicad-helper/scripts/autoexperiment.py`
- `.claude/skills/kicad-helper/scripts/solve_subcircuits.py`
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

- Ran `python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb --rounds 45 --program .claude/skills/kicad-helper/scripts/program.md`
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
