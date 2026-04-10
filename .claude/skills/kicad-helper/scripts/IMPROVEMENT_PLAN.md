# Autoplacer Improvement Plan

Date: 2026-04-09
Context: 28-round autoexperiment post-bugfix. Best score 21.83, 13/26 nets routed, 31 shorts. 3 nets never route. Stagnation after round 8.

---

## Diagnosis Summary

### Current Performance
- Best: score=21.83, routed=13/26, shorts=31, DRC=276
- Score range: 13.28–21.83 across 28 rounds (tight band = limited exploration)
- 3/28 kept (10.7% acceptance) — stagnated for 20 consecutive rounds

### Root Causes (ordered by impact)

1. **Grid resolution too coarse (0.5mm)** — traces need 1mm min separation on grid vs 0.45mm physical. Wastes ~55% of routing capacity. This alone likely explains why 50% of nets fail.

2. **Routing order starves late nets** — power nets route first and mark HARD_BLOCK exclusion zones. The 3 always-failing nets (`/CHG_N`, `/NTC_SENSE`, `Net-(F1-Pad2)`) are signal nets in dense areas around U2/F1 that route last.

3. **Shorts penalty dominates scoring** — raw score 54.68 → final 21.83 after `÷2.5` shorts penalty. The optimizer can't distinguish between "good routing with shorts" and "bad routing without shorts."

4. **RRR too conservative** — only 2 victims per rip, 30s timeout. Can't clear enough congestion in dense areas.

5. **program.md ranges create DRC violations** — `clearance_mm` min=0.15 is below DRC minimum 0.2. `existing_trace_cost` min=1.0 has no effect (cross-net traces use HARD_BLOCK, not this parameter).

6. **Escape corridors too narrow** — 3 cells wide (1.5mm). A single routed trace blocks pad egress.

---

## Improvement Plan

### Phase 1: Quick Wins (config/parameter fixes, no architecture changes)

#### 1A. Fix program.md parameter ranges

**File:** `program.md`

Problems:
- `clearance_mm` min=0.15 is below DRC minimum (0.2mm), causes shorts
- `existing_trace_cost` range 1.0–50.0 has negligible effect (cross-net uses HARD_BLOCK=1e6, not this param)
- `force_repel_k` max=200 equals the config default, so MINOR can only decrease it

Fix:
```json
{
  "param_ranges": {
    "force_attract_k": [0.01, 0.3, 0.15],
    "force_repel_k": [50.0, 500.0, 0.15],
    "cooling_factor": [0.90, 0.995, 0.05],
    "edge_margin_mm": [2.0, 8.0, 0.1],
    "clearance_mm": [0.2, 0.35, 0.1],
    "max_rips_per_net": [3, 20, 0.2],
    "grid_resolution_mm": [0.25, 0.5, 0.15]
  }
}
```

Changes:
- `clearance_mm` min raised to 0.2 (DRC floor)
- Removed `existing_trace_cost` (not useful to tune)
- Added `grid_resolution_mm` as tunable (see 2A)
- `force_repel_k` range widened to 50–500
- `max_rips_per_net` max raised to 20

#### 1B. Make `grid_resolution_mm` tunable in mutations

**File:** `autoexperiment.py`, `mutate_config_minor` function (line ~230)

Add `grid_resolution_mm` to the `tunable` dict:
```python
"grid_resolution_mm": (0.25, 0.5, 0.15),
```

This lets the optimizer try finer grids (0.25mm = 4× more cells = much more routing capacity) at the cost of slower A* search. The tradeoff is automatic via the scoring loop.

Also add it to `mutate_config_major`'s aggressive_tunable:
```python
"grid_resolution_mm": (0.2, 0.5, 0.3),
```

#### 1C. Add `grid_resolution_mm` and RRR params to config defaults  

**File:** `config.py`

Ensure `DEFAULT_CONFIG` includes:
```python
"grid_resolution_mm": 0.5,
"max_rrr_iterations": 25,
"max_rips_per_net": 4,
"rrr_timeout_s": 30,
"rip_stagnation_limit": 4,
```

If any are missing, add them so mutations can perturb from a known baseline.

---

### Phase 2: Routing Improvements (targeted code changes)

#### 2A. Finer Grid Resolution (0.25mm default)

**File:** `config.py`

Change `grid_resolution_mm` default from 0.5 to 0.25.

