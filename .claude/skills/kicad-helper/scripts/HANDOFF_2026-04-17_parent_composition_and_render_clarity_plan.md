# Handoff — 2026-04-17 — Parent Composition Tightening + Render Clarity

This note is for the next agent to continue immediately without re-discovery.

---

## 1. What was completed

### Leaf layout / scoring progress already landed
The leaf pipeline has already been improved in several relevant ways:

- leaf-level board-size reduction loop exists in first-pass form
- leaf ordering is now topology-aware at the component/net connectivity level
- a new `topology_structure` placement score term was added to the placement objective
- leaf solving still passes the required routed verification command after these changes

This matters because parent composition now starts from better leaf artifacts than before.

### GUI / analysis cleanup already landed
The experiment manager GUI was partially cleaned up:

- monitor page was refocused on active experiment visibility
- some vestigial GUI paths were removed or hidden
- analysis page now auto-selects the latest active experiment more reliably
- accepted leaf gallery now shows:
  - front preview
  - back preview
  - combined copper preview
- parent preview section now has clearer labels and explanatory text

### Render defaults were improved
`render_pcb.py` was updated to improve readability:

- higher DPI
- larger max output size
- darker surround/background
- stronger border
- stronger contrast/saturation tuning
- slightly darker brightness
- stronger back-layer opacity in combined copper view

### Parent spacing was reduced slightly
In `autoexperiment.py`, the parent composition command was changed from:

- `--spacing-mm 12`
to
- `--spacing-mm 6`

This reduces some wasted space, but it does **not** solve the underlying parent composition problem.

---

## 2. The key problems still visible

### Problem A — parent composition still wastes a lot of space
The screenshot of the parent board makes this obvious.

Current parent composition in `autoexperiment.py` still calls:

- `compose_subcircuits.py`
- `--mode grid`

And in `compose_subcircuits.py`, grid mode uses:

- the largest child width
- the largest child height
- plus spacing

to size every cell.

This means one large child inflates the whole grid and creates:

- large empty gaps between child modules
- long-looking ratsnest lines
- visually poor parent previews
- misleading “sloppy” parent layouts

This is the main reason the screenshot shows so much wasted space.

### Problem B — parent routing visuals are misleading
The screenshot also makes it look like parent routing is not being done on top of pre-routed leaf subcircuits.

The intended pipeline is:

1. accepted routed leaf artifacts are loaded
2. child copper is stamped/preloaded into the parent board
3. FreeRouting is run mainly for remaining parent interconnect

But the routed-parent visual can under-represent preserved child copper.

So the user sees something that looks like:

- child copper disappeared
- or parent routing ignored the pre-routed leaves

even when the stamped/preloaded board is the actual source of truth.

This is a **real user-facing clarity problem**, even if the underlying preservation path is partially working.

### Problem C — render readability is still not good enough
Even after the recent render improvements, the user still reports:

- text is hard to read
- screenshots are visually messy
- white board / pale imagery / weak contrast still hurts inspection
- parent previews especially are not inspection-grade

So render quality needs another pass, especially for:

- parent previews
- leaf gallery inspection mode
- text/silkscreen readability
- copper visibility on both layers

---

## 3. What remains next, in priority order

### Priority 1 — replace naive parent grid composition with tighter generic packing
This is the most important next engineering step.

Goal:
- reduce wasted whitespace between child modules
- make parent previews visually coherent
- shorten apparent interconnect distances
- improve the quality of the stamped parent board before routing

Recommended direction:
- stop relying on uniform max-size grid cells as the default parent composition strategy
- replace or augment `grid` mode with a tighter generic packing strategy

Suggested generic strategies, in increasing sophistication:

#### Option A — row packing with size-aware wrapping
- sort children by width/area descending
- place them left-to-right in rows
- wrap when row width exceeds a target
- track actual row heights instead of using one global max height

This is much better than the current max-cell grid and is relatively easy to implement.

#### Option B — shelf/bin packing
- use a simple shelf-packing heuristic
- place larger children first
- fill rows/shelves with smaller children
- preserve a configurable spacing margin

This is still generic and should reduce whitespace significantly.

#### Option C — lightweight parent placement optimization
- treat child modules as rigid rectangles
- optimize their positions using a simple cost function:
  - bounding box area
  - interconnect distance
  - overlap avoidance
  - connector/edge preferences if available

