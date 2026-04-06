# PCB Layout Experiment Program

Human-editable search space definition for `autoexperiment.py`.
Edit the JSON blocks below to steer the optimization.

## Parameter Ranges

Each entry: `[min, max, sigma_fraction]` where sigma controls mutation step size.
Only override parameters you want to constrain — unlisted params use defaults.

```json
{
  "param_ranges": {
    "force_attract_k": [0.01, 0.5, 0.15],
    "force_repel_k": [5.0, 200.0, 0.15],
    "cooling_factor": [0.90, 0.995, 0.05],
    "edge_margin_mm": [1.0, 5.0, 0.1],
    "clearance_mm": [0.15, 1.0, 0.1],
    "existing_trace_cost": [1.0, 50.0, 0.2],
    "max_rips_per_net": [2, 15, 0.2]
  }
}
```

## Scoring Weights

How much each metric contributes to the unified score.
Route completion dominates — a board that routes all nets with mediocre
placement beats a beautifully placed board with failed routes.

```json
{
  "score_weights": {
    "placement": 0.20,
    "route_completion": 0.50,
    "trace_efficiency": 0.20,
    "via_penalty": 0.10
  }
}
```

## Strategy Notes

- **Minor tweaks**: perturb 1-3 continuous params by gaussian noise.
  Same placement seed — refines the current layout.
- **Major changes**: fresh placement seed + aggressive param resample.
  Escapes local optima by exploring a totally different initial layout.
- Plateau detection: after N minor rounds with no improvement,
  automatically escalate to MAJOR.
- Tune `--plateau` flag to control exploration vs exploitation.
  Lower = more exploration, higher = more exploitation.

## Ideas to Try

- Narrow `force_attract_k` range if layouts are consistently too spread out
- Increase `existing_trace_cost` range if traces are crossing too much
- Lower `clearance_mm` min if the board is too tight to route
- Raise `max_rips_per_net` if routing keeps failing on congested nets