Impact analysis:
- Grid size: 180×116×2 → 360×232×2 = ~167K cells (4× more)
- At 0.25mm, signal traces (0.127mm) still occupy 1 cell, but clearance-aware width `ceil((0.127+0.2)/0.25) = 2` cells = 0.5mm effective spacing (vs 1.0mm at 0.5 resolution)
- Doubles effective routing capacity in congested areas
- A* search ~4× slower per net — offset by `max_search` limit
- Consider raising `max_search` from 500K to 1M for the finer grid

**Risk:** Experiment round time may increase from ~130s to ~200-300s. Acceptable given routing improvement.

#### 2B. Net Priority for Always-Failing Nets

**File:** `router.py`, `_prioritize_nets` method (line ~360)

Currently all signal nets have priority=0. Add a mechanism to boost priority of historically failing nets:

Option A (simple): Add a `net_priority` config dict that maps net names to priority values:
```python
# In config.py DEFAULT_CONFIG:
"net_priority": {}

# In _prioritize_nets:
priority_overrides = self.cfg.get("net_priority", {})
for net in nets:
    if net.name in priority_overrides:
        net.priority = priority_overrides[net.name]
```

Then in `program.md`:
```json
{
  "net_priority": {
    "/CHG_N": 5,
    "/NTC_SENSE": 5,
    "Net-(F1-Pad2)": 5
  }
}
```

Option B (automatic): Track per-net failure rates across rounds in autoexperiment. After N rounds, boost priority of nets that fail >80% of the time. This is more complex but self-adapting.

**Recommendation:** Start with Option A (manual) since we know the failing nets. Add Option B later.

#### 2C. Wider Escape Corridors

**File:** `grid_builder.py`, `build_grid` function — the escape corridor section

Currently carves a 3-cell-wide corridor from pad to component edge. At 0.5mm resolution this is 1.5mm; at 0.25mm it's 0.75mm. Either way, a single routed trace (width + clearance ≈ 2 cells) fills the corridor.

Fix: Widen escape corridors to `max(5, ceil(3 * resolution / 0.25))` cells, scaling with resolution. At 0.25mm this gives 1.25mm corridors (enough for 2 adjacent traces).

Also: carve escape corridors in **all 4 directions** from each pad, not just the nearest edge. This gives the A* more egress options.

#### 2D. Increase RRR Aggressiveness

**File:** `conflict.py`

Changes:
1. Increase max victims per rip from 2 to 4: `candidates[:4]` in `_find_victims`
2. Widen victim search bbox from ±5mm to ±10mm
3. Raise default `rrr_timeout_s` from 30 to 60
4. Raise default `rip_stagnation_limit` from 4 to 6

These let RRR clear more congestion per iteration and run longer before giving up.

---

### Phase 3: Scoring & Search Strategy (optimizer improvements)

#### 3A. Decouple Shorts Penalty from Routing Score

**File:** `autoexperiment.py`, `_apply_shorts_penalty` function (line 622)

Current: `score.total *= 1.0 / (1 + log10(1 + shorts))` — this is a multiplicative kill. 31 shorts → ÷2.5.

Problem: The optimizer can't tell if a layout routes 20/26 nets with 30 shorts vs 10/26 nets with 15 shorts. The shorts penalty overwhelms the routing signal.

Fix: Use an additive penalty scaled to the score range:
```python
def _apply_shorts_penalty(score: ExperimentScore, shorts: int) -> None:
    if shorts > 0:
        # Deduct up to 15 points for shorts (out of ~100 max score)
        penalty = min(15.0, shorts * 0.5)
        score.total = max(0.0, score.total - penalty)
```

This preserves the ranking signal from routing completion while still penalizing shorts. A layout routing 20/26 nets with 20 shorts (score ~50-10=40) always beats one routing 10/26 nets with 0 shorts (score ~35).

#### 3B. Add Exploration Mode to Batch Generation

**File:** `autoexperiment.py`, batch generation section (line ~920)

Currently the batch fills with MINOR or MAJOR (one mode per batch). The `batch_seeds > 1` explore logic exists but only gets 1 explore slot.

Fix: Reserve 20% of each batch for pure exploration (random config from full range + random seed), regardless of stagnation state. This ensures diversity even when the optimizer is exploiting.

```python
# After generating the first candidate (exploit/minor/major):
n_explore = max(1, batch_size // 5)
for _ in range(n_explore):
    explore_cfg = mutate_config_major(dict(DEFAULT_CONFIG), rng, param_ranges)
    explore_seed = rng.randint(0, 2**31)
    batch.append(("explore", explore_cfg, explore_seed, ...))
```

