# Monitoring & Reports Guide

How to watch your layout evolve during an optimization run, and how to analyze results after it finishes.

> **Performance note:** All monitoring methods are read-only. They read output files written by the experiment loop — they never interfere with it and add zero overhead to the optimization.

---

## Quick Start

Open two terminals. In the first, start an experiment:

```bash
python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb --rounds 100
```

In the second, pick one of these to watch progress:

| Method | Command | What you see |
|--------|---------|-------------|
| **Web dashboard** | `python3 .claude/skills/kicad-helper/scripts/dashboard_app.py --port 5000` then open `http://localhost:5000` | Live score chart, round table, log viewer, start/stop controls |
| **Terminal status** | `watch -n2 cat .experiments/run_status.txt` | One-line summary: round, best score, ETA, kept count |
| **Live HTML report** | `xdg-open report.html` | Rebuilt after each round and auto-refreshes while the run is active |
| **Watch frames** | `ls -lt .experiments/frames/ \| head` | PNG snapshots appearing as each round completes |

After the run finishes, the best outputs are ready:

```bash
# Animated layout evolution
xdg-open .experiments/progress.gif

# Multi-panel score dashboard
xdg-open .experiments/experiments_dashboard.png

# Interactive HTML report (richest view — rebuilt live during runs, filterable tables, per-net analysis)
python3 .claude/skills/kicad-helper/scripts/generate_report.py .experiments/ -o report.html
xdg-open report.html
```

---

## What the Experiment Produces

Every run writes to the `.experiments/` directory. Here is every artifact, when it appears, and how to use it.

### Updated Every Round (live)

| File | Format | Contents |
|------|--------|----------|
| `report.html` | HTML | Interactive report rebuilt after each completed round; auto-refreshes while the run is active |
| `run_status.json` | JSON | Machine-readable status: round, best score, ETA, worker counts, throughput |
| `run_status.txt` | Text | Human-readable one-liner of the same status |
| `experiments.jsonl` | JSONL | One JSON record per round — full scoring breakdown, config delta, DRC counts, timing |
| `rounds/round_NNNN.json` | JSON | Comprehensive detail for one round: per-net routing results, DRC violation coordinates, phase timing |
| `frames/frame_NNNN.png` | PNG | Board snapshot with score overlay, colored border (green=kept, red=shorts, gray=discarded) |
| `best/best.kicad_pcb` | KiCad PCB | Current best layout (updated only when score improves) |

### Generated After Run Completes

