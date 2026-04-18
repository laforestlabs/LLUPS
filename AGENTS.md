# LLUPS Project Rules

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
python3 .claude/skills/kicad-helper/scripts/solve_subcircuits.py LLUPS.kicad_sch \
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
- `.claude/skills/kicad-helper/scripts/autoplacer/` — Autoplacer package
  - `brain/placement.py` — Core placement solver and force simulation
  - `brain/types.py` — Data types and scoring weights
  - `config.py` — Default and LLUPS-specific configuration
  - `hardware/adapter.py` — KiCad pcbnew API interface
- `.claude/skills/kicad-helper/scripts/autoexperiment.py` — Experiment runner
- `.claude/skills/kicad-helper/scripts/program.md` — Search space definition
