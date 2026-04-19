# LLUPS Roadmap

> **Last updated:** 2025-07-19 (session 2)
> **Current phase:** Phase 3-5 — in progress
> **Quick status:** Tests green (94 pass). Phase 2 complete (commit 7d02220, pushed). Phase 3-5 partial (commit 939ff28, pushed). Parent validation fixed, recursive hierarchy added.

---

## How to use this file

This is the **single canonical plan document** for the LLUPS project. Every session should:
1. **Start** by reading this file to understand current state
2. **End** by updating the checkboxes, status line, and "Last Session" section below

This replaces the scattered tracking previously split across NEXT_AGENT.md, docs/next-steps.md, and CHANGELOG.md handoff entries. The CHANGELOG remains for detailed per-session engineering notes (append-only history).

---

## Phases Overview

| # | Phase | Status | Description |
|---|-------|--------|-------------|
| 0 | Repo cleanup and KiCraft extraction | Done | Untrack artifacts, consolidate docs, extract KiCraft submodule |
| 1 | KiCraft dead code removal (Wave 1-3) | Done | Delete dead code, fix imports, clean GUI |
| 2 | KiCraft code cleanup | Done | Delete dead CLIs, refactor subcircuit_instances, update docs |
| 3 | Leaf pipeline hardening | In progress | Fix pre-route leaf legality, acceptance gates, anchor completeness |
| 4 | Parent composition MVP | Not started | Compose parent from real routed leaves, parent FreeRouting |
| 5 | Recursive hierarchy | In progress | Bottom-up N-level solve (leaves to mid-parents to root) |
| 6 | Production polish | Not started | Force tuning, FreeRouting crash reduction, test coverage |

---

## Phase 0: Repo Cleanup and KiCraft Extraction (done)

All complete. See docs/CLEANUP_PLAN.md for details.

- [x] Untrack .experiments/ and generated artifacts from git
- [x] Consolidate .gitignore
- [x] Delete stale handoff files and backups
- [x] Consolidate 3 overlapping roadmap/next-steps docs
- [x] Add clean-experiments CLI
- [x] Decouple KiCraft from LLUPS hardcodes
- [x] Extract KiCraft to standalone repo with pyproject.toml
- [x] Reintegrate as git submodule (pip install -e KiCraft/)
- [x] GitHub Actions CI (ruff + pytest on 3.10/3.12/3.13)
- [x] Tag KiCraft v0.1.0

---

## Phase 1: KiCraft Dead Code Removal (done)

- [x] Wave 1: Delete ~3,000 lines of dead code (commit 3b47044)
- [x] Wave 2: Fix fragile imports, normalize scoring weights, consolidate plot CLIs (commit 60477fa)
- [x] Wave 3 / Phase 1 GUI cleanup: Delete param_sensitivity module, remove dead GUI toggles/flags, fix preloaded_path bug (commit c7e85ae)
- [x] Add minimal test gate rules to AGENTS.md

---

## Phase 2: KiCraft Code Cleanup (done)

- [x] Delete dead CLI modules: layout_session.py, dashboard_app.py
- [x] Remove dead entry points from pyproject.toml (layout-session, dashboard-app)
- [x] Clean score_layout.py: remove --no-track flag and broken session-tracking block
- [x] Refactor subcircuit_instances.py with normalize-early pattern (1 normalizer + 6 shared parsers, ~90 lines removed)
- [x] Update SKILL.md (both copies): remove deleted commands, fix plot-experiments to plot-results
- [x] Run verification: pytest 94 pass, import smoke OK, ruff clean
- [x] Commit and push KiCraft changes (7d02220)
- [x] Update LLUPS submodule pointer

---

## Phase 3: Leaf Pipeline Hardening (in progress)

The leaf pipeline works end-to-end but stamped pre-route leaf boards are sometimes illegal geometry, causing FreeRouting to fail. This phase makes leaves reliably legal.

- [x] Fix root parent validation bug: was rejecting with 'missing_required_anchors' despite successful routing (commit 939ff28)
- [x] Add leaf anchor completeness warning: _persist_solution now warns when required ports are unanchored
- [ ] Fix stamped pre-route leaf legality for edge-pinned connectors (USB INPUT leaf)
- [ ] Extend leaf acceptance gates (DRC, anchor completeness, render diagnostics)
- [ ] Fix LLUPS leaf anchor completeness (USB INPUT has only VBUS port; GND is implicit, needs explicit interface port)
- [ ] Add tests for subcircuit_instances normalize-early refactor
- [ ] Verify full pipeline with pcbnew environment

- [ ] Fix stamped pre-route leaf legality for edge-pinned connectors (USB INPUT leaf is the current blocker)
- [ ] Extend leaf acceptance gates (DRC, anchor completeness, render diagnostics)
- [ ] Fix LLUPS leaf anchor completeness (USB INPUT, BATT PROT)
- [ ] Verify: all LLUPS leaves solve, FreeRoute, pass acceptance, persist clean artifacts

