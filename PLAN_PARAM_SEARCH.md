# Overnight parameter sweep plan

> Status: launched 2026-04-27 evening; results land in `.experiments/param_sweep/`.
> Goal: discover the best **default value** and the best **search range** for
> every parameter in `KiCraft/.../config.py::CONFIG_SEARCH_SPACE`.

## Why two stages

The KiCraft autoexperiment loop already supports the "solve leaves first, pin
best leaves, solve parent" workflow via `--leaves-only` and `--parents-only`.
Splitting the sweep along that boundary gives:

- **Cleaner per-stage signal.** Stage A varies leaf-side knobs while parent
  composition is suppressed; Stage B fixes the leaves and varies parent-side
  knobs. Each parameter is exercised in the phase where it actually changes
  the score.
- **Faster rounds.** Each stage skips the half it doesn't need.
- **Better coverage.** Random search with uniform sampling over each spec
  range avoids the greedy hill-climb bias of the default Gaussian-around-best
  mutator. (Implemented as `--random-search` on autoexperiment, KiCraft side.)

## Pipeline

```
Stage A: autoexperiment --leaves-only --random-search
   |   ~3hr / ~150 rounds (parents-only round budget tracking)
   v
tools/pin_best_leaves.py
   pick the highest-scoring round_NNNN_solved_layout.json per leaf,
   call pins.pin_leaf() so the canonical files reflect the best snapshot
   v
Stage B: autoexperiment --parents-only --random-search
   |   ~3.5hr / ~210 rounds
   v
tools/analyze_param_sweep.py
   per-param Pearson r in each stage, top-quintile median (-> default),
   top-quintile P10/P90 (-> range), reconcile across stages
   v
Validation: autoexperiment --rounds 5 with the proposed defaults applied
            (greedy mutation, full pipeline)
```

## Time budget

Defaults aim at ~7hr total wall-clock:

| phase            | budget      | per-round  | rounds (est) |
|------------------|-------------|------------|--------------|
| Stage A leaves   | 180 min     | ~70 s      | ~150         |
| pin best leaves  | <1 min      | -          | -            |
| Stage B parents  | 210 min     | ~60 s      | ~210         |
| analysis         | <1 min      | -          | -            |
| validation       | ~10 min     | ~120 s     | 5            |

Override via `--stage-a-budget-min` / `--stage-b-budget-min` on the
orchestrator.

## How to run

From the repo root:

```bash
python tools/run_overnight_param_sweep.py
# or with a fixed seed for reproducibility:
python tools/run_overnight_param_sweep.py --seed 12345
# smoke check (1 leaves-only round, ~70 s) without committing to the long run:
python tools/run_overnight_param_sweep.py --smoke-only
```

Interrupt-safe:

- `Ctrl-C` -> orchestrator drops `.experiments/stop.now`, autoexperiment
  finishes the current round and exits cleanly.
- Each phase is archived under `.experiments/param_sweep/<stage>/` after it
  completes, so a partial run still produces analyzable artifacts.

## Outputs

All under `.experiments/param_sweep/`:

```
stage_a/round_NNNN/round_config.json    # per-round overlay actually applied
stage_a/rounds/round_NNNN.json          # per-round result + score breakdown
stage_a.jsonl                           # autoexperiment event log
stage_a.stdout.log                      # full child stdout
stage_b/...                             # mirror of above for Stage B
pin_summary.json                        # which round was pinned per leaf
proposed_default_config.json            # OVERLAY: merge into DEFAULT_CONFIG
proposed_param_ranges.json              # bounds replacement for CONFIG_SEARCH_SPACE
analysis.md                             # per-param sensitivity table
raw_combined.jsonl                      # joined per-round (config, score, stage)
validation/                             # 5-round greedy run with proposed defaults
orchestrator.log                        # high-level phase log
```

## Analysis methodology

For each parameter `p` in `CONFIG_SEARCH_SPACE`:

1. Collect `(value, score)` pairs from each stage's round configs + JSONL.
2. Pearson `r_A`, `r_B` between value and score.
3. Top-quintile (top 20% by score) -> proposed default = median value;
   proposed range = `[P10, P90]`.
4. Trust the stage with higher `|r|` for that parameter.
5. If `max(|r_A|, |r_B|) < 0.10`, mark insensitive and keep the current
   default + range untouched.
6. A spec-span floor of 5% prevents the proposed range from collapsing to a
   single value when the top-quintile P10/P90 happens to coincide.

`proposed_default_config.json` is an OVERLAY -- it lists ONLY parameters where
the proposed default differs from the current `DEFAULT_CONFIG`. Same logic for
`proposed_param_ranges.json` vs `CONFIG_SEARCH_SPACE`.

## How to apply the recommendations

Manual review tomorrow:

1. Read `analysis.md` -- look at the top-of-table parameters (sorted by
   sensitivity) first, those are where defaults matter most.
2. Spot-check the validation summary: did 5 rounds at the new defaults beat
   the previous best score by a meaningful margin?
3. Apply the JSON overlays:
   - `proposed_default_config.json` -> patch into
     `KiCraft/kicraft/autoplacer/config.py::DEFAULT_CONFIG`.
   - `proposed_param_ranges.json` -> replace `min`/`max` in
     `CONFIG_SEARCH_SPACE` for the listed keys.
4. Run `pytest -x -q` and `verify-minimal.sh` after the patch.

## Code touched (this session)

- `KiCraft/kicraft/cli/autoexperiment.py`
  - new `_random_sample_config()` -- uniform-random alternative to the
    Gaussian `_mutate_config()`
  - new `--random-search` flag wired into the main loop (greedy default
    behaviour unchanged when the flag is absent)
- `tools/pin_best_leaves.py` -- post-Stage-A pin selector
- `tools/analyze_param_sweep.py` -- post-Stage-B sensitivity analyzer
- `tools/run_overnight_param_sweep.py` -- orchestrator
- (this file)

## Caveats / known limitations

- Random search treats parameter sensitivity as monotone-and-independent.
  For interaction effects (e.g. SA cooling rate x SA initial temperature),
  the proposed default is still a sensible starting point but follow-up
  Gaussian search around it is what closes the last few points of score.
- Top-quintile P10/P90 needs ~30-50 samples per parameter to be stable. Stage
  B at 210 rounds gives that comfortably; Stage A at 150 is on the edge for
  rarely-mutated knobs.
- Pinned leaves freeze leaf-side params during Stage B, so anything classified
  as "leaf-side" but appearing in Stage B's correlation table is noise.
  `analysis.md` chooses the higher-`|r|` stage per parameter, which handles
  this automatically.
