# LLUPS Roadmap

> **Last updated:** 2026-04-19 (session 4)
> **Current phase:** Phase 3-6 -- in progress
> **Quick status:** Tests green (209 pass). leaf_acceptance integrated into solve_subcircuits.py. Copper accounting with fingerprint matching added. Force step dedup completed (center-attraction bug fixed). Full pipeline verified end-to-end.

---

## How to use this file

This is the **single canonical plan document** for the LLUPS project. Every session should:
1. **Start** by reading this file to understand current state
2. **End** by updating the checkboxes, status line, and Last Session section below

This replaces the scattered tracking previously split across NEXT_AGENT.md, docs/next-steps.md, and CHANGELOG.md handoff entries. The CHANGELOG remains for detailed per-session engineering notes (append-only history).

---

## Phases Overview

| # | Phase | Status | Description |
|---|-------|--------|-------------|
| 0 | Repo cleanup and KiCraft extraction | Done | Untrack artifacts, consolidate docs, extract KiCraft submodule |
| 1 | KiCraft dead code removal (Wave 1-3) | Done | Delete dead code, fix imports, clean GUI |
| 2 | KiCraft code cleanup | Done | Delete dead CLIs, refactor subcircuit_instances, update docs |
| 3 | Leaf pipeline hardening | In progress | Fix pre-route leaf legality, acceptance gates, anchor completeness |
| 4 | Parent composition MVP | In progress | Compose parent from real routed leaves, parent FreeRouting |
| 5 | Recursive hierarchy | In progress | Bottom-up N-level solve (leaves to mid-parents to root) |
| 6 | Production polish | In progress | Force tuning, FreeRouting crash reduction, test coverage |

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

- [x] Fix root parent validation bug: was rejecting with missing_required_anchors despite successful routing (commit 939ff28)
- [x] Add leaf anchor completeness warning: _persist_solution now warns when required ports are unanchored
- [x] Fix pcbnew environment: venv had include-system-site-packages=false, blocking KiCad 9.0.8 bindings
- [x] Fix list_footprints.py: add argparse so --help works without crashing pcbnew
- [x] Verify full pipeline with pcbnew environment: all 6 leaves solve, route, and get accepted
- [x] Create brain/leaf_acceptance.py: configurable acceptance gate module (DRC, anchor, legality gates)
- [x] Add tests for subcircuit_extractor (14 tests)
- [x] Add tests for hierarchy levels / _compute_levels (6 tests)
- [x] Add tests for subcircuit_composer (7 tests)
- [x] Add tests for leaf_acceptance module (10 tests)
- [x] Integrate leaf_acceptance module into solve_subcircuits.py (replace inline acceptance logic)
- [ ] Fix stamped pre-route leaf legality for edge-pinned connectors (USB INPUT leaf)
- [ ] Fix LLUPS leaf anchor completeness (USB INPUT has only VBUS port; GND is implicit, needs explicit interface port)

---

## Phase 4: Parent Composition MVP (in progress)

Key MVP milestone: a parent board composed from real routed leaves, inspectable in KiCad.

- [x] Compose root parent from accepted routed leaf artifacts (preserve child copper exactly)
- [x] Run parent FreeRouting without clearing child copper
- [x] Human-inspectable output in KiCad before and after parent routing (renders generated)
- [x] Reproducible from CLI without manual patching (solve-hierarchy --skip-leaves --route)
- [x] Add copper accounting verification (fingerprint-based trace matching, per-child preservation reporting)

**MVP success:** Full pipeline verified -- parent accepted with 6 composed leaves, 233 child traces + 95 parent interconnect traces.

---

## Phase 5: Recursive N-Level Hierarchy (in progress)

- [x] Bottom-up level-by-level traversal via _compute_levels() (commit 939ff28)
- [x] Update solve-hierarchy CLI for full recursive N-level flow
- [x] Add test coverage for _compute_levels with 3+ level hierarchies (test_hierarchy_levels.py)
- [ ] Verify on real hierarchy deeper than 2 levels (requires multi-level schematic)

---

## Phase 6: Production Polish (in progress)

