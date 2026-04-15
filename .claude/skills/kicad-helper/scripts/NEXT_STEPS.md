# Autoplacer — Next Steps

Future work for the hierarchical group-based placement system.

## Intra-group routing awareness

The current intra-group placer (`solve_group()`) optimizes component
positions within each group using a force-directed simulation, but it
has no knowledge of how traces will actually be routed between pads.

**Potential improvements:**

- After intra-group placement, run a lightweight channel/escape router
  within each group's bounding box to estimate trace congestion.
- Use congestion feedback to adjust component spacing or rotation
  before the group is "frozen" as a rigid block.
- Score intra-group routability (e.g., estimated via count, trace
  crossings within the group) and feed it back into group placement
  quality metrics.

## Smarter inter-group placement

The current `GroupPlacer` uses a simple force-directed approach at the
group level. Possible refinements:

- **Simulated annealing** at the group level — the small entity count
  (5-10 groups) makes SA feasible with full evaluation per step.
- **Rotation of group blocks** — currently groups are always placed
  axis-aligned. Allowing 90-degree group rotation could improve
  packing on asymmetric boards.
- **Multi-objective optimization** — balance signal flow order, edge
  constraints, thermal separation, and inter-group net length
  simultaneously using Pareto ranking.

## Group-aware swap optimization

The flat solver's swap optimizer (`solve()` step 7) freely swaps any
two similarly-sized components to minimize crossover count. This is
group-blind — it can scatter group members.

**Fix:** restrict swaps to within-group or between-group as a unit.
When evaluating a swap, also check that group coherence doesn't
degrade.

## Dynamic group sizing

Currently, the virtual board size for intra-group placement uses a
fixed formula: `overhead = max(2.0, 3.5 - 0.15 * n)`. This could be
made adaptive:

- Start with a tight bounding box and expand if overlap resolution
  fails to converge within a budget.
- Use the group's net density (number of inter-component connections
  per mm^2) to estimate required routing clearance.

## Schematic-driven pin assignment

For groups with connectors, the schematic provides signal ordering on
the connector pins. This ordering could be used to:

- Place passives in the same order as their connected connector pins
  (reduces trace crossings).
- Orient ICs so that their pin-1 side faces the signal input direction.

## Thermal group separation

Groups containing thermal components (e.g., voltage regulators, power
MOSFETs) should maintain minimum distance from heat-sensitive groups.
Currently `thermal_refs` is defined in config but only affects
individual component spacing, not group-level separation.

## Board shape support

The current system assumes rectangular boards. Extending to support
non-rectangular board outlines (L-shapes, circles, cutouts) would
require:

- Group placement feasibility checking against arbitrary polygons.
- Modified clamping logic for non-rectangular bounds.
- Edge classification for non-rectangular edges (curved, angled).

## Test coverage

- Unit tests for `brain/groups.py` S-expression parser with edge cases
  (escaped quotes, deeply nested structures, malformed files).
- Unit tests for `brain/group_placer.py` with synthetic group
  configurations (2 groups, 10 groups, groups larger than board).
- Integration test: round-trip schematic → groups → placement → score
  with a minimal test project (3 components, 2 groups).
