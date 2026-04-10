# Implementation Plan: FreeRouting Integration + Autoexperiment Simplification

> **For**: Implementation agent
> **Date**: 2026-04-10
> **Board**: LLUPS (Lithium Li-ion Universal Power Supply)
> **Goal**: Replace custom A*/RRR router with FreeRouting, simplify placement code, speed up autoexperiment loop

---

## Context & Motivation

The current autoexperiment system uses a custom Python A* grid router + rip-up/reroute (RRR) conflict resolver. This has two fatal problems:

1. **Speed**: At 0.25mm grid resolution (needed for honest DRC), each round takes 14-22 minutes. At 0.5mm grid it's 2min but creates hidden shorts
2. **Quality**: The router produces 32-96 DRC shorts per layout. Via grid quantization causes collisions. The RRR has a PathResult bug that crashes workers (conflict.py treats `find_path()` return as raw list instead of PathResult namedtuple)

**FreeRouting** is a mature Java-based PCB autorouter (1.7k GitHub stars, active development) that:
- Uses topological routing (no grid resolution tradeoff)
- Has native rip-up/reroute built in
- Produces DRC-clean results
- Has a headless CLI: `java -jar freerouting.jar -de board.dsn -do board.ses`
- Works with KiCad via Specctra DSN/SES file exchange
- Typical routing time: 5-30 seconds for a 26-net board

This replaces ~1450 lines of Python code (router.py + conflict.py + grid_builder.py) with ~150 lines of integration glue.

---

## Prerequisites

1. **Java JRE 21+** must be installed (`sudo apt install default-jre` on Ubuntu/Debian)
2. **FreeRouting JAR** — download v2.1.0 from https://github.com/freerouting/freerouting/releases
   - Place at a known path, e.g., `~/.local/lib/freerouting-2.1.0.jar`
   - Verify: `java -jar freerouting-2.1.0.jar -help`
3. **kicad-cli** must support DSN export (KiCad 9 on this system already has it)

---

## Phase 1: FreeRouting Integration (Critical Path)

### Step 1.1: Create `freerouting_runner.py`

**File**: `.claude/skills/kicad-helper/scripts/autoplacer/freerouting_runner.py` (NEW)

This module handles the DSN→FreeRouting→SES pipeline. It must:

1. **Export DSN** from a placed KiCad PCB:
   ```python
   import pcbnew
   
   def export_dsn(kicad_pcb_path: str, dsn_path: str) -> None:
       """Export Specctra DSN from a KiCad PCB file."""
       board = pcbnew.LoadBoard(kicad_pcb_path)
       pcbnew.ExportSpecctraDSN(board, dsn_path)
   ```
   - If `ExportSpecctraDSN` is not available in KiCad 9's Python API, fall back to kicad-cli:
     ```
     kicad-cli pcb export specctra -o board.dsn board.kicad_pcb
     ```

2. **Run FreeRouting** headless:
   ```python
   import subprocess
   
   def run_freerouting(dsn_path: str, ses_path: str, 
                       jar_path: str, timeout_s: int = 60,
                       max_passes: int = 20,
                       ignore_net_classes: list[str] | None = None) -> dict:
       """Run FreeRouting CLI and return result metadata."""
       cmd = ["java", "-jar", jar_path, "-de", dsn_path, "-do", ses_path,
              "-mp", str(max_passes)]
       if ignore_net_classes:
           cmd.extend(["-inc", ",".join(ignore_net_classes)])
       
       result = subprocess.run(cmd, capture_output=True, text=True, 
                               timeout=timeout_s)
       # Parse stdout for routing stats (completion, via count, etc.)
       return parse_freerouting_output(result.stdout, result.returncode)
   ```
   - **Important**: Use `-inc GND,VCC` to exclude power nets (they should be copper fills/zones, not traces)
   - `-mp 20` = max 20 routing passes (tune this; start with 20)

3. **Import SES** back into KiCad PCB:
   ```python
   def import_ses(kicad_pcb_path: str, ses_path: str, output_path: str) -> None:
       """Import Specctra SES session file into KiCad PCB."""
       board = pcbnew.LoadBoard(kicad_pcb_path)
       pcbnew.ImportSpecctraSES(board, ses_path)
       board.Save(output_path)
   ```
   - If `ImportSpecctraSES` is not available, fall back to kicad-cli:
     ```
     kicad-cli pcb import specctra -i board.ses board.kicad_pcb
     ```