#### 3C. Track Per-Net Failure Rates in JSONL Log

**File:** `autoexperiment.py`, JSONL logging section

Currently logs `failed_net_names` per round but doesn't aggregate. Add a running failure counter and log it:

```python
# After processing each round result:
for net_name in score.failed_net_names:
    net_fail_counts[net_name] = net_fail_counts.get(net_name, 0) + 1

# Log in JSONL entry:
"net_failure_rates": {name: count/round_num for name, count in net_fail_counts.items()}
```

This enables post-hoc analysis and could feed into Option B of 2B (automatic priority boosting).

---

### Phase 4: Architecture (larger refactors for future consideration)

#### 4A. Negotiated Congestion Routing

Replace the single-pass "route in order, mark HARD_BLOCK" with iterative negotiated congestion:
1. Route all nets with soft costs (no HARD_BLOCK)
2. Where nets overlap, increase cost in congested cells
3. Rip and re-route all nets with updated costs
4. Repeat 3-5 iterations until congestion resolves

This is how real EDA routers (PathFinder/FPGA) work. It distributes routing pressure more evenly instead of starving late nets.

**Complexity:** High. Requires refactoring RoutingSolver to support soft costs and iterative passes. Estimated 300-500 lines of new code.

#### 4B. Two-Pass Routing with Width Relaxation

First pass: route all nets at minimum width (0.127mm signal, no clearance boost). This maximizes successful routing.
Second pass: selectively widen traces for power nets where space allows.

Currently the router tries strict width → relaxed width per edge, but this is per-edge, not global. A global two-pass approach would route more nets first, then improve quality.

#### 4C. Adaptive Grid Resolution

Instead of uniform grid resolution, use variable resolution:
- Fine grid (0.125mm) in congested IC areas
- Coarse grid (0.5mm) in open areas

This gives the routing detail where it matters without the 4× memory/compute cost everywhere.

**Complexity:** Very high. Requires hierarchical grid data structure. Future work.

---

## Implementation Order

**Immediate (do now):**
1. 1A — Fix program.md ranges (5 min)
2. 3A — Fix shorts penalty to additive (5 min)
3. 2A — Change grid resolution default to 0.25mm (1 line)
4. 2D — Increase RRR aggressiveness (4 small changes)

**After validation run:**
5. 1B — Make grid_resolution tunable in mutations
6. 2B Option A — Manual net priority for failing nets
7. 2C — Wider escape corridors
8. 3B — Add exploration slots to batches

**Future (deferred):**
9. 3C — Per-net failure tracking
10. 4A — Negotiated congestion routing
11. 4B — Two-pass width relaxation
12. 4C — Adaptive grid resolution

---

## Validation

After implementing steps 1–4 (Immediate), run:
```bash
python3 .claude/skills/kicad-helper/scripts/autoexperiment.py LLUPS.kicad_pcb \
  --rounds 20 --program .claude/skills/kicad-helper/scripts/program.md
```

**Success criteria:**
- [ ] Routed nets > 16/26 (was 13/26) — finer grid should unlock 3+ more nets
- [ ] Score > 30 (was 21.83) — additive shorts penalty preserves routing signal
- [ ] Shorts < 25 (was 31) — clearance_mm floor at 0.2 eliminates sub-DRC configs
- [ ] At least 1 of the 3 never-routed nets (`/CHG_N`, `/NTC_SENSE`, `Net-(F1-Pad2)`) routes in ≥1 round
- [ ] No regression in round duration (target < 300s/round)

After implementing steps 5–8, run 40 rounds and verify:
- [ ] Routed nets > 20/26
- [ ] Score > 45
- [ ] Mode diversity: MINOR, MAJOR, and EXPLORE all appear

---

## Files Modified (Summary)

| File | Phase | Change |
|------|-------|--------|
| `program.md` | 1A | Fix param ranges (clearance floor, remove existing_trace_cost, add grid_resolution) |
| `autoexperiment.py` | 1B, 3A, 3B, 3C | Tunable grid_resolution, additive shorts penalty, explore slots, failure tracking |
| `config.py` | 1C, 2A | Add missing defaults, change grid_resolution to 0.25 |
| `router.py` | 2B | Net priority support in `_prioritize_nets` |
| `grid_builder.py` | 2C | Wider + multi-direction escape corridors |
| `conflict.py` | 2D | More victims, wider search, longer timeout |