---

## Phase 4: Parent Composition MVP

Key MVP milestone: a parent board composed from real routed leaves, inspectable in KiCad.

- [ ] Compose root parent from accepted routed leaf artifacts (preserve child copper exactly)
- [ ] Run parent FreeRouting without clearing child copper
- [ ] Human-inspectable output in KiCad before and after parent routing
- [ ] Reproducible from CLI without manual patching

**MVP success:** Visually inspect legal pre-route leaves, routed leaves, parent with routed leaves stamped in, parent with inter-leaf routing completed.

---

## Phase 5: Recursive N-Level Hierarchy (in progress)

- [x] Bottom-up level-by-level traversal via _compute_levels() (commit 939ff28)
- [x] Update solve-hierarchy CLI for full recursive N-level flow
- [ ] Verify on hierarchy deeper than 2 levels (requires test schematic)

---

## Phase 6: Production Polish

- [ ] Tune force balance for better component spread
- [ ] Reduce FreeRouting crash rate (~6% to <1%)
- [ ] Deduplicate force simulation code
- [ ] Extract algorithmic code from solve_subcircuits.py into brain/
- [ ] Improve test coverage
- [ ] Split brain/placement.py into focused modules

---

## Architecture Reference

### Pipeline flow

  solve-subcircuits (per-leaf solve + FreeRouting)
    -> .experiments/subcircuits/<slug>/solved_layout.json
  compose-subcircuits (assemble leaves into parent, stamp + FreeRoute parent)
    -> .experiments/subcircuits/<parent>/...
  solve-hierarchy (orchestrates full bottom-up recursive solve)
    -> calls solve-subcircuits + compose-subcircuits per level
  autoexperiment (multi-round outer loop)
    -> calls solve-subcircuits + compose-subcircuits as subprocesses

### Key facts

- FreeRouting is the only real router. Manhattan router is a placeholder.
- KiCraft is a git submodule at KiCraft/. Install with pip install -e KiCraft/.
- Project config: LLUPS_autoplacer.json
- Artifacts: .experiments/ (gitignored, regenerable)

### Key files

| File | Role |
|------|------|
| KiCraft/kicraft/cli/solve_subcircuits.py | Leaf solve + FreeRouting orchestration |
| KiCraft/kicraft/cli/compose_subcircuits.py | Parent composition + stamp + FreeRoute |
| KiCraft/kicraft/cli/solve_hierarchy.py | Top-level recursive orchestrator |
| KiCraft/kicraft/autoplacer/brain/subcircuit_solver.py | Leaf placement algorithm |
| KiCraft/kicraft/autoplacer/brain/subcircuit_composer.py | Parent composition logic |
| KiCraft/kicraft/autoplacer/brain/subcircuit_instances.py | Artifact loading + transform |
| KiCraft/kicraft/autoplacer/brain/subcircuit_extractor.py | Leaf extraction from full board |
| KiCraft/kicraft/autoplacer/brain/hierarchy_parser.py | Schematic hierarchy parsing |
| KiCraft/kicraft/autoplacer/brain/placement.py | Core force-directed placement solver |
| KiCraft/kicraft/autoplacer/hardware/adapter.py | KiCad pcbnew API interface |
| KiCraft/kicraft/autoplacer/freerouting_runner.py | FreeRouting Java process wrapper |

---

## Last Session Handoff

**Date:** 2025-07-19 (session 2)
**KiCraft HEAD:** 939ff28 (pushed to origin/main)

### Completed this session
1. Phase 2 complete: dead CLI deletion, pyproject cleanup, score_layout cleanup, normalize-early refactor (7d02220)
2. Fixed root parent validation bug (was rejecting valid parent with missing_required_anchors)
3. Added leaf anchor completeness warning in _persist_solution
4. Made solve_hierarchy.py recursive: N-level bottom-up hierarchy
5. Committed and pushed KiCraft (7d02220, 939ff28)

### Remaining (apply next)
1. Add tests for subcircuit_instances normalize-early refactor
2. Add implicit power net interface ports (GND etc) for parent connectivity
3. Run full pipeline with pcbnew and verify parent validation now accepts
4. Fix edge-pinned connector legality for USB INPUT leaf
5. Test recursive hierarchy on 3+ level schematic

### Verification state
- pytest: 94 passed, 2 skipped (pass)
- ruff: clean (pass)
- Full pipeline: NOT RUN (requires pcbnew)

### Key findings from artifact analysis
- All 6 leaves solved and routed successfully
- Parent was stamped, routed (95 parent traces, 12 vias), but rejected due to now-fixed validation bug
- USB INPUT: 1 port (VBUS), GND is implicit external without anchor
- DRC violations on USB INPUT are intrinsic to USB-C footprint (handled by existing heuristic)
