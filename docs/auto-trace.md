# Auto-Trace: FreeRouting Integration

This page describes how automatic routing works in the LLUPS pipeline.

## Routing Engine

Routing uses [FreeRouting](https://github.com/freerouting/freerouting), a Java-based
topological PCB autorouter, via DSN/SES file exchange.

**Prerequisites:**
- Java JRE 21+ (`java -version`)
- FreeRouting JAR at `~/.local/lib/freerouting-1.9.0.jar` (v2.1.0 has a regression where max_passes is ignored)
- `kicad-cli` (ships with KiCad 9)

## Routing Pipeline

```mermaid
flowchart TD
  routingEngine[RoutingEngine.run] --> clearTraces[clear_traces - preserve thermal vias]
  clearTraces --> exportDSN[export_dsn - pcbnew to Specctra DSN]
  exportDSN --> freerouting[run_freerouting - java -jar freerouting.jar]
  freerouting --> importSES[import_ses - Specctra SES back to pcbnew]
  importSES --> countTracks[count_board_tracks - real trace/via counts]
  countTracks --> results[Return traces, vias, length, unrouted count]
```

### Key files

| File | Purpose |
|------|---------|
| `autoplacer/freerouting_runner.py` | DSN export, FreeRouting CLI, SES import, track counting |
| `autoplacer/pipeline.py` | Orchestrates placement → routing → DRC |
| `autoplacer/config.py` | Default config (timeouts, max passes, thermal refs) |

## Routing Rules

- **Thermal vias** for U2/U4 are preserved during `clear_traces()` — not re-routed.
- **GND** is skipped from routing (`skip_gnd_routing=True`) — handled as copper zones.
- FreeRouting runs single-threaded (`-mt 1`) with up to 40 passes by default.
- Timeout: 120 seconds per routing attempt.

## Auto-Trace + Experiment Loop

```mermaid
flowchart TD
  autoexperiment[autoexperiment.py round] --> mutateCfg[mutate_config]
  mutateCfg --> fullPipeline[FullPipeline.run]
  fullPipeline --> placementPhase[Placement]
  fullPipeline --> routingPhase[FreeRouting]
  routingPhase --> drc[kicad-cli DRC]
  drc --> scorePenalty[_score_round]
  scorePenalty --> keepCheck{score > best?}
  keepCheck -->|yes| copyBest[Copy best board]
  keepCheck -->|no| discard[Discard candidate]
  copyBest --> log[Append experiments.jsonl]
  discard --> log
```

## Error Handling

- If FreeRouting fails to produce a SES file, a `RuntimeError` is raised (not silently ignored).
- Worker crashes are captured with full tracebacks and printed to stdout.
- DRC errors from `kicad-cli` include the error message in the returned dict.