This is the best long-term direction, but may be more work than the next agent should take on in one pass.

Recommended immediate implementation:
- implement **size-aware row/shelf packing first**
- keep it generic
- preserve rigid child transforms
- make it the default for hierarchical autoexperiment parent composition

Acceptance criteria:
- parent bounding box shrinks materially versus current grid mode
- child modules are visibly closer together
- no overlaps
- stamped parent board still routes/validates through the current path

### Priority 2 — make parent preview story explicitly show preserved child copper vs added parent interconnect
Goal:
- make the visuals tell the truth
- stop making the user infer preservation from ambiguous routed screenshots

Recommended behavior:
- keep showing both:
  - stamped/preloaded parent
  - routed/final parent
- add explicit metadata and UI labels for:
  - expected preserved child traces/vias
  - preserved child traces/vias
  - added parent traces/vias
- if possible, generate a dedicated “preserved child copper only” preview and/or “added parent interconnect only” preview

Best-case visual set:
1. stamped/preloaded parent
2. routed/final parent
3. preserved child copper only
4. added parent interconnect only

Even if only 3 and 4 are implemented as metadata-backed overlays or filtered renders, that would greatly improve clarity.

Acceptance criteria:
- user can visually distinguish preserved child copper from newly added parent routing
- routed-parent preview no longer implies that child copper vanished
- analysis page labels and badges match the actual artifact semantics

### Priority 3 — improve render readability further
Goal:
- make previews inspection-grade rather than merely present

Recommended render improvements:
- further improve contrast between:
  - copper
  - silkscreen
  - board background
  - edge cuts
- avoid pale/washed-out board interiors
- ensure text remains readable against the board fill
- consider separate render styles for:
  - copper inspection
  - silkscreen inspection
  - parent composition inspection

Suggested concrete improvements:
- darker board surround and stronger edge border are already in place; continue tuning
- consider:
  - slightly off-white board fill instead of bright white
  - darker silkscreen text or stronger stroke
  - stronger copper color separation between front/back
  - larger output size for parent previews
  - click-to-expand or full-resolution inspection mode in the GUI

Acceptance criteria:
- leaf gallery previews are readable without squinting
- parent previews are readable enough to inspect labels, copper, and module boundaries
- screenshots are suitable for user-facing debugging

### Priority 4 — improve analysis page inspection UX
Goal:
- make the analysis page a real inspection tool

Recommended improvements:
- add click-to-expand full-resolution preview dialogs
- add a toggle between:
  - gallery mode
  - inspection mode
- allow selecting which preview type to emphasize:
  - front
  - back
  - copper
  - parent stamped
  - parent routed
- show compact metadata badges near each preview:
  - traces
  - vias
  - preserved child copper counts
  - added parent copper counts

### Priority 5 — later: parent-level board-size reduction loop
Not the next step, but still important later.

Once parent composition is tighter and visually truthful:
- add parent-level outline shrink loop
- preserve child copper during shrink
- reroute parent interconnect as needed
- keep smallest passing parent outline

---

## 4. Exact files most relevant for the next agent

### Parent composition / routing
- `.claude/skills/kicad-helper/scripts/compose_subcircuits.py`
- `.claude/skills/kicad-helper/scripts/autoexperiment.py`

### Render pipeline
- `.claude/skills/kicad-helper/scripts/render_pcb.py`
- `.claude/skills/kicad-helper/scripts/autoplacer/brain/subcircuit_render_diagnostics.py`

### GUI / analysis presentation
- `gui/pages/analysis.py`
- `gui/components/progression_viewer.py`
- `gui/pages/monitor.py`
- `gui/state.py`

### Documentation / continuity
- `CHANGELOG.md`
- this handoff file

---

## 5. Exact verification already run and outcomes

### Required subcircuit pipeline verification
Command:
`python3 .claude/skills/kicad-helper/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route`

Latest outcome:
- completed successfully
- no Python exceptions
- no hang
- accepted artifacts written under `.experiments/subcircuits/`
- canonical routed copper persisted in `solved_layout.json`

This confirms the leaf pipeline is still healthy after the recent leaf scoring/ordering work.

