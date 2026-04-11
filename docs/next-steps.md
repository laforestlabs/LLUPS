# LLUPS — Suggested Next Steps

> Updated: 2026-04-11
> Current state: FreeRouting pipeline stable, 150-round experiment completed, old Python router fully removed

---

## Where Things Stand

- **FreeRouting** is the sole router. Routing time is ~15-30 sec/round.
- **Subprocess isolation** for pcbnew calls avoids the SwigPyObject stale-object bug.
- **Blocking dialogs eliminated** via `dialog_confirmation_timeout: 0` in `freerouting.json`.
- **Scoring fixed**: `ExperimentScore.compute()` uses passed weights; `board_containment` no longer zeroes all scores.
- 150-round experiment completed with parallel workers.

---

## High Priority

### 1. Investigate consistently failing nets

Check which nets still fail after 150 rounds. Consider:
- Adding them to `net_priority` in `program.md` to influence placement grouping
- Checking if they connect components across IC groups that get placed far apart
- Running `kicad-cli pcb drc` on the best board to diagnose connectivity vs clearance issues

### 2. Tune `freerouting_max_passes`

FreeRouting v2.1.0 ignores the `-mp` CLI flag — it runs until its internal score stagnates. The `timeout_s: 120` acts as the real limit. For this 26-net board, FreeRouting typically converges in 15-30 seconds. Options:
- Monitor `routing_seconds` in experiment logs
- Reduce `freerouting_timeout_s` to 60 if routing consistently finishes in <30s
- Or switch to a newer FreeRouting release that may respect `-mp`

### 3. Power net routing strategy

Consider excluding power nets (`GND`, `VBAT`, `VBUS`) via `-inc` flag so they're routed as copper fills/zones instead of traces. This could:
- Free up routing space for signal traces
- Improve current-carrying capacity on power paths
- Reduce DRC violations from narrow power traces

---

## Medium Priority

### 4. Deduplicate force simulation in placement.py

The force-directed placement code has ~180 lines duplicated between cluster-level and board-level loops. Extract to a single `force_step()` function.

### 5. Elite config persistence

Save the top-10 configs from each run to `.experiments/elite_configs.json`. Seed 30% of new runs from this archive for cross-run learning.

### 6. Optuna integration

If the evolutionary search plateaus after 500+ rounds, replace `mutate_config_minor/major` with Optuna's TPE sampler for more intelligent hyperparameter exploration.

---

## Low Priority / Future

### 7. USB-PD header for future revision

The spec mentions routing CC1/CC2 to pads or a header for a future PD controller. Verify the current layout leaves space and traces for this.

### 8. Thermal analysis

Components U2 and U4 are flagged as thermal-sensitive. After placement stabilizes, verify thermal pad placement and copper pour connectivity.

### 9. Generate fabrication outputs

Once the board reaches a satisfactory routing score (target: 26/26 nets, 0 DRC shorts):
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
| `routing_ms` includes pcbnew subprocess overhead | `pipeline.py` | Timing includes DSN export + SES import subprocesses, not just FreeRouting |
