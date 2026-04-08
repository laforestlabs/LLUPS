# Dashboard Automation Options

This page outlines practical ways to keep dashboard artifacts fresh with minimal manual work.

## Web Dashboard (Recommended)

The new Flask dashboard provides live monitoring and control with minimal setup:

```bash
# Start dashboard daemon
python3 .claude/skills/kicad-helper/scripts/dashboard_app.py --port 5000
```

Features:
- Live status (round progress, best score, kept count)
- Interactive score chart
- Start/Stop buttons
- Log viewer
- Runs as separate daemon - zero performance impact on experiments

## One-Command Local Refresh

For static outputs, use this sequence:

```bash
python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb --rounds 100
python3 .claude/skills/kicad-helper/scripts/plot_experiments.py .experiments/experiments.jsonl .experiments/experiments_dashboard.png
python3 .claude/skills/kicad-helper/scripts/score_layout.py LLUPS_best.kicad_pcb
```

This is the simplest option and matches your current workflow.

## Canonical "Latest" Artifacts Strategy

Keep these stable paths as latest outputs:

- `.experiments/experiments_dashboard.png`
- `.experiments/progress.gif`
- `.experiments/run_status.json`
- `.experiments/run_status.txt`
- `.experiments/best/best.kicad_pcb`

Store historical runs separately (timestamped directories or archived JSONL files) so README always points to a stable latest snapshot.

## GitHub Actions (Optional)

For automatic cloud refresh:

- Trigger: manual (`workflow_dispatch`) and/or nightly (`schedule`)
- Steps:
  - set up Python + KiCad CLI environment
  - run `autoexperiment.py` for bounded rounds
  - run `plot_experiments.py`
  - upload PNG/GIF/JSONL as workflow artifacts
- Optional follow-up:
  - commit refreshed `.experiments` assets back to a branch (or docs branch)

This avoids running long optimization locally when you only need periodic updates.

## Lightweight Web Report (Optional Future)

If you want better drill-down than a static PNG:

- Convert `experiments.jsonl` into a single HTML report with sortable tables and trend charts.
- Publish to GitHub Pages.
- Keep README with one image and a link to the interactive report.

## Practical Defaults

- Short sanity run: `--rounds 20`
- Typical local run: `--rounds 100`
- Long exploration: `--rounds 500 --plateau 8`
- Keep `--no-render` for quick tuning and re-enable rendering for publishable runs.

## Logging System

Enable detailed logging with `--log-level DEBUG`:

```bash
python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb --log-level DEBUG
```

Logs are written to `.experiments/debug.log`:
- `experiment_started` - configuration and parameters
- `baseline_complete` - baseline score, DRC counts
- `new_best` - when score improves
- `round_discarded` - when round doesn't improve
- `stop_requested` - graceful stop signal received
- `experiment_completed` - final results

The logging system uses async writes to avoid blocking experiment performance.
