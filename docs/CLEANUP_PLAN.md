# LLUPS Repository Cleanup & Reorganization Plan

**Created:** 2025-07-11
**Status:** In Progress

## Overview

This plan covers 7 phases of cleanup and reorganization for the LLUPS repository.
Each phase has a checkbox for tracking. Mark phases `[x]` as they are completed.

---

## Phase 1: Untrack Generated Artifacts from Git  [x]

**Problem:** 74 files under `.experiments/` are committed to git but are fully
regenerable. This bloats the repo with ~4.4 MB of binary/JSON experiment data.
Additional stale backup files are also tracked.

### Files to untrack

| Path Pattern | Reason |
|---|---|
| `.experiments/` (all 74 files) | Pipeline output, entirely regenerable |
| `LLUPS.kicad_sch.bak` | KiCad auto-backup |
| `report.html` | Generated HTML report |
| `BOM.xlsx` | Generated spreadsheet |
| `scripts/autoplacer/brain/placement.py.bak` | Stale source backup |

### Commands

```
git rm -r --cached .experiments/
git rm --cached LLUPS.kicad_sch.bak
git rm --cached report.html
git rm --cached BOM.xlsx
git rm --cached .claude/skills/KiCraft/scripts/autoplacer/brain/placement.py.bak
```

### Verification

- `git ls-files .experiments/ | wc -l` should return 0
- `git ls-files | wc -l` should drop from 196 to ~112

---

## Phase 2: Update .gitignore  [x]

**Problem:** The current `.gitignore` grew organically with 80+ lines of one-off
patterns. Many are redundant or incomplete.

### New `.gitignore` (replace entire file)

```
# === KiCad ===
*.kicad_prl
fp-info-cache
*-backups/
*-rescue.lib
*-rescue.dcm
_autosave-*
*.kicad_pcb-bak
*.sch-bak
*.kicad_sch.bak

# === Gerber / fabrication ===
gerber/
fabrication/
*.gbr
*.drl
*.gbrjob

# === Generated outputs ===
report.html
BOM.xlsx
LLUPS_best.kicad_pcb
renders/

# === Python ===
__pycache__/
*.pyc
*.pyo
*.bak
.venv/
.pytest_cache/

# === ALL experiment artifacts (regenerable by pipeline) ===
.experiments/

# === Scoring results ===
.claude/skills/KiCraft/scripts/results/

# === Logs ===
logs/

# === Claude local settings ===
.claude/settings.local.json

# === OS ===
.DS_Store
Thumbs.db
desktop.ini
.~lock.*
~*.lck
```

Key change: single `.experiments/` entry replaces 30+ granular rules.

---

## Phase 3: Delete Stale Files from Disk  [x]

### Handoff files to delete (7 files)

Content already captured in `CHANGELOG.md`. These clutter the scripts directory:

- `scripts/HANDOFF_2026-04-17_hierarchical_scoring_and_size_reduction.md`
- `scripts/HANDOFF_2026-04-17_parent_composition_and_render_clarity_plan.md`
- `scripts/HANDOFF_2026-04-17_realtime_monitor_and_live_preview_plan.md`
- `scripts/HANDOFF_2026-04-17_single_parent_pipeline_cleanup.md`
- `scripts/HANDOFF_2026-04-17_timing_instrumentation_and_hardware_utilization.md`
- `scripts/HANDOFF_2026-04-17_timing_verification_and_smoke_mode.md`
- `scripts/NEXT_AGENT_PROMPT_2026-04-17_scheduling_and_failure_handling.md`

### Other stale files

| File | Action |
|---|---|
| `autoplacer/brain/placement.py.bak` | Delete |
| `LLUPS.kicad_sch.bak` | Delete |
| `LLUPS-backups/` (empty) | Delete |
| `__pycache__/` (root, empty) | Delete |
| All `__pycache__/` under gui/ and scripts/ | Delete (gitignored) |
| `.pytest_cache/` | Delete (gitignored) |
| `scripts/results/` (empty) | Delete |

### Commands

```
rm .claude/skills/KiCraft/scripts/HANDOFF_2026-04-17_*.md
rm .claude/skills/KiCraft/scripts/NEXT_AGENT_PROMPT_2026-04-17_*.md
rm .claude/skills/KiCraft/scripts/autoplacer/brain/placement.py.bak
rm -f LLUPS.kicad_sch.bak
rmdir LLUPS-backups/ 2>/dev/null
rm -rf __pycache__/
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null
rm -rf .claude/skills/KiCraft/scripts/results/
```

---

## Phase 4: Consolidate Documentation  [x]

### Problem

