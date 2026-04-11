# LLUPS Autoplacer Architecture

This document describes how the autoplacer stack operates.

## High-Level System Map

```mermaid
flowchart TD
  autoplaceCli[autoplace.py] --> placementEngine[PlacementEngine.run]
  autorouteCli[autoroute.py] --> routingEngine[RoutingEngine.run]
  autopipelineCli[autopipeline.py] --> fullPipeline[FullPipeline.run]
  autoexperimentCli[autoexperiment.py] --> fullPipeline

  fullPipeline --> placementEngine
  fullPipeline --> routingEngine
  fullPipeline --> drcAnalysis[kicad-cli DRC]

  placementEngine --> adapterLoad[KiCadAdapter.load]
  adapterLoad --> boardState[BoardState]
  boardState --> placementSolver[PlacementSolver.solve]
  placementSolver --> placementScorer[PlacementScorer.score]
  placementSolver --> applyPlacement[KiCadAdapter.apply_placement]

  routingEngine --> freerouting[FreeRouting via DSN/SES]
  freerouting --> countTracks[count_board_tracks]

  placementScorer --> experimentScore[ExperimentScore.compute]
  countTracks --> experimentScore
  drcAnalysis --> experimentScore

  applyPlacement --> pcbArtifact[PCB file output]
  freerouting --> pcbArtifact
  experimentScore --> autoexperimentLoop[Experiment keep/discard loop]
  autoexperimentLoop --> artifacts[JSONL + report + GIF + status files]
```

## Layer Responsibilities

- `hardware/adapter.py` is the I/O boundary with KiCad (`pcbnew`): loads board state, applies placement.
- `brain/` modules are pure-Python algorithmic logic:
  - `placement.py`: footprint placement and placement scoring
  - `graph.py`: netlist graph analysis for placement grouping
  - `types.py`: shared dataclasses and scoring objects
- `freerouting_runner.py`: DSN export → FreeRouting CLI → SES import → track counting.
- `pipeline.py` composes placement + routing + DRC and emits `ExperimentScore`.
- `autoexperiment.py` runs iterative optimization rounds, keeps best board, writes artifacts.

## Data Model Path

```mermaid
flowchart LR
  kicadBoard[.kicad_pcb] --> adapterLoad[KiCadAdapter.load]
  adapterLoad --> boardState[BoardState dataclasses]
  boardState --> placementPhase[Placement phase]
  placementPhase --> placementMetrics[PlacementScore]
  boardState --> routingPhase[FreeRouting]
  routingPhase --> routingMetrics[traces, vias, length, unrouted]
  placementMetrics --> expScore[ExperimentScore.compute]
  routingMetrics --> expScore
  expScore --> bestDecision[Best candidate decision]
  bestDecision --> bestBoard[best.kicad_pcb]
```
