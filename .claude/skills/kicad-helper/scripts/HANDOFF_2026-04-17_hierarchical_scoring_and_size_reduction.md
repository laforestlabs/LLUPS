# Handoff — 2026-04-17 — Hierarchical Scoring + Board-Size Reduction

This note is for the next agent to continue immediately without re-discovery.

---

## 1. What was completed

### Hierarchical scoring redesign
The hierarchical round score in `autoexperiment.py` was redesigned in multiple passes.

It now records and uses:

- `score`
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

### Current scoring architecture
The current score is composed of:

#### Absolute quality
- `absolute_leaf_acceptance`
- `absolute_routed_copper`
- `absolute_parent_composition`
- `absolute_top_level_ready`
- `absolute_parent_quality`

#### Relative improvement
- `improvement_vs_baseline`
- `improvement_vs_recent`

#### Plateau handling
- `plateau_escape`

### Parent/top-level quality scoring
A graded parent-quality term was added. It currently rewards:

- preserved child trace fidelity
- preserved child via fidelity
- evidence of newly added parent copper
- routed parent copper presence relative to expected preserved + added copper

This is better than pure binary milestone scoring, but still incomplete.

### Copper accounting plumbing
Hierarchical live status and round detail artifacts now include parent copper-accounting data.

### Balanced defaults
GUI defaults and setup copy were updated earlier in the session to reflect a more balanced baseline:
- rounds: `10`
- leaf rounds: `2`
- workers: `2`
- plateau threshold: `2`
- compose spacing: `12 mm`

### Board-size reduction design
A design direction was established for a dedicated post-optimization board-size reduction loop at:
- leaf level
- parent level

This is **not implemented yet**.

---

## 2. What remains next, in priority order

### Priority 1 — implement leaf-level board-size reduction loop
This should be the next concrete implementation step.

Goal:
- after a leaf has an accepted routed layout, iteratively shrink the local board outline
- keep the smallest passing outline

Recommended behavior:
1. start from the accepted leaf outline
2. compute a tight envelope from:
   - component bodies
   - pads
   - routed copper
3. shrink width and/or height in steps
4. restamp the leaf board with the smaller outline
5. rerun routing or at minimum full validation
6. accept only if:
   - pads remain inside board with inset margin
   - no new legality failures
   - routed leaf still accepted
   - no unacceptable DRC regression
7. stop at first failure and keep the last passing size

Recommended search strategy:
- coarse steps first, then fine steps
- shrink one axis at a time before diagonal shrink
- preserve connector edge constraints

### Priority 2 — persist canonical reduced leaf outline
Once the leaf shrink loop exists:
- persist the reduced outline into leaf artifact metadata/debug/canonical solved layout
- make sure downstream composition uses the reduced leaf size, not the original extracted envelope

### Priority 3 — implement parent-level board-size reduction loop
After leaf shrink works:
- do the same for parent/top-level boards
- preserve child copper during shrink
- reroute parent interconnect after shrink if needed
- keep smallest passing parent outline

Acceptance criteria should include:
- preserved child copper remains preserved
- required anchors remain present
- no new illegal routed geometry
- parent/top-level DRC does not regress beyond allowed threshold

### Priority 4 — improve scoring with richer parent truthfulness metrics
Current scoring still needs more graded parent/top-level quality terms:
- anchor/interconnect completion quality
- parent/top-level DRC burden
- preserved child copper fidelity beyond simple counts
- newly added parent interconnect quality

### Priority 5 — make parent copper accounting canonical
Current live status can fall back to visible-parent metadata because the persisted parent artifact path may be stale.
That should be cleaned up so the canonical parent artifact path is the single source of truth.

---

## 3. Exact files touched in this session

### Modified
- `AGENTS.md`
- `.claude/skills/kicad-helper/scripts/compose_subcircuits.py`
- `.claude/skills/kicad-helper/scripts/autoexperiment.py`
- `gui/pages/monitor.py`
- `gui/state.py`
- `gui/pages/setup.py`
- `CHANGELOG.md`

