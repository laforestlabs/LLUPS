# LLUPS Project Rules


## Text Formatting Rule

Never use special Unicode characters in code, comments, documentation, or commit messages. This includes:
- No emdash or endash (use -- or - instead)
- No smart quotes or curly quotes (use straight quotes and double quotes only)
- No ellipsis character (use three dots ... instead)
- No non-breaking spaces (use regular spaces)
- No other fancy Unicode punctuation

Stick to plain ASCII for all text content.

## Session Continuity / Handoff Rule

When a work session is getting long, approaching context limits, or ending before the implementation plan is complete, write a concise continuation handoff before stopping.

### Required handoff contents

Record enough detail that the next session can continue immediately without re-discovery:

1. what was completed
2. what remains next, in priority order
3. exact files touched
4. exact verification commands already run and their outcomes
5. any open bugs, misleading behaviors, or known limitations
6. the next recommended implementation step
7. if useful, the latest commit hashes relevant to the work

### Preferred locations

Persist the handoff in at least one durable place inside the repo, preferably:
- `CHANGELOG.md` for user-visible progress notes, and/or
- a focused next-steps note near the affected pipeline code

Also include a short chat summary, but do not rely on chat history alone for continuity.

## Verification After Code Changes

After making changes to the subcircuits/autoplacer pipeline (`brain/placement.py`, `brain/types.py`, `config.py`, `brain/subcircuit_*.py`, `freerouting_runner.py`, `hardware/adapter.py`, `solve_subcircuits.py`, `compose_subcircuits.py`, or related hierarchical pipeline modules), always run the subcircuit pipeline once before considering the task complete.

### Required verification command

```bash
solve-subcircuits LLUPS.kicad_sch \
  --pcb LLUPS.kicad_pcb \
  --rounds 1 \
  --route
```

Alternatively, if the CLI entry point is not on PATH:

```bash
python -m kicraft.cli.solve_subcircuits LLUPS.kicad_sch \
  --pcb LLUPS.kicad_pcb \
  --rounds 1 \
  --route
```

### What to check in the output

1. No Python exceptions or tracebacks
2. Leaf subcircuits are solved through the real routed path, not a heuristic fallback
3. Accepted artifacts are written under `.experiments/subcircuits/`
4. Each accepted routed leaf artifact persists canonical copper in `solved_layout.json`
5. The run completes without hanging in the leaf pipeline

### Visual/full-pipeline direction

The target verification flow for this branch is evolving toward a single user-visible hierarchical run that:

1. solves the lowest-level leaf subcircuits first
2. routes those leaves with FreeRouting
3. persists accepted routed leaf artifacts
4. assembles higher-level parents from those routed children layer by layer like legos
5. preserves child copper during parent composition
6. reaches the complete top-level parent circuit in a visually inspectable way

When extending the pipeline, prefer work that moves verification toward that full start-to-finish hierarchical run rather than isolated demo polish.

### When to skip verification

- Pure comment or documentation changes
- Changes to files outside the subcircuits/autoplacer pipeline

## Project Structure

- `LLUPS.kicad_pcb` — Main PCB layout file
- `LLUPS_autoplacer.json` — Project-specific autoplacer configuration
- `KiCraft/` — Git submodule: KiCad automation toolkit (pip install -e KiCraft/)
  - `kicraft/autoplacer/` — Placement and routing engine
    - `brain/placement.py` — Core placement solver and force simulation
    - `brain/types.py` — Data types and scoring weights
    - `config.py` — Default configuration + project config loader
    - `hardware/adapter.py` — KiCad pcbnew API interface
  - `kicraft/scoring/` — Layout quality scoring checks
  - `kicraft/gui/` — NiceGUI experiment manager
  - `kicraft/cli/` — CLI entry-point scripts
    - `autoexperiment.py` — Experiment runner
    - `solve_subcircuits.py` — Subcircuit placement and routing
    - `program.md` — Search space definition
- `.claude/skills/KiCraft/SKILL.md` — Claude skill definition


## Minimal Test Gate After Code Changes

After any code change to KiCraft Python files, run these two checks before committing:

### 1. Unit tests (fast - must always pass)

```bash
cd KiCraft && python -m pytest -x -q
```

This runs in under 1 second. All tests must pass, no skips on core logic.

### 2. Import smoke test (fast - must always pass)

```bash
python -c "from kicraft.autoplacer.brain.placement import PlacementSolver, PlacementScorer; from kicraft.autoplacer.brain.types import BoardState, Component, Point, SubCircuitLayout; from kicraft.autoplacer.brain.subcircuit_solver import solve_leaf_placement, route_interconnect_nets; from kicraft.autoplacer.brain.subcircuit_composer import build_parent_composition; from kicraft.autoplacer.brain.subcircuit_instances import load_solved_artifact, transform_subcircuit_instance; from kicraft.autoplacer.brain.subcircuit_extractor import extract_leaf_board_state; from kicraft.autoplacer.brain.hierarchy_parser import parse_hierarchy; from kicraft.autoplacer.config import DEFAULT_CONFIG; from kicraft.cli.solve_subcircuits import main as solve_main; from kicraft.cli.compose_subcircuits import main as compose_main; from kicraft.autoplacer.brain.leaf_acceptance import evaluate_leaf_acceptance, acceptance_config_from_dict; from kicraft.autoplacer.brain.copper_accounting import build_copper_manifest, verify_copper_preservation, CopperManifest; print('All critical imports OK')"
```

### 3. Full pipeline verification (slow - run after structural changes)

Only required after changes to pipeline modules listed in the Verification section above.

```bash
solve-subcircuits LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route
```

### When to run what

| Change type | pytest | import smoke | pipeline |
|------------|--------|-------------|----------|
| Any Python file in KiCraft | Yes | Yes | - |
| brain/*.py, cli/solve_subcircuits.py, cli/compose_subcircuits.py, freerouting_runner.py | Yes | Yes | Yes |
| Tests, docs, comments only | Yes | - | - |