Three overlapping roadmap/next-steps documents:
1. `docs/next-steps.md` — project-level priorities
2. `scripts/NEXT_STEPS.md` — autoplacer theory-of-operation + roadmap
3. `CHANGELOG.md` handoff entries — per-session priorities

### Actions

1. Merge "Theory of Operation" from `scripts/NEXT_STEPS.md` into `docs/architecture.md`
2. Delete `scripts/NEXT_STEPS.md`
3. Keep `docs/next-steps.md` as the single canonical roadmap

---

## Phase 5: Automatic Artifact Cleanup Script  [x]

### What gets generated per run

| Directory | Per-run size |
|---|---|
| `.experiments/subcircuits/` | ~20 MB |
| `.experiments/rounds/` | ~100 KB |
| `.experiments/frames/` | ~2 MB |
| `.experiments/hierarchical_autoexperiment/` | ~5 MB |
| `.experiments/best/` | ~500 KB |
| `.experiments/*.json`, `*.jsonl`, `*.db` | ~3 MB |

### Script: `clean_experiments.py`

Location: `.claude/skills/KiCraft/scripts/clean_experiments.py`

Three modes:

1. **`--before-run`** — Pre-run cleanup:
   - Archives `best/` to `best_previous/`
   - Wipes `frames/`, `rounds/`, `round_renders/`, `workers/`
   - Wipes `hierarchical_autoexperiment/`
   - Removes stale `run_status.json`, `experiment.pid`
   - Preserves: `seed_bank.json`, `elite_configs.json`, `best_config.json`
   - Preserves: `subcircuits/*/solved_layout.json` (cache reuse)

2. **`--after-run`** — Post-run cleanup:
   - Removes intermediates from `subcircuits/*/`: `leaf_pre_freerouting.*`,
     `leaf_routed.*`, `leaf_illegal_*`, `route_input.*`, `*.txt`, `renders/`
   - Removes `frames/`, individual `rounds/*.json`
   - Keeps: `metadata.json`, `solved_layout.json`, `layout.kicad_pcb`

3. **`--nuke`** — Full reset:
   - Removes entire `.experiments/` directory

### Integration

Add `--clean` and `--clean-after` flags to `autoexperiment.py`.

---

## Phase 6: Separate KiCraft into Its Own Codebase  [x]

### Coupling analysis

KiCraft is ~95% generic. LLUPS-specific content in exactly 3 files:

| File | LLUPS content | Fix |
|---|---|---|
| `autoplacer/config.py` | `LLUPS_CONFIG` dict (~50 lines) | Remove, use JSON-only |
| `autoplacer/llups_config.json` | Entire file | Move to LLUPS project root |
| `autoplacer/brain/graph.py` | `POWER_NETS` constant | Read from config dict |

Scripts with LLUPS defaults (already accept CLI args, just need default changes):

| File | LLUPS content | Fix |
|---|---|---|
| `parse_schematic.py` | Hardcoded `IC_GROUPS` | Accept config arg |
| `cleanup_routing.py` | Hardcoded `["U2", "U4"]` | Read from config |
| `dashboard_app.py` | `_find_llups_root()` | Generic project discovery |

GUI files with LLUPS defaults:

| File | LLUPS content | Fix |
|---|---|---|
| `gui/state.py` | `LLUPS.kicad_pcb`, `LLUPS.kicad_sch` | Auto-detect from cwd |
| `gui/app.py` | Title: `"LLUPS Experiment Manager"` | Config-driven |
| `gui/db.py` | DB filename `llups.db` | `experiments.db` |
| `gui/experiment_runner.py` | Default `LLUPS.kicad_sch` | Auto-detect |
| `gui/pages/setup.py` | Default filenames | Auto-detect |
| `gui/pages/monitor.py` | Default `LLUPS.kicad_sch` | Auto-detect |

### Sub-phases

**6a — Decouple (in current repo, low risk):**
- Remove `LLUPS_CONFIG` from `config.py`
- Move `llups_config.json` content into `LLUPS_autoplacer.json`
- Make `graph.py` read power nets from config
- Parameterize remaining hardcoded LLUPS references

**6b — Extract (new repo):**
- Create `KiCraft` repository
- Move scripts + autoplacer + scoring + gui as `kicraft` package
- Add `pyproject.toml` with CLI entry points
- Add minimal test suite

**6c — Reintegrate:**
- Add KiCraft as git submodule or pip dependency in LLUPS
- Update `AGENTS.md`, `SKILL.md` for new paths

### Target standalone structure

