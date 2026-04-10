# Auto-Trace Internals

This page describes the implemented auto-tracing behavior in:

- `autoplacer/brain/router.py`
- `autoplacer/brain/grid_builder.py`
- `autoplacer/brain/conflict.py`

## End-to-End Routing Flow

```mermaid
flowchart TD
  routingEngine[RoutingEngine.run] --> loadBoard[KiCadAdapter.load]
  loadBoard --> routeSolve[RoutingSolver.solve]
  routeSolve --> buildGrid[build_grid]
  routeSolve --> orderNets[_prioritize_nets]
  orderNets --> perNet[_route_net per net]
  perNet --> mstBuild[minimum_spanning_tree]
  mstBuild --> astarPath[AStarRouter.find_path]
  astarPath --> pathConvert[path_to_traces]
  pathConvert --> markSoft[Mark routed net as soft obstacle]
  markSoft --> moreEdges{More MST edges}
  moreEdges -->|yes| astarPath
  moreEdges -->|no| nextNet{More nets}
  nextNet -->|yes| perNet
  nextNet -->|no| failedCheck{Failed nets exist}
  failedCheck -->|yes| rrr[RipUpRerouter.solve]
  failedCheck -->|no| applyRouting[KiCadAdapter.apply_routing]
  rrr --> applyRouting
```

## Routing Rules and Constraints

- Net ordering:
  - power nets first
  - higher `priority` first
  - simpler nets (fewer pads) earlier
- GND can be skipped (`skip_gnd_routing=True`).
- Nets with fewer than 2 pads are skipped.
- Width occupancy uses conservative grid cells: `ceil((width + clearance)/resolution)`.
- Optional width fallback can use relaxed width (`allow_width_relaxation`).
- Cross-net segments and vias are hard-blocked with cost `1e6`.
- Existing routed geometry is soft-costed (default `existing_trace_cost=100.0`).
- A* applies direction bias:
  - Front layer prefers horizontal
  - Back layer prefers vertical
- Via transition penalty is `VIA_COST=8.0`.
- Search is capped by `max_search`.

## Grid Cost Model

```mermaid
flowchart LR
  boardState[BoardState] --> buildGrid[build_grid]
  buildGrid --> compObstacles[Component bodies cost 100]
  buildGrid --> padSafe[Pad cells and escape corridors cleared]
  buildGrid --> traceSoft[Existing traces as soft obstacles]
  buildGrid --> viaSoft[Existing vias as soft obstacles]
  compObstacles --> routingGrid[RoutingGrid]
  padSafe --> routingGrid
  traceSoft --> routingGrid
  viaSoft --> routingGrid
  routingGrid --> astar[AStarRouter]
```

## Rip-Up/Reroute Behavior

When initial A* pass fails on some nets:

- `RipUpRerouter.solve()` starts from failed-net queue.
- Builds a component-only base grid, then overlays current routed geometry as hard blocks.
- Attempts to route blocked net.
- If blocked, chooses victim nets via `_find_victims()` using:
  - shorter routed length preferred
  - lower net priority preferred
  - fewer prior rip attempts preferred
- Rips up selected victims, retries blocked net, and requeues victims.
- Stops on success, stagnation, max iterations, or timeout.

## Auto-Trace + Experiment Loop Interaction

```mermaid
flowchart TD
  autoexperiment[autoexperiment.py round] --> mutateCfg[mutate_config_minor major]
  mutateCfg --> fullPipeline[FullPipeline.run]
  fullPipeline --> placementPhase[Placement]
  fullPipeline --> routingPhase[Routing and optional RRR]
  routingPhase --> drcQuick[quick_drc]
  drcQuick --> scorePenalty[Apply shorts penalty]
  scorePenalty --> keepCheck{score > best}
  keepCheck -->|yes| copyBest[Copy best board]
  keepCheck -->|no| discard[Discard candidate]
  copyBest --> log[Append experiments.jsonl]
  discard --> log
```
