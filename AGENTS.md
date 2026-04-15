# LLUPS Project Rules

## Verification After Code Changes

After making any changes to the autoplacer code (`brain/placement.py`, `brain/types.py`, `config.py`, or other autoplacer modules), always run a short autoexperiment to verify the changes work correctly before considering the task complete.

### Quick verification command

```bash
python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb \
  --rounds 3 \
  --program .claude/skills/kicad-helper/scripts/program.md \
  --save-all \
  --verbose
```

### What to check in the output

1. No Python exceptions or tracebacks
2. Placement scores are reasonable (not drastically worse than ~60-80 range)
3. No warnings about pads outside the board after clamp passes
4. Battery holders (BT1, BT2) are aligned as a pair in the log output
5. The run completes all 3 rounds without hanging

### When to skip verification

- Pure comment or documentation changes
- Changes to files outside the autoplacer package (e.g. render scripts, scoring-only changes)

## Project Structure

- `LLUPS.kicad_pcb` — Main PCB layout file
- `.claude/skills/kicad-helper/scripts/autoplacer/` — Autoplacer package
  - `brain/placement.py` — Core placement solver and force simulation
  - `brain/types.py` — Data types and scoring weights
  - `config.py` — Default and LLUPS-specific configuration
  - `hardware/adapter.py` — KiCad pcbnew API interface
- `.claude/skills/kicad-helper/scripts/autoexperiment.py` — Experiment runner
- `.claude/skills/kicad-helper/scripts/program.md` — Search space definition
