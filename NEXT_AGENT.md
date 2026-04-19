# Continuation Handoff — KiCraft MVP Cleanup

## Session date: 2025-07-13

---

## What was completed this session

### Wave 2: Committed and pushed (KiCraft 60477fa)
- Fixed fragile bare imports in subcircuit_render_diagnostics.py
- Normalized scoring weights to sum to 1.0 (was 0.90 after removing ViaCheck)
- Consolidated plot_experiments.py + plot_scores.py into unified plot_results.py

### Phase 1: Dead GUI cleanup — committed and pushed (KiCraft c7e85ae)
- Deleted kicraft/gui/components/param_sensitivity.py (180 lines, zero consumers)
- Removed dead Sensitivity + Correlation tabs from analysis.py (depend on unpopulated config_delta)
- Cleaned DEFAULT_TOGGLES: removed 7 dead keys, added 4 actually-used keys (render_png, save_round_details, show_top_level_progress, import_best_as_preset)
- Cleaned DEFAULT_GUI_CLEANUP: removed 3 dead keys (show_legacy_imports, show_raw_status_json, show_visuals_panel)
- Fixed preloaded_path/stamped_path key mismatch bug in progression_viewer.py

### Testing rule added to AGENTS.md (LLUPS repo, uncommitted)
- Added "Minimal Test Gate After Code Changes" section with pytest + import smoke test + pipeline verification matrix

### Analysis completed (not yet applied)
- Full structural analysis of all major files
- Dead code audit of all 28 CLI entry points
- Detailed refactor design for subcircuit_instances.py normalize-early pattern
- Pipeline flow traced end-to-end (solve-subcircuits -> compose-subcircuits -> solve-hierarchy -> autoexperiment)

---

## IMMEDIATE TASKS — Apply these changes first

### Task 1: Delete dead CLI modules

```bash
cd KiCraft
rm kicraft/cli/layout_session.py    # 352 lines, superseded by autoexperiment
rm kicraft/cli/dashboard_app.py     # 841 lines, superseded by NiceGUI GUI
```

### Task 2: Clean pyproject.toml entry points

In `KiCraft/pyproject.toml`, remove these lines (around line 71-76):

```
# Session tracking
layout-session = "kicraft.cli.layout_session:main"

# Dashboard
dashboard-app = "kicraft.cli.dashboard_app:main"
```

### Task 3: Clean broken session tracking in score_layout.py

In `KiCraft/kicraft/cli/score_layout.py`:

1. Delete line 162: `parser.add_argument("--no-track", action="store_true", help="Don't record iteration in session tracker")`

2. Delete lines 196-237: The entire dead session-tracking block:
```python
    # Record iteration in session tracker
    if not args.no_track:
        try:
            from layout_session import snapshot_board, load_session, save_session, diff_snapshots
            # ... 40 lines of dead code that always fails with ImportError ...
        except Exception as e:
            print(f"  (session tracking failed: {e})\n")
```

This block uses a broken bare import (`from layout_session import ...` instead of `from kicraft.cli.layout_session import ...`) that always fails silently.

### Task 4: Refactor subcircuit_instances.py (normalize-early pattern)

In `KiCraft/kicraft/autoplacer/brain/subcircuit_instances.py`:

**Replace lines 317-696** (from `_layout_from_artifact_payload` through `_extract_layout_score_from_layout`) with new code that:

1. Rewrites `_layout_from_artifact_payload` to be LINEAR (no if/else branching):
   - Call `_normalize_to_canonical(metadata, debug, solved_layout)` to get one canonical dict
   - Call shared `_parse_*` functions on the canonical dict

2. Keeps `_subcircuit_id_from_metadata` unchanged

3. Adds `_normalize_to_canonical()` — NEW function (~80 lines) that:
   - If solved_layout exists, returns it as-is
   - Otherwise converts debug/metadata fallback format into canonical shape:
     - Components: debug.solved_components OR debug.extra.solved_local_placement.components
     - Traces: debug.extra.solved_local_routing.traces
     - Vias: debug.extra.solved_local_routing.vias
     - Ports: metadata.interface_ports (key becomes "ports")
     - Interface anchors: 3-level fallback + flat x/y -> nested {pos: {x, y}} normalization
     - Bbox: metadata.local_board_outline OR debug.leaf_extraction.local_board_outline
     - Score: debug.extra.best_round.score OR debug.extra.solve_summary.best_round.score