### GUI / Python compile verification
Command:
`python3 -m compileall gui .claude/skills/kicad-helper/scripts/render_pcb.py .claude/skills/kicad-helper/scripts/autoplacer/brain/subcircuit_render_diagnostics.py .claude/skills/kicad-helper/scripts/autoexperiment.py`

Outcome:
- completed successfully

This confirms the recent GUI/render edits are syntactically valid.

---

## 6. Known limitations / open issues

### A. Parent composition is still fundamentally naive
Even after reducing spacing from 12 mm to 6 mm, parent composition still uses:
- `--mode grid`
- max-child-size cell packing

This is the main cause of wasted space.

### B. Parent routed preview is still semantically misleading
The routed parent image can still visually understate preserved child copper.

The user explicitly noticed this and interpreted it as:
- parent routing not being done on pre-routed leaf subcircuits

That interpretation is understandable from the current visuals.

### C. Render readability is still not good enough
The user explicitly reported:
- yellow text on pale board / white-ish imagery is hard to read
- screenshots are poor for inspection

So render tuning is not done.

### D. Analysis page is improved but not yet an inspection-grade tool
The leaf gallery now shows front/back/copper views, but:
- there is no full-resolution inspection workflow
- parent previews still need clearer visual decomposition
- metadata and visuals are not yet tightly integrated

---

## 7. Recommended next implementation step

### Recommended next step
Implement a **generic tighter parent composition strategy** first.

Why this first:
- it directly addresses the “why so much wasted space?” complaint
- it improves both:
  - actual parent board quality
  - visual clarity of parent previews
- it reduces the chance that the user mistakes spacing artifacts for routing failure

### Suggested implementation shape
In `compose_subcircuits.py`:

1. add a new composition mode, e.g.:
   - `packed`
   - or `shelf`
2. implement size-aware row/shelf packing for rigid child modules
3. make `autoexperiment.py` use that mode instead of `grid`
4. keep spacing configurable, but use a smaller default
5. verify no overlaps and preserve child transforms/copper

Then, after that:
- improve parent preview semantics and render clarity

---

## 8. Suggested acceptance tests for the next agent

### Parent composition tightening
After implementing tighter packing:
1. run a hierarchical autoexperiment round
2. inspect the parent preview
3. confirm:
   - child modules are materially closer together
   - no overlaps
   - parent bounding box is smaller than before
   - parent composition still routes through the current path

### Parent preview truthfulness
Verify:
1. stamped/preloaded parent clearly shows preserved child copper
2. routed/final parent clearly communicates added parent interconnect
3. UI labels explain the distinction
4. user can no longer reasonably conclude that child copper disappeared

### Render readability
Verify:
1. leaf gallery previews are readable
2. back-layer content is clearly visible
3. parent previews are readable enough for inspection
4. screenshots are suitable for user-facing debugging

### Required pipeline verification
If any subcircuits/autoplacer pipeline files are changed, rerun:
`python3 .claude/skills/kicad-helper/scripts/solve_subcircuits.py LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route`

And check:
- no Python exceptions
- no hang
- accepted artifacts written
- canonical copper persisted

---

## 9. Files touched in the most recent session relevant to this handoff

### Modified
- `.claude/skills/kicad-helper/scripts/render_pcb.py`
- `.claude/skills/kicad-helper/scripts/autoexperiment.py`
- `.claude/skills/kicad-helper/scripts/autoplacer/brain/subcircuit_render_diagnostics.py`
- `gui/pages/analysis.py`
- `gui/components/progression_viewer.py`
- `gui/pages/monitor.py`
- `gui/pages/setup.py`
- `gui/app.py`
- `gui/state.py`
- `CHANGELOG.md`

---

## 10. Short chat-summary equivalent

The user identified three real issues from a parent-routing screenshot:

1. too much whitespace between leaf groups
2. routed parent visuals make it look like pre-routed leaf copper is not being preserved
3. renders/screenshots are too hard to read

Recent work already:
- improved leaf topology-aware placement/scoring
- improved some GUI experiment-manager behavior
- improved render defaults somewhat
- reduced parent spacing from 12 mm to 6 mm

But the next real implementation step is to:
- replace naive parent grid packing with tighter generic packing
- make parent preview semantics explicitly distinguish preserved child copper from added parent interconnect
- continue improving render readability until the screenshots are actually usable