```
KiCraft/
├── pyproject.toml
├── kicraft/
│   ├── autoplacer/
│   │   ├── config.py           # DEFAULT_CONFIG only
│   │   ├── freerouting_runner.py
│   │   ├── brain/              # Pure algorithms
│   │   └── hardware/           # pcbnew interface
│   ├── scoring/                # Fully generic already
│   ├── cli/                    # Entry-point scripts
│   └── gui/                    # Parameterized experiment manager
├── tests/
└── examples/
    └── llups/llups_config.json
```

---

## Phase 7: Execution Tracking

| Phase | Status | Commit | Notes |
|---|---|---|---|
| 1. Untrack artifacts | [x] | d362c84 | 76 files untracked |
| 2. Update .gitignore | [x] | d362c84 | 80 → 50 lines |
| 3. Delete stale files | [x] | d362c84 | 7 handoffs + backups |
| 4. Consolidate docs | [x] | bf73fbe | 3 docs → 1 |
| 5. Cleanup script | [x] | bf73fbe | 3 modes working |
| 6a. Decouple KiCraft | [x] | 7c7df2c | All hardcodes removed |
| 6b. Extract to new repo | [x] | 7d9e56c | 91 files, pyproject.toml, 7/7 tests pass |
| 6c. Reintegrate | [x] | 7d9e56c | submodule + pip install -e, pipeline verified |

---

## Risk Assessment

| Action | Risk | Mitigation |
|---|---|---|
| Untracking .experiments/ | Lose experiment history in git | All data is regenerable pipeline output |
| Deleting handoff files | Lose context | Content duplicated in CHANGELOG.md |
| Blanket `.experiments/` gitignore | Might miss wanted file | Nothing in .experiments/ is source |
| KiCraft separation | Breaks current workflow | Phase 6a (decouple) is low-risk prep |

---

## Completion Log

### 2025-07-11 — Phases 1-5 + 6a completed

**Commits:**
- `d362c84` — Phases 1-3: Untrack 76 generated artifacts, simplify .gitignore, delete stale files
- `bf73fbe` — Phases 4-5: Consolidate docs, add clean_experiments.py
- `10a4543` — Phase 6a: Remove LLUPS_CONFIG, llups_config.json, fix POWER_NETS
- `c89bb32` — Phase 6a: Auto-detect in autoexperiment.py, run_hierarchical_pipeline.py, dashboard_app.py
- `7c7df2c` — Phase 6a: Parameterize GUI and remaining scripts

**Results:**
- Tracked files: 196 → 114 (42% reduction)
- Generated artifacts: removed ~129K lines from git history
- .gitignore: 80 lines → 50 lines (clean, organized)
- LLUPS-specific hardcodes in KiCraft: eliminated from functional code
- Cleanup script: working with --before-run, --after-run, --nuke modes
- Documentation: consolidated from 3 roadmap docs to 1

**Remaining:**
- Phase 6b: Extract KiCraft to separate repository
- Phase 6c: Reintegrate as submodule/dependency

### 2025-07-12 — Phases 6b + 6c completed

**Commits:**
- `9992d38` (KiCraft repo) — Initial commit: standalone Python package
- `7d9e56c` (LLUPS) — Phase 6b+6c: Extract and reintegrate as submodule

**Phase 6b — Extract KiCraft to standalone repo:**
- Created `/home/jason/Documents/KiCraft/` with proper Python package structure
- `kicraft/` package with autoplacer, scoring, gui, cli subpackages
- `pyproject.toml` with 30+ CLI entry points (`solve-subcircuits`, `autoexperiment`, etc.)
- All imports converted to `kicraft.*` package prefix
- sys.path hacks removed (kept only pcbnew path helper)
- Added `main()` wrappers to `parse_schematic.py` and `add_gnd_zone.py`
- 7/7 import tests pass
- Git repo initialized on `main` branch

**Phase 6c — Reintegrate into LLUPS:**
- Removed `.claude/skills/KiCraft/scripts/` (62 files)
- Removed `gui/` from LLUPS root (19 files)
- Added KiCraft as git submodule at `KiCraft/`
- `pip install -e KiCraft/` provides all CLI entry points
- Updated `AGENTS.md` with new paths and `solve-subcircuits` CLI command
- Updated `.claude/skills/KiCraft/SKILL.md` for submodule layout
- Pipeline verification: all 6 leaves solved + routed, parent assembled — zero tracebacks

**Results:**
- LLUPS tracked files: 114 → 32 (72% reduction from original 196)
- KiCraft: 91 files in standalone repo with proper packaging
- All CLI commands available as installed entry points
- Subcircuit pipeline verified end-to-end through new package structure

**All phases complete.** The cleanup plan is fully executed.
