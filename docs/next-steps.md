# LLUPS — Suggested Next Steps

> Generated: 2026-04-10
> Current state: FreeRouting integration complete, custom A*/RRR router deleted, autoexperiment loop functional

---

## Where Things Stand

- **FreeRouting** replaces the custom Python router. Routing time dropped from 14-22 min/round to ~15-30 sec/round.
- **Subprocess isolation** for pcbnew calls avoids the SwigPyObject stale-object bug that plagued repeated `LoadBoard()` calls.
- **Blocking dialogs eliminated** via `dialog_confirmation_timeout: 0` in `freerouting.json`.
- **Scoring fixed**: `ExperimentScore.compute()` now uses passed weights; `board_containment` no longer zeroes all scores.
- Last 20-round experiment peaked at **score 61.0** (21/26 nets routed, placement=78.9, 51 DRC shorts, 306 DRC total). Earlier standalone test hit **score 96.6** (26/26 nets, 0 DRC shorts) — the difference is placement quality.

---

## High Priority

### 1. Run a long autoexperiment with the new FreeRouting pipeline

The existing 20 rounds in `experiments.jsonl` were from the old A*/RRR router. A fresh 50-100 round run with FreeRouting will establish the new performance baseline and let the evolutionary search explore placement space with fast feedback.

```bash
python3 .claude/skills/kicad-helper/scripts/autoexperiment.py \
    LLUPS.kicad_pcb --rounds 100 \
    --program .claude/skills/kicad-helper/scripts/program.md
```

### 2. Investigate the 5 consistently failing nets

The last experiment logged these failed nets:
- `/VBAT`, `/CHG_N`, `Net-(U2-TMR)`, `/NTC_SENSE`, `Net-(U4-FB)`

These may be placement-dependent (components too far apart or blocked by other parts). Consider:
- Adding them to `net_priority` in `program.md` to influence placement grouping
- Checking if they connect components across IC groups that get placed far apart
- Running `kicad-cli pcb drc` on the best board to see if failures are connectivity or clearance issues

### 3. Tune `freerouting_max_passes`

FreeRouting v2.1.0 appears to ignore the `-mp` CLI flag and the `max_passes` JSON config — it runs until its internal score stagnates. The current `timeout_s: 120` acts as the real limit. For this 26-net board, FreeRouting typically converges in 15-30 seconds, so the timeout rarely fires. If you want tighter control:
- Monitor `routing_seconds` in experiment logs
- Reduce `freerouting_timeout_s` to 60 if routing consistently finishes in <30s
- Or switch to a newer FreeRouting release that may respect `-mp`

### 4. Power net routing strategy

Currently all nets go through FreeRouting. The plan doc suggests excluding power nets (`GND`, `VBAT`, `VBUS`) via `-inc` flag so they're routed as copper fills/zones instead of traces. This could:
- Free up routing space for signal traces
- Improve current-carrying capacity on power paths
- Reduce DRC violations from narrow power traces

Implementation: add `"freerouting_ignore_nets": ["GND", "VBAT", "VBUS"]` to config and pass `-inc` to the FreeRouting CLI.

---

## Medium Priority

### 5. DRC integration into scoring loop

The experiment logs show 51 DRC shorts and 306 total DRC errors. Currently DRC is run via `kicad-cli pcb drc` but its results may not be fully weighted in the score. Consider:
- Running DRC after every round (or every Nth round) and incorporating violation counts into `ExperimentScore`
- Adding a `drc_penalty` weight to the scoring formula
- Using DRC-clean rounds as a hard filter for "kept" results

### 6. Deduplicate force simulation in placement.py

The force-directed placement code has ~180 lines duplicated between cluster-level and board-level loops. Extract to a single `force_step()` function. This makes it easier to tune the physics and reduces the surface area for bugs.

### 7. Elite config persistence (Phase 3 from the plan)

Save the top-10 configs from each run to `.experiments/elite_configs.json`. Seed 30% of new runs from this archive. This provides cross-run learning — new experiments start from previously successful placement parameters rather than random mutations.

### 8. Autoexperiment parallelism

The current loop is sequential (one round at a time). Since FreeRouting is fast and each round is independent, running 2-4 candidates in parallel would multiply throughput. Worker processes with separate temp directories would avoid file conflicts.

---

## Low Priority / Future

### 9. Optuna integration

If the evolutionary search plateaus after 500+ rounds, replace `mutate_config_minor/major` with Optuna's TPE sampler for more intelligent hyperparameter exploration. Only worthwhile if placement optimization remains the bottleneck.

### 10. USB-PD header for future revision

The spec mentions routing CC1/CC2 to pads or a header in addition to the pull-down resistors, so a PD controller can be added later. Verify the current layout leaves space and traces for this.

### 11. Thermal analysis

Components U2 and U4 are flagged as thermal-sensitive (`thermal_refs` in config). After placement stabilizes, verify thermal pad placement and copper pour connectivity around these ICs.

### 12. Generate fabrication outputs

Once the board reaches a satisfactory routing score (target: 26/26 nets, 0 DRC shorts), generate Gerber files and a BOM for prototype ordering:
```bash
kicad-cli pcb export gerbers -o gerber/ LLUPS.kicad_pcb
kicad-cli pcb export drill -o gerber/ LLUPS.kicad_pcb
```

---

## Known Technical Debt

| Item | Location | Notes |
|------|----------|-------|
| FreeRouting ignores `max_passes` | `freerouting_runner.py` | v2.1.0 bug; relies on natural convergence or timeout |
| pcbnew SWIG memory leak warnings | `_run_pcbnew_script()` | Harmless stderr noise from `PCB_TRACK *` / `PCB_VIA *` destructors |
| Old experiment data in `experiments.jsonl` | `.experiments/` | First 20 rounds are from the dead A*/RRR router; consider archiving or starting fresh |
| `routing_ms` includes pcbnew subprocess overhead | `pipeline.py` | Timing includes DSN export + SES import subprocesses, not just FreeRouting |