### Most relevant for next implementation
- `.claude/skills/kicad-helper/scripts/autoexperiment.py`
- `.claude/skills/kicad-helper/scripts/solve_subcircuits.py`
- `.claude/skills/kicad-helper/scripts/compose_subcircuits.py`
- `.claude/skills/kicad-helper/scripts/autoplacer/brain/subcircuit_extractor.py`
- `.claude/skills/kicad-helper/scripts/autoplacer/freerouting_runner.py`
- `CHANGELOG.md`

---

## 4. Exact verification commands already run and outcomes

### Required subcircuit pipeline verification
Command:
`python3 .claude/skills/kicad-helper/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route`

Outcome:
- completed without Python exceptions
- leaf artifacts written under `.experiments/subcircuits/`
- routed leaf artifacts persisted canonical copper in `solved_layout.json`
- run did not hang

### Hierarchical smoke tests run during scoring work

Command:
`python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb --schematic LLUPS.kicad_sch --rounds 1 --leaf-rounds 1 --workers 2 --skip-visible`

Observed successful outcomes across runs:
- `score=97.81`, `leafs=6/7`, `compose=ok`, `top=ok`
- `score=98.33`, `leafs=6/7`, `compose=ok`, `top=ok`
- `score=100.55`, `leafs=6/7`, `compose=ok`, `top=ok`

These were from the old broken scoring and were the reason the redesign started.

### First-pass bounded scoring verification
Command:
`python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb --schematic LLUPS.kicad_sch --rounds 3 --leaf-rounds 1 --workers 2 --skip-visible --plateau 2`

Outcome:
- Round 1: `76.88` `[KEPT]`
- Round 2: `76.74` `[discard]`
- Round 3: `76.11` `[discard]`

### Second-pass scoring verification
Same command as above.

Outcome:
- Round 1: `61.89` `[KEPT]`
- Round 2: `62.51` `[KEPT]`
- Round 3: `63.79` `[KEPT]`

### Graded parent scoring verification
Same command as above.

Outcome:
- Round 1: `60.36` `[KEPT]`
- Round 2: `62.69` `[KEPT]`
- Round 3: `61.79` `[discard]`

This is the latest verified scoring behavior.

---

## 5. Open bugs, misleading behaviors, and known limitations

### A. Parent artifact path may be stale
The persisted parent artifact under:
- `.experiments/subcircuits/subcircuit__8a5edab282/`

appeared stale in checked metadata/debug files.

Because of that, `autoexperiment.py` currently falls back to visible-parent metadata when extracting parent copper accounting.

This should be fixed so the canonical parent artifact path is trustworthy.

### B. Parent copper accounting is still approximate
Current parent copper accounting is useful for observability, but not yet semantically perfect.

Observed example:
- expected preserved child traces/vias: `315 / 10`
- preserved child traces/vias: `219 / 10`
- routed total traces/vias: `208 / 10`
- added parent traces/vias: `0 / 0`

This suggests the current accounting/truthfulness story is still incomplete.

### C. FreeRouting visual issue still exists
The stamped parent board preserves child copper, but the DSN/FreeRouting visual representation is still misleading.

This is still a real user-facing issue.

### D. Parent validation still failing in checked artifact
The checked parent artifact still showed missing required anchors and DRC issues.

### E. Scoring is improved but not final
Current scoring still has limitations:
- parent composition and top-level readiness still retain some binary milestone behavior
- improvement rewards are heuristic
- plateau escape exists structurally but may not trigger often in short improving runs
- score still does not directly include:
  - anchor/interconnect completion quality
  - parent/top-level DRC burden
  - richer preserved-child-copper truthfulness metrics

### F. Board-size reduction loop is only designed, not implemented
There is no actual shrink loop yet at either leaf or parent level.

---

## 6. The next recommended implementation step

### Recommended next step
Implement the **leaf-level board-size reduction loop first**.

Why leaf first:
- smaller scope
- easier validation
- fewer moving parts than parent/top-level shrink
- directly useful for later parent composition