4. **Convenience wrapper**:
   ```python
   def route_with_freerouting(kicad_pcb_path: str, output_path: str,
                               jar_path: str, config: dict) -> dict:
       """Full DSN→FreeRouting→SES pipeline. Returns routing stats."""
       with tempfile.TemporaryDirectory() as tmpdir:
           dsn_path = os.path.join(tmpdir, "board.dsn")
           ses_path = os.path.join(tmpdir, "board.ses")
           
           export_dsn(kicad_pcb_path, dsn_path)
           stats = run_freerouting(dsn_path, ses_path, jar_path,
                                    timeout_s=config.get("freerouting_timeout_s", 60),
                                    max_passes=config.get("freerouting_max_passes", 20),
                                    ignore_net_classes=config.get("freerouting_ignore_nets"))
           import_ses(kicad_pcb_path, ses_path, output_path)
           
       return stats
   ```

**Testing**: Run this standalone on `LLUPS.kicad_pcb` BEFORE integrating into the pipeline. Verify:
- DSN exports without error
- FreeRouting routes ≥21/26 nets (current best)  
- SES imports cleanly
- `kicad-cli pcb drc` shows 0 shorts on the result

### Step 1.2: Modify `pipeline.py` — Replace RoutingEngine

**File**: `.claude/skills/kicad-helper/scripts/autoplacer/pipeline.py`

Replace the `RoutingEngine` class body. The current code (lines 65-107) does:
```python
solver = RoutingSolver(state, cfg)
traces, vias, failed, per_net_results = solver.solve()
# ... RRR ...
rrr = RipUpRerouter(state, cfg)
traces, vias, failed, rrr_summary = rrr.solve(traces, vias, failed)
# ... adapter.apply_routing() ...
```

Replace with:
```python
from .freerouting_runner import route_with_freerouting

class RoutingEngine:
    def run(self, pcb_path: str, output_path: str = None,
            config: dict = None, rip_up: bool = True) -> dict:
        cfg = {**DEFAULT_CONFIG, **(config or {})}
        out = output_path or pcb_path
        
        t0 = time.monotonic()
        jar_path = cfg.get("freerouting_jar", 
                           os.path.expanduser("~/.local/lib/freerouting-2.1.0.jar"))
        stats = route_with_freerouting(pcb_path, out, jar_path, cfg)
        routing_ms = (time.monotonic() - t0) * 1000.0
        
        # Count routed/failed nets from the output board
        adapter = KiCadAdapter(out)
        state = adapter.load()
        # ... count nets by checking which have traces ...
        
        return {
            "traces": stats.get("trace_count", 0),
            "vias": stats.get("via_count", 0),
            "failed_nets": stats.get("failed_nets", []),
            "total_nets": stats.get("total_nets", 0),
            "total_length_mm": stats.get("total_length_mm", 0),
            "routing_ms": routing_ms,
            "rrr_ms": 0.0,  # FreeRouting handles RRR internally
            "rrr_summary": None,
            "per_net_results": [],
        }
```

**Key changes**:
- Remove imports of `RoutingSolver`, `RipUpRerouter` 
- Remove all grid/A*/RRR logic
- The `FullPipeline` class should work mostly unchanged since it just calls `RoutingEngine.run()` and reads the returned dict

### Step 1.3: Update `FullPipeline` in `pipeline.py`

The `FullPipeline.run()` method (lines 120-185) builds an `ExperimentScore` from routing results. Update it to handle the new return format:

- `per_net_results` will be empty (FreeRouting doesn't expose per-net A* stats). Set `total_a_star_expansions = 0`
- `rrr_summary` will be `None`
- `failed_net_names` comes from FreeRouting's output (parse from stdout or by comparing routed vs expected nets)

### Step 1.4: Add FreeRouting config keys to `config.py`

**File**: `.claude/skills/kicad-helper/scripts/autoplacer/config.py`

Add these new keys to `DEFAULT_CONFIG`:
```python
# FreeRouting
"freerouting_jar": "~/.local/lib/freerouting-2.1.0.jar",
"freerouting_timeout_s": 60,
"freerouting_max_passes": 20,
"freerouting_ignore_nets": ["GND", "VCC"],  # Route as zones, not traces
```

**Remove** these keys (no longer used):
- `grid_resolution_mm` (FreeRouting has no grid concept)
- `clearance_mm` (FreeRouting reads clearance from DSN/board rules)
- `existing_trace_cost` (internal A* cost, not applicable)
- `max_search` (A* expansion limit)
- `max_rips_per_net`, `rip_stagnation_limit`, `rrr_timeout_s`, `max_rrr_iterations` (RRR params)
- `mst_retry_limit` (MST routing param)

### Step 1.5: Update mutation functions in `autoexperiment.py`

**File**: `.claude/skills/kicad-helper/scripts/autoexperiment.py`

In `mutate_config_minor()` (line ~233), remove router-related parameters from the `tunable` dict:
```python
# REMOVE these entries:
"clearance_mm": ...
"existing_trace_cost": ...
"max_rips_per_net": ...  
"grid_resolution_mm": ...
```

The remaining tunable placement parameters are:
```python
tunable = {
    "force_attract_k": (0.005, 0.15, 0.15),
    "force_repel_k":   (100.0, 500.0, 0.15),
    "cooling_factor":  (0.90, 0.995, 0.05),
    "edge_margin_mm":  (4.0, 10.0, 0.1),
    "placement_clearance_mm": (1.0, 3.0, 0.15),
}
```

Similarly update `mutate_config_major()` (line ~275).

### Step 1.6: Update ExperimentScore and scoring

**File**: `.claude/skills/kicad-helper/scripts/autoplacer/brain/types.py`

The `ExperimentScore` dataclass and its `compute()` method need updates:
- Remove `grid_occupancy_pct` field (grid concept gone)
- Remove `total_a_star_expansions` field or keep it at 0 for compatibility
- **FIX THE BUG**: `compute(weights)` currently ignores the `weights` parameter. Make it use the passed weights dict

### Step 1.7: Delete dead router code

**Delete these files entirely**:
- `.claude/skills/kicad-helper/scripts/autoplacer/brain/router.py` (~710 lines)
- `.claude/skills/kicad-helper/scripts/autoplacer/brain/conflict.py` (~320 lines)  
- `.claude/skills/kicad-helper/scripts/autoplacer/brain/grid_builder.py` (~420 lines)
- `.claude/skills/kicad-helper/scripts/autoplacer/brain/test_router_grid_behavior.py` (test for deleted code)

**Update imports** — remove dead imports in:
- `pipeline.py` — remove `from .brain.router import RoutingSolver` and `from .brain.conflict import RipUpRerouter`
- `autoplacer/brain/__init__.py` — remove any router/conflict/grid exports
- `autoroute.py` — if it imports router directly, update or delete

### Step 1.8: Update `_write_round_detail()` in `autoexperiment.py`

The round detail JSON (line ~650) logs A*-specific fields. Update:
- `total_a_star_expansions` → set to 0 or remove
- `grid_occupancy_pct` → remove
- `per_net` → will be empty list (FreeRouting doesn't expose per-net stats)
- `rrr` → will be null

---

## Phase 2: Simplify Placement Code (Medium Priority)

*Depends on: Phase 1 complete and validated*

### Step 2.1: Fix `ExperimentScore.compute(weights)` bug

**File**: `.claude/skills/kicad-helper/scripts/autoplacer/brain/types.py`

The `compute()` method ignores its `weights` parameter and uses hardcoded values. Fix it to:
```python
def compute(self, weights: dict | None = None):
    w = weights or {
        "placement": 0.15,
        "route_completion": 0.65,
        "via_penalty": 0.10,
        "containment": 0.10,
    }
    # ... use w["placement"], w["route_completion"], etc.
```

### Step 2.2: Fix `board_containment` zeroing all scores

The score formula multiplies by `board_containment / 100`, which destroys the score when containment < 100%. Change to additive:
```python
# BEFORE (broken):
total = raw * (board_containment / 100)

# AFTER (additive):
total = (w["placement"] * placement_total +
         w["route_completion"] * route_completion_pct +
         w["via_penalty"] * via_score +
         w["containment"] * board_containment)
```

### Step 2.3: Deduplicate force simulation (optional)

The force simulation code in `placement.py` is duplicated (~180 LOC × 2). Extract to a single function:
```python
def force_step(positions: dict, connectivity: dict, config: dict) -> dict:
    """One iteration of force-directed layout. Returns updated positions."""
```

Call this from both the cluster-level and board-level placement loops.

---

## Phase 3: Long-Term Learning (Optional, After Phase 1+2 Validated)

With FreeRouting making each round ~5-30s, the evolutionary search has 30-200x more budget. Before adding Optuna, try these simpler improvements:

### Step 3.1: Persistent Config Archive

Save top-10 configs from every run to `.experiments/elite_configs.json`. Seed 30% of each new run from this archive. This gives cross-run learning with zero dependencies.

### Step 3.2: Optuna Integration (if needed)

If the evolutionary loop still plateaus after 500+ rounds with FreeRouting:
- `pip install optuna`
- Replace `mutate_config_minor/major` with Optuna's TPE sampler
- Use `storage='sqlite:///experiments.db'` for persistence
- Use `optuna.importance.get_param_importances()` to identify which placement params matter

This is ~200 lines of code change. Only worthwhile if placement optimization is still the bottleneck after FreeRouting handles routing.

---

## File Change Summary

| File | Action | Lines Changed |
|------|--------|--------------|
| `autoplacer/freerouting_runner.py` | **CREATE** | ~150 new |
| `autoplacer/pipeline.py` | **MODIFY** | Replace RoutingEngine (~50 lines changed) |
| `autoplacer/config.py` | **MODIFY** | Add 4 new keys, remove 7 dead keys |
| `autoplacer/brain/types.py` | **MODIFY** | Fix compute() bug, remove grid fields |
| `autoexperiment.py` | **MODIFY** | Remove router params from mutation (~30 lines) |
| `autoplacer/brain/router.py` | **DELETE** | -710 lines |
| `autoplacer/brain/conflict.py` | **DELETE** | -320 lines |
| `autoplacer/brain/grid_builder.py` | **DELETE** | -420 lines |
| `autoplacer/brain/test_router_grid_behavior.py` | **DELETE** | ~100 lines |
| `autoplacer/brain/__init__.py` | **MODIFY** | Remove dead exports |

All file paths are relative to `.claude/skills/kicad-helper/scripts/`.

**Net change**: ~-1400 lines (delete ~1550, add ~150)

---

## Verification Checklist

Run these checks after each phase:

### After Phase 1 (FreeRouting Integration):
- [ ] `java -jar freerouting.jar -help` works (Java JRE installed)
- [ ] Standalone test: `export_dsn(LLUPS.kicad_pcb)` → `run_freerouting()` → `import_ses()` succeeds
- [ ] FreeRouting routes ≥21/26 nets (match or beat current best)
- [ ] `kicad-cli pcb drc` on FreeRouting result shows 0 shorts (vs current 32-96)
- [ ] Single round time < 60 seconds (vs current 14-22 minutes)
- [ ] `python3 autoexperiment.py LLUPS.kicad_pcb --rounds 5` completes without error
- [ ] Experiment JSONL logs contain valid data (no NaN, no -1.0 crash scores)
- [ ] No import errors from deleted router/conflict/grid modules

### After Phase 2 (Scoring Fixes):
- [ ] `ExperimentScore.compute({"placement": 0.15, ...})` uses passed weights
- [ ] Board containment < 100% no longer zeroes the score
- [ ] Scores are in a meaningful range (30-90 typical, not all 0.0 or all -1.0)

### After Phase 3 (Long-Term Learning):
- [ ] Elite configs saved to `.experiments/elite_configs.json` after each run
- [ ] New runs seed from elite archive
- [ ] 100-round run shows monotonic improvement in best score

---

## Known Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| `pcbnew.ExportSpecctraDSN()` not available in KiCad 9 Python API | Medium | Fall back to `kicad-cli pcb export specctra` subprocess |
| `pcbnew.ImportSpecctraSES()` not available | Medium | Fall back to `kicad-cli pcb import specctra` subprocess |
| FreeRouting can't route some nets due to board constraints | Low | Same as current situation; count as failures in scoring. FreeRouting typically routes more than basic A* |
| FreeRouting produces different trace widths than config specifies | Low | DSN file includes trace width from board design rules; FreeRouting respects them |
| Java JRE not installed on target machine | Low | Document as prerequisite; `sudo apt install default-jre` |
| FreeRouting timeout on complex layouts | Low | Default 60s timeout; configurable. For 26 nets on 2-layer board, 5-30s is typical |

---

## Architecture After Implementation

```
autoexperiment.py
  └─ autoplacer/
       ├─ pipeline.py          — PlacementEngine, RoutingEngine (FreeRouting), FullPipeline
       ├─ freerouting_runner.py — NEW: DSN export, FreeRouting CLI, SES import
       ├─ config.py            — DEFAULT_CONFIG (placement params only)
       ├─ hardware/
       │   └─ adapter.py       — KiCad pcbnew read/write (unchanged)
       └─ brain/
            ├─ types.py        — BoardState, PlacementScore, ExperimentScore (fixed)
            ├─ placement.py    — Force-directed placement (unchanged)
            └─ graph.py        — Connectivity graph (unchanged)
            # router.py      — DELETED
            # conflict.py    — DELETED
            # grid_builder.py — DELETED
```
