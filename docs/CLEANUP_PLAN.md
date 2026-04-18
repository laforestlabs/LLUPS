# LLUPS Repository Cleanup & Reorganization Plan

**Created:** 2025-07-11
**Status:** In Progress

## Overview

This plan covers 7 phases of cleanup and reorganization for the LLUPS repository.
Each phase has a checkbox for tracking. Mark phases `[x]` as they are completed.

---

## Phase 1: Untrack Generated Artifacts from Git  [ ]

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
git rm --cached .claude/skills/kicad-helper/scripts/autoplacer/brain/placement.py.bak
```

### Verification

- `git ls-files .experiments/ | wc -l` should return 0
- `git ls-files | wc -l` should drop from 196 to ~112

---

## Phase 2: Update .gitignore  [ ]

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
.claude/skills/kicad-helper/scripts/results/

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

## Phase 3: Delete Stale Files from Disk  [ ]

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
rm .claude/skills/kicad-helper/scripts/HANDOFF_2026-04-17_*.md
rm .claude/skills/kicad-helper/scripts/NEXT_AGENT_PROMPT_2026-04-17_*.md
rm .claude/skills/kicad-helper/scripts/autoplacer/brain/placement.py.bak
rm -f LLUPS.kicad_sch.bak
rmdir LLUPS-backups/ 2>/dev/null
rm -rf __pycache__/
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null
find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null
rm -rf .claude/skills/kicad-helper/scripts/results/
```

---

## Phase 4: Consolidate Documentation  [ ]

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

## Phase 5: Automatic Artifact Cleanup Script  [ ]

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

Location: `.claude/skills/kicad-helper/scripts/clean_experiments.py`

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

## Phase 6: Separate kicad-helper into Its Own Codebase  [ ]

### Coupling analysis

kicad-helper is ~95% generic. LLUPS-specific content in exactly 3 files:

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
- Create `kicad-helper` repository
- Move scripts + autoplacer + scoring + gui as `kicad_helper` package
- Add `pyproject.toml` with CLI entry points
- Add minimal test suite

**6c — Reintegrate:**
- Add kicad-helper as git submodule or pip dependency in LLUPS
- Update `AGENTS.md`, `SKILL.md` for new paths

### Target standalone structure

```
kicad-helper/
├── pyproject.toml
├── kicad_helper/
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
| 1. Untrack artifacts | [ ] | | |
| 2. Update .gitignore | [ ] | | |
| 3. Delete stale files | [ ] | | |
| 4. Consolidate docs | [ ] | | |
| 5. Cleanup script | [ ] | | |
| 6a. Decouple kicad-helper | [ ] | | |
| 6b. Extract to new repo | [ ] | | |
| 6c. Reintegrate | [ ] | | |

---

## Risk Assessment

| Action | Risk | Mitigation |
|---|---|---|
| Untracking .experiments/ | Lose experiment history in git | All data is regenerable pipeline output |
| Deleting handoff files | Lose context | Content duplicated in CHANGELOG.md |
| Blanket `.experiments/` gitignore | Might miss wanted file | Nothing in .experiments/ is source |
| kicad-helper separation | Breaks current workflow | Phase 6a (decouple) is low-risk prep |