### Suggested implementation location
Most likely:
- `.claude/skills/kicad-helper/scripts/solve_subcircuits.py`
- possibly with helper logic in:
  - `.claude/skills/kicad-helper/scripts/autoplacer/brain/subcircuit_extractor.py`
  - or a new focused helper module near the subcircuit pipeline

### Suggested implementation shape
Add a post-acceptance refinement pass after a leaf’s best routed layout is found:

1. derive tight routed envelope from:
   - solved component geometry
   - pads
   - routed traces
   - routed vias
2. generate candidate smaller outlines
3. restamp board with smaller outline
4. rerun validation / reroute as needed
5. keep last passing outline
6. persist reduced outline into canonical artifact

### Suggested artifact additions
For leaf artifacts, add fields like:
- `size_reduction_attempted`
- `size_reduction_passes`
- `original_outline`
- `reduced_outline`
- `outline_reduction_mm`
- `outline_reduction_percent`
- `size_reduction_validation`

---

## 7. Relevant implementation clues already discovered

### Leaf extraction / local envelope
Relevant file:
- `.claude/skills/kicad-helper/scripts/autoplacer/brain/subcircuit_extractor.py`

Important details:
- `_derive_local_envelope(...)` currently derives the synthetic local board from component bodies and pads plus margin
- `ExtractedSubcircuitBoard` stores:
  - `local_state`
  - `envelope`
  - `translation`

This is a good place to understand current local board sizing.

### Leaf solver config
Relevant file:
- `.claude/skills/kicad-helper/scripts/solve_subcircuits.py`

Important details:
- `_local_solver_config(...)` sets:
  - `enable_board_size_search = False`
  - `board_width_mm = extraction.local_state.board_width`
  - `board_height_mm = extraction.local_state.board_height`

This means leaf solving currently uses a fixed extracted local board size.
That is exactly where a post-solve shrink loop can hook in.

### Leaf persistence
Relevant file:
- `.claude/skills/kicad-helper/scripts/solve_subcircuits.py`

Important details:
- `_persist_solution(...)` writes:
  - canonical solved layout
  - metadata
  - debug payload
- `_solved_local_outline(...)` serializes the local outline currently used

This is where reduced outline data should eventually be persisted.

### Parent stamping
Relevant file:
- `.claude/skills/kicad-helper/scripts/compose_subcircuits.py`

Important details:
- `_stamp_parent_board(...)` rewrites the board outline in the stamped parent board
- it already has the mechanism to replace the outline from `board_state.board_outline`

This is promising for later parent shrink implementation.

---

## 8. Suggested acceptance tests for the next agent

### For leaf shrink loop
After implementation, verify:
1. accepted leaf still routes and validates
2. reduced outline is smaller than original for at least some leaves
3. reduced outline is persisted in artifact metadata/debug/canonical layout
4. no Python exceptions or hangs
5. required verification command still passes:
   `python3 .claude/skills/kicad-helper/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route`

### For later parent shrink loop
Verify:
1. preserved child copper remains preserved
2. required anchors remain present
3. no new illegal routed geometry
4. parent artifact becomes canonical source of copper accounting
5. top-level visual artifact story becomes less misleading

---

## 9. Relevant commit hashes
Not recorded in this handoff beyond the earlier user-provided commits from the previous session:
- `1a7d348` — Propagate leaf worker parallelism through hierarchical autoexperiment
- `aa4b3db` — Fix hierarchical autoexperiment worker status helper

If you make the next implementation step, record the new commit hashes in `CHANGELOG.md` and update this handoff pattern again if the session gets long.

---

## 10. Short chat summary equivalent
Scoring was redesigned from broken >100 additive bonuses into a bounded, context-aware model with:
- absolute quality
- improvement vs baseline
- improvement vs recent rounds
- plateau escape
- graded parent quality

The next real implementation step is **leaf-level iterative board-size reduction after a routed leaf is accepted**, then later the same pattern at the parent level.