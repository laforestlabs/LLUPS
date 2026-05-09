# LLUPS Project Rules


## Commit As You Go

Commit work incrementally as logical units are completed -- do not batch all changes into a single commit at the end of a session. Each commit should represent a coherent, self-contained change (a feature, a bugfix, a refactor, a test addition, etc.).

Rules:
- After completing a logical unit of work, commit it immediately
- For submodule repos (e.g. KiCraft/), commit inside the submodule first, then update the submodule pointer in the parent repo
- Do not wait until the end of a session to commit everything at once
- If multiple unrelated changes accumulate uncommitted, split them into separate commits by topic
- Commit messages follow conventional commits style (feat:, fix:, chore:, docs:, test:, refactor:)

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

After making changes to the subcircuits/autoplacer pipeline (`brain/placement_solver.py`, `brain/placement_scorer.py`, `brain/placement_utils.py`, `brain/types.py`, `config.py`, `brain/subcircuit_*.py`, `freerouting_runner.py`, `hardware/adapter.py`, `solve_subcircuits.py`, `compose_subcircuits.py`, or related hierarchical pipeline modules), always run the subcircuit pipeline once before considering the task complete.

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
2. Leaf subcircuits are solved through the FreeRouting-backed path
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
    - `brain/placement_solver.py` -- Force-directed placement solver
    - `brain/placement_scorer.py` -- Placement quality scorer
    - `brain/placement_utils.py` -- Shared placement geometry helpers
    - `brain/leaf_passive_ordering.py` -- Passive topology ordering
    - `brain/leaf_geometry.py` -- Leaf geometry bounds and reduction
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
python -c "from kicraft.autoplacer.brain.placement_solver import PlacementSolver; from kicraft.autoplacer.brain.placement_scorer import PlacementScorer; from kicraft.autoplacer.brain.placement_utils import _update_pad_positions, compute_min_board_size; from kicraft.autoplacer.brain.types import BoardState, Component, Point, SubCircuitLayout; from kicraft.autoplacer.brain.subcircuit_solver import infer_interface_anchors; from kicraft.autoplacer.brain.subcircuit_composer import build_parent_composition; from kicraft.autoplacer.brain.subcircuit_instances import load_solved_artifact, transform_subcircuit_instance; from kicraft.autoplacer.brain.subcircuit_extractor import extract_leaf_board_state; from kicraft.autoplacer.brain.hierarchy_parser import parse_hierarchy; from kicraft.autoplacer.config import DEFAULT_CONFIG; from kicraft.cli.solve_subcircuits import main as solve_main; from kicraft.cli.compose_subcircuits import main as compose_main; from kicraft.autoplacer.brain.leaf_acceptance import evaluate_leaf_acceptance, acceptance_config_from_dict; from kicraft.autoplacer.brain.copper_accounting import build_copper_manifest, verify_copper_preservation, CopperManifest; from kicraft.autoplacer.brain.leaf_passive_ordering import apply_leaf_passive_ordering, build_leaf_passive_topology_groups; from kicraft.autoplacer.brain.leaf_geometry import tight_leaf_geometry_bounds; print('All critical imports OK')"
```

### 3. Full pipeline verification (slow - run after structural changes)

Only required after changes to pipeline modules listed in the Verification section above.

```bash
solve-subcircuits LLUPS.kicad_sch --pcb LLUPS.kicad_pcb --rounds 1 --route
```

### When to run what

| Change type | pytest | import smoke | pipeline | stamp smoke |
|------------|--------|-------------|----------|-------------|
| Any Python file in KiCraft | Yes | Yes | - | - |
| brain/*.py, cli/solve_subcircuits.py, cli/compose_subcircuits.py, freerouting_runner.py | Yes | Yes | Yes | - |
| Tests, docs, comments only | Yes | - | - | - |
| `_stamp_subcircuit_subprocess.py`, `_parent_stamp_subprocess.py`, `adapter._apply_board_outline`, `adapter.stamp_subcircuit_board*`, `compose._stamp_parent_board`, anything that introspects pcbnew `GetDrawings()`/`Footprints()`/`GetTracks()`/`Zones()` | Yes | Yes | - | Yes |

### 4. Stamp smoke test (~30 s - run after touching either subprocess script)

```bash
python tools/smoke_stamp.py
```

Exercises BOTH the leaf stamp path (`solve_subcircuits` →
`adapter.stamp_subcircuit_board_subprocess` →
`_stamp_subcircuit_subprocess.py`) AND the parent stamp path
(`compose_subcircuits._stamp_parent_board` →
`_parent_stamp_subprocess.py`) on a single small leaf plus the saved
manual layout. Exits non-zero with the failing script's stderr.

Why: these are two different (now lifted) subprocess scripts.
Testing only one (e.g. running `compose_subcircuits` and assuming
the leaf path works the same way) is exactly how the May 2026
"`AttributeError: 'PCB_TEXT' object has no attribute 'GetShape'`"
regression slipped through review -- the parent stamp had no silk
text on F.Silkscreen so the bad filter ran clean, while every leaf
solve failed and degraded to "routing_exception" with cached
on-disk leaves still being reported as "accepted."

Treat any failure here as blocking until fixed.

### Defensive coding rules for pcbnew API

* **Never call `board.GetDrawings()` / `Footprints()` / `GetTracks()`
  / `Zones()` more than once across a board mutation in the same
  process.** KiCad 9's SWIG bindings return a non-iterable
  `SwigPyObject` from the second call once the board has been
  mutated. Snapshot all four containers via `list(...)` UPFRONT,
  before any `board.Add` / `board.Remove` of footprints, then
  iterate the captured Python lists.
* **Don't call `GetShape()` / `GetWidth()` on the result of
  `board.GetDrawings()` without `hasattr` guards.** That iterator
  returns a heterogeneous mix of `PCB_SHAPE`, `PCB_TEXT`,
  `PCB_DIMENSION`, etc.; only `PCB_SHAPE` exposes those methods.
  Filtering by `GetLayer()` is safe (every drawing has it). Anything
  shape-specific must guard or wrap in `try/except`.
* **Inline subprocess scripts are off-limits for new code.** When
  you need a fresh pcbnew interpreter, write a real `.py` file under
  `kicraft/autoplacer/hardware/` or `kicraft/cli/` and invoke it
  via `_run_pcbnew_script_file(SCRIPT_PATH, *args)`. Inline strings
  are not lintable, not type-checkable, and obscure stack traces.
  The two stamping scripts already follow this pattern --
  `_stamp_subcircuit_subprocess.py` and `_parent_stamp_subprocess.py`.