| File | Format | Contents |
|------|--------|----------|
| `.experiments/report.html` | HTML | Final self-contained copy of the interactive report |
| `progress.gif` | GIF | Animated sequence of all frame PNGs showing layout evolution |
| `experiments_dashboard.png` | PNG | Multi-panel matplotlib figure (see [Dashboard Panels](#dashboard-panels-png) below) |

### Generated On Demand

| Command | Output | Contents |
|---------|--------|----------|
| `generate_report.py .experiments/ -o report.html` | HTML | Self-contained interactive report (see [HTML Report](#html-report) below) |
| `plot_experiments.py .experiments/experiments.jsonl out.png` | PNG | Regenerate the dashboard PNG from history |
| `render_drc_overlay.py LLUPS.kicad_pcb .experiments/rounds/round_NNNN.json` | PNG | Board image with DRC violation markers overlaid |
| `render_failure_heatmap.py .experiments/ LLUPS.kicad_pcb` | PNG | Heatmap of routing failure hotspots on the board |

All scripts are in `.claude/skills/kicad-helper/scripts/`.

---

## Monitoring During a Run

### Web Dashboard (recommended)

The dashboard is the easiest way to watch a run in real time.

```bash
python3 .claude/skills/kicad-helper/scripts/dashboard_app.py --port 5000
```

Open `http://localhost:5000` in any browser. The page auto-refreshes every few seconds.

**What you see:**
- **Status bar** — current round / total, best score, kept count, elapsed time, ETA
- **Score chart** — live-updating plot of score per round, with kept/discarded markers
- **Round table** — filterable, sortable; click a row to expand full detail (timing, per-net routing, DRC)
- **Log viewer** — tails `.experiments/debug.log`
- **Start/Stop controls** — start a new run or gracefully stop the current one

**Stopping a run:** Click the Stop button in the dashboard, or from the terminal:

```bash
python3 .claude/skills/kicad-helper/scripts/dashboard_app.py --stop
# or simply:
touch .experiments/stop.now
```

The experiment finishes its current round and exits cleanly.

### Terminal Status

If you prefer not to run a web server:

```bash
watch -n2 cat .experiments/run_status.txt
```

This prints a refreshing one-liner with round number, best score, ETA, and kept count.

For machine-readable status (useful for scripting):

```bash
cat .experiments/run_status.json | python3 -m json.tool
```

### Watching Frames

Each round writes a snapshot PNG to `.experiments/frames/`. You can watch them appear:

```bash
watch -n5 'ls .experiments/frames/*.png | wc -l'
```

Each frame shows the board layout with an overlay: round number, score, elapsed time, and a colored border indicating whether the round was kept or discarded.

---

## Analyzing Results After a Run

### Progress GIF

The animated GIF is the fastest way to see how the layout evolved across all rounds.

```bash
xdg-open .experiments/progress.gif
```

Each frame is one round. Green border = kept improvement. Red border = shorts detected. Gray border = discarded (no improvement). The score and round number are overlaid on each frame.

### Dashboard Panels (PNG)

```bash
xdg-open .experiments/experiments_dashboard.png
```

The dashboard PNG contains up to five panels:

1. **Score per round** — Dots per round (green=kept, gray=discarded, diamond=major mutation), with a running-best line
2. **Scoring breakdown** — Line chart of the six sub-scores: placement, route completion, trace efficiency, via score, courtyard overlap, board containment
3. **DRC violations** — Stacked bar chart: shorts, unconnected, clearance, courtyard violations per round
4. **Phase timing** — Stacked bar chart: placement and routing time per round (in seconds)
5. **Config sensitivity** — Heatmap of normalized parameter values for kept runs only

To regenerate this from history (e.g., after adjusting `plot_experiments.py`):

```bash
python3 .claude/skills/kicad-helper/scripts/plot_experiments.py \
  .experiments/experiments.jsonl \
  .experiments/experiments_dashboard.png
```

### HTML Report

The richest post-run view. A single self-contained HTML file with no external dependencies — works offline.

```bash
python3 .claude/skills/kicad-helper/scripts/generate_report.py .experiments/ -o report.html
xdg-open report.html
```

**Sections:**

| Section | What it shows |
|---------|--------------|
| **Summary cards** | Total rounds, improvements kept, best score, total time, worst shorts count, number of failing nets |
| **Score timeline** | Interactive chart — dots colored by outcome (green=kept, red=major fail, gray=discard) with running-best line |
| **Round browser** | Filterable + sortable table with columns: Round, Score, Mode, Duration, Routed, Vias, Shorts, DRC, Status. Click a row to expand timing breakdown and per-net success/failure detail |
| **Net failure analysis** | Top 50 failing nets ranked by failure count, with failure modes |
| **Shorts dashboard** | All rounds that had shorts — nets involved, coordinates |
| **Config sensitivity** | Scatter plot per tunable parameter (X=value, Y=score, color=kept/discard) |

### DRC Overlay

Visualize exactly where DRC violations occur on the board for a specific round:

```bash
python3 .claude/skills/kicad-helper/scripts/render_drc_overlay.py \
  LLUPS.kicad_pcb \
  .experiments/rounds/round_0042.json \
  --output drc_overlay.png
```

Markers: red X = short, orange circle = unconnected, yellow halo = clearance violation, magenta rectangle = courtyard overlap.

### Failure Heatmap

See which board areas have the most routing failures across all rounds:

```bash
python3 .claude/skills/kicad-helper/scripts/render_failure_heatmap.py \
  .experiments/ LLUPS.kicad_pcb \
  --output failure_heatmap.png
```

Produces a color-graded heatmap overlaid on the board outline, with the top 10 failing nets annotated.

---

## Dependencies

| Feature | Requires | Install |
|---------|----------|---------|
| Experiment loop + GIF frames | kicad-cli, ImageMagick | System packages |
| Web dashboard | Flask | `pip install flask` |
| Dashboard PNG | matplotlib, numpy | `pip install matplotlib numpy` |
| Failure heatmap (blur) | scipy | `pip install scipy` (optional — works without, just no blur) |
| HTML report | *(stdlib only)* | Nothing extra |

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Dashboard page shows "idle" | No experiment running, or experiments dir doesn't exist | Start an experiment first; check `--experiments-dir` path |
| No frames appearing | `kicad-cli` not installed or not on PATH | Install KiCad 9 and ensure `kicad-cli` is available |
| GIF not generated | Run was stopped early (frames exist but GIF assembly didn't run) | Run `convert -dispose Background -delay 40 .experiments/frames/frame_*.png .experiments/progress.gif` |
| Dashboard PNG missing | matplotlib not installed | `pip install matplotlib numpy` |
| Status shows "maybe_stuck" | A round is taking much longer than average | Usually resolves on its own; complex layouts take longer. Check `debug.log` for errors |
| Experiment won't stop | `stop.now` not in the right directory | `touch .experiments/stop.now` — must be inside the `.experiments/` dir used by the run |

---

## Useful Run Configurations

```bash
# Quick sanity check (fast, ~5 min)
python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb --rounds 20

# Standard run
python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb --rounds 100

# Long exploration with aggressive plateau escape
python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb --rounds 500 --plateau 8

# Verbose logging (writes .experiments/debug.log)
python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb --rounds 100 --log-level DEBUG
```