- [x] Improve test coverage: 209 tests (was 187), added copper_accounting tests (22 tests)
- [ ] Tune force balance for better component spread
- [ ] Reduce FreeRouting crash rate (~6% to <1%)
- [x] Deduplicate force simulation code (_force_step vs _force_step_numpy in placement.py) + fix missing center-attraction bug
- [ ] Extract algorithmic code from solve_subcircuits.py into brain/ modules
- [ ] Split brain/placement.py into focused modules (solver, scorer, legalizer)

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
- pcbnew: system-installed at /usr/lib64/python3.13/site-packages/ (KiCad 9.0.8)
- venv must have include-system-site-packages=true for pcbnew access

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
| KiCraft/kicraft/autoplacer/brain/leaf_acceptance.py | Configurable leaf acceptance gates |
| KiCraft/kicraft/autoplacer/brain/hierarchy_parser.py | Schematic hierarchy parsing |
| KiCraft/kicraft/autoplacer/brain/placement.py | Core force-directed placement solver |
| KiCraft/kicraft/autoplacer/hardware/adapter.py | KiCad pcbnew API interface |
| KiCraft/kicraft/autoplacer/freerouting_runner.py | FreeRouting Java process wrapper |

---

## Last Session Handoff

**Date:** 2026-04-19 (session 4)

### Completed this session
1. Integrated leaf_acceptance module into solve_subcircuits.py: per-round acceptance now uses structured gates (evaluate_leaf_acceptance) instead of inline boolean check; persist-time acceptance includes full anchor validation
2. Created brain/copper_accounting.py: fingerprint-based trace/via matching for real copper preservation verification (replaces fake min-based accounting)
3. Integrated copper accounting into compose_subcircuits.py: builds CopperManifest from composed children, verifies preservation with fingerprint matching, reports per-child results
4. Deduplicated _force_step/_force_step_numpy in placement.py: extracted 9 helper methods, single orchestrator; fixed missing center-attraction bug in numpy path (was effectively never applied since numpy is always available)
5. Fixed inflated expected_child_trace_count: state.trace_count included parent interconnect traces; now uses manifest's accurate child-only count
6. Created tests/test_copper_accounting.py (22 tests covering fingerprinting, manifest building, preservation verification)
7. Tests: 209 passed (up from 187)
8. Full pipeline verified end-to-end: all 6 leaves solved+routed+accepted, parent composed+stamped+routed+accepted

### Remaining (apply next)
1. Fix edge-pinned connector legality for USB INPUT leaf (CHARGER also has occasional overlap failures)
2. Fix LLUPS leaf anchor completeness (USB INPUT has only VBUS port; GND is implicit, needs explicit interface port)
3. Add implicit power net interface ports (GND etc) for parent connectivity
4. Phase 6: extract algorithmic code from solve_subcircuits.py into brain/ modules
5. Phase 6: split placement.py into solver/scorer/legalizer modules
6. Phase 6: tune force balance for better component spread (center-attraction bug now fixed; re-evaluate spread quality)
7. Phase 6: reduce FreeRouting crash rate (~6% to <1%)
8. Verify recursive hierarchy on 3+ level schematic (needs multi-level .kicad_sch)

### Verification state
- pytest: 209 passed, 0 skipped (pass)
- Import smoke: All critical imports OK (pass)
- Full pipeline: VERIFIED -- all 6 leaves solved+routed+accepted (fast-smoke mode)
- Hierarchy solver: VERIFIED -- parent composed+stamped+routed+accepted (44s)
- ruff: clean (pass)

### Key findings from this session
- The old copper accounting was fake: min(expected, actual) always reported 100% preservation. Real fingerprint matching shows 85.7% trace preservation after FreeRouting (215/251 traces survived geometrically)
- FreeRouting rips up some child traces during parent routing (CHARGER loses 18/99 traces, LDO loses 10/38)
- The numpy force step path was missing center-attraction force entirely -- this bug existed since the numpy variant was added
- force_step dedup reduced ~410 lines of duplicated code to ~350 lines of clean helper methods
- Copper manifest captures provenance before the flat merge loses child trace identity
