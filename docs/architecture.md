# LLUPS Autoplacer Architecture

This document describes how the current autoplacer stack operates in code.

## High-Level System Map

```mermaid
flowchart TD
  autoplaceCli[autoplace.py] --> placementEngine[PlacementEngine.run]
  autorouteCli[autoroute.py] --> routingEngine[RoutingEngine.run]
  autopipelineCli[autopipeline.py] --> fullPipeline[FullPipeline.run]
  autoexperimentCli[autoexperiment.py] --> fullPipeline

  fullPipeline --> placementEngine
  fullPipeline --> routingEngine

  placementEngine --> adapterLoadA[KiCadAdapter.load]
  routingEngine --> adapterLoadB[KiCadAdapter.load]

  adapterLoadA --> boardStateA[BoardState]
  adapterLoadB --> boardStateB[BoardState]

  boardStateA --> placementSolver[PlacementSolver.solve]
  placementSolver --> placementScorer[PlacementScorer.score]
  placementSolver --> applyPlacement[KiCadAdapter.apply_placement]

  boardStateB --> routingSolver[RoutingSolver.solve]
  routingSolver --> rrrSolver[RipUpRerouter.solve]
  routingSolver --> applyRouting[KiCadAdapter.apply_routing]
  rrrSolver --> applyRouting

  placementScorer --> experimentScore[ExperimentScore.compute]
  routingSolver --> experimentScore
  rrrSolver --> experimentScore

  applyPlacement --> pcbArtifact[PCB file output]
  applyRouting --> pcbArtifact
  experimentScore --> autoexperimentLoop[Experiment keep/discard loop]
  autoexperimentLoop --> dashboardArtifacts[JSONL + dashboard PNG + GIF + status files]
```



## Layer Responsibilities

- `hardware/adapter.py` is the I/O boundary with KiCad (`pcbnew`): load board state, apply placement, apply routing.
- `brain/` modules are pure-Python algorithmic logic:
  - `placement.py`: footprint placement and placement scoring
  - `router.py`: A* routing, net prioritization, MST-based per-net routing
  - `conflict.py`: rip-up/reroute when initial routing fails
  - `types.py`: shared dataclasses and scoring objects
- `pipeline.py` composes placement + routing and emits `ExperimentScore`.
- `autoexperiment.py` runs iterative optimization rounds, applies shorts penalty, keeps best board, and writes dashboard artifacts.

## Data Model Path

```mermaid
flowchart LR
  kicadBoard[.kicad_pcb] --> adapterLoad[KiCadAdapter.load]
  adapterLoad --> boardState[BoardState dataclasses]
  boardState --> placementPhase[Placement phase]
  boardState --> routingPhase[Routing phase]
  placementPhase --> placementMetrics[PlacementScore fields]
  routingPhase --> routingMetrics[routed_nets failed_nets traces vias]
  placementMetrics --> expScore[ExperimentScore.compute]
  routingMetrics --> expScore
  expScore --> bestDecision[Best candidate decision]
  bestDecision --> bestBoard[best.kicad_pcb]
```