4. Keeps `_interface_ports_from_payload` unchanged

5. Adds 7 shared parser functions (each ~15-30 lines):
   - `_parse_components(payload)` -> dict[str, Component]
   - `_parse_traces(payload)` -> list[TraceSegment]
   - `_parse_vias(payload)` -> list[Via]
   - `_parse_interface_anchors(payload)` -> list[InterfaceAnchor]
   - `_parse_bbox(payload, components)` -> tuple[float, float]
   - `_parse_score(value)` -> float

6. DELETES these 14 old paired extractor functions:
   - _extract_interface_ports / _extract_interface_ports_from_layout
   - _extract_solved_components / _extract_solved_components_from_layout
   - _extract_solved_traces / _extract_solved_traces_from_layout
   - _extract_solved_vias / _extract_solved_vias_from_layout
   - _extract_interface_anchors / _extract_interface_anchors_from_layout
   - _extract_layout_bbox / _extract_layout_bbox_from_layout
   - _extract_layout_score / _extract_layout_score_from_layout

7. Everything from line 699 onward stays EXACTLY as-is:
   - _component_from_dict, _pad_from_dict, _point_from_dict, _layer_from_value
   - All _transform_* functions
   - _rotated_bbox_size, _compute_layout_bbox, _compute_component_bbox

NOTE: _parse_bbox calls _compute_component_bbox which is defined later in the file.
This is fine in Python since the call only happens at runtime, not import time.

Net effect: -14 functions, +8 functions (1 normalizer + 7 parsers), ~150 lines removed, zero branching in dispatcher.

### Task 5: Update SKILL.md

In `KiCraft/SKILL.md` (NOT the one under .claude/skills):
- Remove references to layout_session.py (line ~38, lines ~79-80)
- Remove references to dashboard_app.py (line ~50, line ~95)
- Update plot_experiments.py reference to plot_results.py (line ~49)

Also update `.claude/skills/KiCraft/SKILL.md`:
- Remove `layout-session` from CLI table
- Remove `dashboard-app` from CLI table
- Update `plot-experiments` / `plot-scores` references to `plot-results`

### Task 6: Commit and verify

```bash
cd KiCraft
git add -A
git commit -m "Phase 2: Delete dead CLIs, refactor subcircuit_instances normalize-early

- Delete layout_session.py (352 lines) and dashboard_app.py (841 lines)
- Remove broken session-tracking block from score_layout.py
- Refactor subcircuit_instances.py: normalize-early pattern eliminates 14 paired extractors
- Update pyproject.toml entry points and SKILL.md documentation"
git push origin main
```

### Task 7: Run verification

```bash
# Fast gate (must pass)
cd KiCraft && python -m pytest -x -q

# Import smoke test (must pass)
python -c "from kicraft.autoplacer.brain.placement import PlacementSolver, PlacementScorer; from kicraft.autoplacer.brain.types import BoardState, Component, Point, SubCircuitLayout; from kicraft.autoplacer.brain.subcircuit_solver import solve_leaf_placement, route_interconnect_nets; from kicraft.autoplacer.brain.subcircuit_composer import build_parent_composition; from kicraft.autoplacer.brain.subcircuit_instances import load_solved_artifact, transform_subcircuit_instance; from kicraft.autoplacer.brain.subcircuit_extractor import extract_leaf_board_state; from kicraft.autoplacer.brain.hierarchy_parser import parse_hierarchy; from kicraft.autoplacer.config import DEFAULT_CONFIG; from kicraft.cli.solve_subcircuits import main as solve_main; from kicraft.cli.compose_subcircuits import main as compose_main; print('All critical imports OK')"

# Lint (must pass)
ruff check kicraft/

# Full pipeline (run after structural changes)
cd .. && solve-subcircuits LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route
```

### Task 8: Update LLUPS submodule pointer

```bash
cd ~/Documents/LLUPS
git add KiCraft AGENTS.md NEXT_AGENT.md .claude/
git commit -m "Update KiCraft submodule + AGENTS.md test rule after Phase 2 cleanup"
git push origin main
```

---

## KEY ARCHITECTURAL UNDERSTANDING

### The pipeline works (for 2-level hierarchies)

The actual execution flow when you run the pipeline:

```
autoexperiment (outer multi-round loop)
  |-- subprocess --> solve-subcircuits --route --json
  |                   Extracts each leaf subcircuit
  |                   Runs PlacementSolver (force-directed placement)
  |                   Calls FreeRouting (real Java autorouter) per leaf
  |                   Persists artifacts under .experiments/subcircuits/
  |
  |-- subprocess --> compose-subcircuits --json (snapshot only)
  |
  |-- subprocess --> compose-subcircuits --route --stamp --pcb ...
                      Loads solved leaf artifacts
                      Stamps parent .kicad_pcb with all child geometry
                      FreeRoutes the parent (preserves child copper)
                      Persists parent artifacts

solve-hierarchy (simpler single-shot orchestrator)
  |-- subprocess --> solve-subcircuits --route
  |-- subprocess --> compose-subcircuits --stamp --route
```

### FreeRouting does ALL real routing
The internal Manhattan router (in subcircuit_solver.py and subcircuit_composer.py) is just a lightweight estimator. FreeRouting does the actual board routing at both leaf and parent levels. Do NOT spend time unifying the Manhattan routers — they're throwaway code.

### The gap: no recursive multi-level hierarchy
Currently: leaves -> root parent (2 levels only).
Target: leaves -> mid-parents -> grandparents -> ... -> root (N levels).
This is THE feature gap for MVP.

### CLI surface area
- 3 CORE: solve-subcircuits, compose-subcircuits, solve-hierarchy
- 8 USEFUL: autoexperiment, clean-experiments, inspect-subcircuits, inspect-solved-subcircuits, render-pcb, split-schematic, run-drc, score-layout
- 15 MARGINAL: various inspection/manipulation tools
- 2 DEAD (being deleted): layout-session, dashboard-app

---

## AFTER IMMEDIATE TASKS — MVP Direction

### Priority 1: Finish dead code + refactor (Tasks 1-8 above)
Expected result: ~1,350 more lines removed, codebase at ~28k lines, all functional.

### Priority 2: Add tests for the refactored code
The subcircuit_instances.py refactor should have tests:
- Test _normalize_to_canonical with debug-dict input
- Test _normalize_to_canonical with solved_layout input
- Test _parse_traces, _parse_vias with edge cases
- Test the anchor flat-to-nested normalization

### Priority 3: Recursive hierarchy support
This is the real MVP gap. The pipeline needs to:
1. Identify all hierarchy levels (not just leaves + root)
2. Solve leaves first (already works)
3. Compose leaves into their immediate parents, route those parents
4. Treat routed parents as new "leaf" artifacts
5. Compose those into the next level up
6. Repeat until root

solve_hierarchy.py is the right place to add this — it's already a thin orchestrator.

### What NOT to do yet
- Don't split placement.py (3,546 lines) — too risky, save for post-MVP
- Don't extract brain logic from cli/solve_subcircuits.py — important but large
- Don't unify Manhattan routers — FreeRouting does the real work
- Don't remove DEFAULT_SCORE_WEIGHTS from state.py — vestigial but plumbed through 4 files

---

## Files touched this session

### KiCraft repo (LLUPS/KiCraft/)
Committed and pushed:
- Wave 2 (60477fa): subcircuit_render_diagnostics.py, scoring/*.py, pyproject.toml, README.md, cli/plot_results.py (new), cli/plot_experiments.py (deleted), cli/plot_scores.py (deleted)
- Phase 1 (c7e85ae): gui/components/param_sensitivity.py (deleted), gui/components/progression_viewer.py, gui/pages/analysis.py, gui/state.py

NOT yet applied (Tasks 1-8):
- cli/layout_session.py (to delete)
- cli/dashboard_app.py (to delete)
- cli/score_layout.py (remove dead session-tracking)
- pyproject.toml (remove 2 entry points)
- autoplacer/brain/subcircuit_instances.py (normalize-early refactor)
- SKILL.md (update docs)

### LLUPS repo
- AGENTS.md (test rule added, uncommitted)
- NEXT_AGENT.md (this file)

---

## Verification status
- pytest: 94 passed, 2 skipped (after Phase 1)
- ruff: all checks passed
- Import smoke test: all critical imports OK
- Pipeline: NOT RUN this session — must run after Tasks 1-8

## Git state
- LLUPS main at 23edef5 — AGENTS.md and NEXT_AGENT.md uncommitted
- KiCraft main at c7e85ae — pushed, Tasks 1-8 not yet applied
- KiCraft GitHub: https://github.com/laforestlabs/KiCraft
- LLUPS GitHub: https://github.com/laforestlabs/LLUPS
