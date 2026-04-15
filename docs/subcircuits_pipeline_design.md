# LLUPS Subcircuits Pipeline Redesign

> Status: Proposed design
> Branch target: `feature/sub-circuits-redesign`
> Scope: Major architectural redesign of the KiCad helper pipeline
> Goal: Replace whole-board-first layout with a scalable hierarchical subcircuit pipeline

---

## 1. Executive Summary

The current pipeline optimizes placement and routing primarily at the whole-board level, with an intermediate notion of functional groups used during placement. That approach works for small and medium designs, but it does not scale well as schematic complexity grows. Routing hundreds of connections at once creates a combinatorial search problem, and global placement changes can destabilize already-good local arrangements.

This redesign introduces **subcircuits as first-class layout units**.

A project schematic must be organized into **true KiCad hierarchical sheets**. Each sheet represents a functional group, typically one or more ICs plus their supporting passives, connectors, protection parts, and local power-conditioning parts. Each group exposes explicit interfaces to the rest of the design. The pipeline solves the design **bottom-up**:

1. Solve each **leaf schematic sheet** independently as a mini layout.
2. Save the best result as a **frozen subcircuit artifact**.
3. Assemble higher levels using solved child subcircuits as **rigid layout macros**.
4. Allow only **translation and rotation** of solved subcircuits at higher levels.
5. Route only the **inter-subcircuit connectivity** at each higher level.

This turns one large routing problem into many small routing problems plus a smaller composition problem. The result should be more scalable, more reusable, and more stable across optimization rounds.

---

## 2. Problem Statement

### 2.1 Current limitations

The current pipeline has several structural limitations:

- It still thinks in terms of a mostly global board state.
- Functional grouping is helpful for placement, but not yet a full layout abstraction.
- Routing is still effectively a board-wide operation.
- Good local layouts are not preserved as reusable artifacts.
- Higher-level optimization can disturb lower-level structure.
- Complexity grows too quickly as component count and net count increase.

### 2.2 Why this matters

For larger designs, the current strategy becomes increasingly inefficient:

- Routing 100+ nets globally is much harder than routing 10 nets in each of 10 groups.
- Placement search becomes unstable because local and global objectives compete.
- Repeated experiments waste time rediscovering good local arrangements.
- The schematic's functional structure is not fully leveraged by the layout engine.

### 2.3 Design objective

The new pipeline must make layout complexity scale with schematic hierarchy. If the schematic is well-organized into functional sheets, the layout engine should exploit that structure directly.

---

## 3. Core Design Principles

### 3.1 True schematic sheets are the source of truth

Grouping must come from **actual KiCad hierarchical sheets**, not inferred labels or heuristic clustering.

This means:

- The top-level schematic defines the hierarchy.
- Child sheets define subcircuits.
- Only **leaf sheets** are independently solved into mini layouts.
- Parent sheets compose solved children and route between them.

Heuristic grouping may remain as a legacy fallback, but it is not part of the primary architecture.

### 3.2 Leaf-first solving

Only **leaf sheets** are solved as independent layout problems.

A leaf sheet contains:
- components
- internal nets
- explicit interfaces to the outside world

A non-leaf sheet contains:
- child sheet instances
- possibly local components
- interconnect between children and local parts

### 3.3 Solved subcircuits are rigid

Once a subcircuit is solved and accepted:

- internal component positions are frozen
- internal component rotations are frozen
- internal traces and vias are frozen
- internal copper geometry is frozen
- internal relative pad geometry is frozen

At higher levels, the subcircuit may only be transformed as a whole by:

- translation in `x/y`
- rotation in-plane

Whole-subcircuit flipping to the opposite side is deferred to a future phase.

### 3.4 Interfaces must be explicit and typed

Subcircuits must expose explicit interfaces. These interfaces are the contract between hierarchy levels.

Where possible, interfaces should be derived from:
- hierarchical sheet pins
- hierarchical labels
- explicit port metadata

The system should normalize these into strict typed interface objects.

### 3.5 Artifacts must be persistent and inspectable

Each solved leaf subcircuit must produce:

1. a machine-readable artifact for the pipeline
2. a mini `.kicad_pcb` for human inspection and debugging

### 3.6 Higher levels compose, not redesign

Parent levels should not re-optimize the internals of solved children. They should only:

- place child subcircuits as rigid macros
- place any parent-local components
- route interconnect between children and local parts
- score the composition

---

## 4. High-Level Pipeline

The redesigned pipeline is bottom-up and recursive.

### 4.1 Phase 0: Hierarchy extraction

Input:
- top-level `.kicad_sch`

Output:
- a hierarchy tree of sheet instances

Tasks:
- parse the top-level schematic
- recursively parse child sheets
- identify leaf sheets
- collect component membership
- collect parent-child relationships
- collect cross-sheet interfaces

### 4.2 Phase 1: Interface normalization

For each sheet:
- identify all external interfaces
- normalize them into strict typed ports
- classify direction, role, and access policy

### 4.3 Phase 2: Leaf extraction

For each leaf sheet:
- extract local components
- classify nets into internal vs external
- build a local board state
- synthesize a local solving envelope

### 4.4 Phase 3: Leaf solve loop

For each leaf:
- generate candidate placements
- route internal nets
- score each candidate
- keep the best result
- freeze it as a subcircuit layout artifact

### 4.5 Phase 4: Artifact persistence

For each solved leaf:
- save JSON metadata
- save mini `.kicad_pcb`
- save score summary
- optionally cache for reuse

### 4.6 Phase 5: Parent composition

For each non-leaf sheet:
- load solved child artifacts
- instantiate them as rigid macros
- place parent-local components
- route interconnect between children and local parts
- score the composition

### 4.7 Phase 6: Recursive upward propagation

Repeat parent composition until the top-level board is assembled.

### 4.8 Phase 7: Final board assembly

At the top level:
- stamp all frozen child layouts into the final board
- route remaining interconnect
- refill zones
- run DRC
- compute final experiment score

---

## 5. Terminology

### 5.1 Subcircuit

A subcircuit is a schematic-defined functional unit represented by a sheet instance. It may be:

- a leaf subcircuit: directly solved into a mini layout
- a composite subcircuit: composed from solved child subcircuits and local parts

### 5.2 Interface

An interface is an explicit connection contract between a subcircuit and its parent or siblings. It is represented by one or more typed ports.

### 5.3 Frozen layout

A frozen layout is a solved subcircuit whose internal geometry is immutable at higher levels.

### 5.4 Rigid macro

A rigid macro is a placed instance of a frozen subcircuit layout used during parent-level composition.

---

## 6. Hierarchy Model

### 6.1 Required schematic structure

The new pipeline assumes:

- the project uses true KiCad hierarchical sheets
- each functional group is represented by a sheet
- leaf sheets contain the actual components for that group
- parent sheets connect child sheets through explicit interfaces

### 6.2 Leaf vs non-leaf sheets

A **leaf sheet**:
- contains components
- contains no child sheets
- is independently solved

A **non-leaf sheet**:
- contains child sheets
- may contain local components
- is solved by composing children and local parts

### 6.3 Hierarchy invariants

The hierarchy parser should enforce these invariants:

- every component belongs to exactly one sheet instance
- every leaf sheet has a stable identity
- every cross-sheet connection is represented as an interface
- parent-child relationships are acyclic
- sheet instance paths are unique

---

## 7. Interface Model

### 7.1 Why strict interfaces are necessary

Without explicit interfaces, higher-level placement and routing become ambiguous. A rigid subcircuit needs a stable external contract so that parent-level composition can reason about:

- where signals enter and leave
- what kind of signals they are
- which connection points are intended for external routing
- whether non-interface access is allowed

### 7.2 Interface object requirements

Each interface port should include at least:

- `name`
- `role`
- `direction`
- `net_name`
- `cardinality`
- `preferred_side`
- `access_policy`

### 7.3 Proposed port roles

Suggested enum values:

- `POWER_IN`
- `POWER_OUT`
- `GROUND`
- `SIGNAL_IN`
- `SIGNAL_OUT`
- `BIDIR`
- `DIFF_P`
- `DIFF_N`
- `BUS`
- `ANALOG`
- `TEST`
- `MECHANICAL`

### 7.4 Proposed directions

Suggested enum values:

- `INPUT`
- `OUTPUT`
- `BIDIRECTIONAL`
- `PASSIVE`
- `UNKNOWN`

### 7.5 Preferred side metadata

Optional but useful values:

- `LEFT`
- `RIGHT`
- `TOP`
- `BOTTOM`
- `ANY`

This metadata can guide parent-level placement and routing.

### 7.6 Access policy

Suggested enum values:

- `INTERFACE_ONLY`
- `OPEN_ACCESS`

Default:
- `INTERFACE_ONLY`

This controls whether higher-level routing may connect only to declared interface anchors or may also connect to other exposed pads inside the subcircuit.

### 7.7 Recommended default policy

Default to:
- `INTERFACE_ONLY`

Rationale:
- preserves clean abstraction boundaries
- improves reuse and caching
- reduces accidental damage to local layout quality
- makes parent-level routing more predictable

Optional mode:
- `OPEN_ACCESS`

This can be enabled later or per-project when more flexibility is desired.

---

## 8. Routing Policy

### 8.1 Leaf-level routing

At the leaf level, the router may:
- route all internal nets
- route to interface anchor pads
- optimize local trace quality
- optimize local via count
- optimize local compactness and manufacturability

### 8.2 Parent-level routing

At parent levels, the router should primarily:
- route between child interfaces
- route between child interfaces and parent-local components
- avoid modifying child internals

### 8.3 Access modes

#### `INTERFACE_ONLY`
Parent-level routing may connect only to:
- declared interface anchors
- parent-local components

#### `OPEN_ACCESS`
Parent-level routing may also connect to:
- other exposed pads in child geometry

This mode should be optional and likely score-penalized in a future refinement.

### 8.4 Global rails

Power and ground need special handling.

Recommended first-version policy:

- local decoupling and short local rail segments stay inside leaf subcircuits
- top-level power and ground stitching happens at higher levels
- copper zones remain primarily top-level in the first implementation

This avoids difficult zone-merging logic during the initial redesign.

---

## 9. Board-Side Policy

### 9.1 Current preference to preserve

The current system prefers:
- large through-hole components on the back side
- SMT components on the front side opposite those THT parts
- efficient dual-sided area usage

This behavior should be preserved.

### 9.2 First-version constraints

For the first version:

- leaf solvers may still place large THT parts on the back side
- SMT remains front-biased
- whole-subcircuit flipping is disabled
- parent-level transforms allow translation and rotation only

### 9.3 Future extension

Later, the system may support:
- whole-subcircuit flipping
- side-aware interface remapping
- mirrored geometry transforms
- more advanced front/back packing

That is explicitly out of scope for the first redesign phase.

---

## 10. Artifact Model

Each solved leaf subcircuit must produce two artifacts.

### 10.1 JSON metadata artifact

Purpose:
- machine-readable pipeline input
- caching
- reproducibility
- score tracking

Suggested contents:

- schema version
- subcircuit id
- source sheet path
- source schematic hash
- config hash
- solver version
- component refs
- local component transforms
- local traces
- local vias
- local bounding box
- interface definitions
- interface anchor geometry
- score breakdown
- artifact generation timestamp

### 10.2 Mini `.kicad_pcb` artifact

Purpose:
- human inspection
- debugging
- visual diffing
- optional replay/import

Suggested contents:

- only the subcircuit's footprints
- local traces and vias
- synthetic local outline
- interface labels or markers
- optional score annotation in comments or metadata

### 10.3 Artifact identity

Artifacts should be keyed by a stable identity derived from:

- sheet instance path
- schematic hash
- config hash
- solver version
- interface schema version

This enables caching and invalidation.

---

## 11. Data Model Proposal

The current `types.py` contains useful primitives such as `Point`, `Component`, `Net`, and `BoardState`. The redesign needs additional hierarchy-specific types.

### 11.1 `SubCircuitId`

Represents a stable identity for a sheet instance.

Suggested fields:

- `sheet_name`
- `sheet_file`
- `instance_path`
- `parent_instance_path`

### 11.2 `InterfacePort`

Represents one exposed connection point.

Suggested fields:

- `name`
- `kind`
- `direction`
- `net_name`
- `bus_index`
- `required`
- `preferred_side`
- `access_policy`

### 11.3 `SubCircuitDefinition`

Logical definition derived from the schematic.

Suggested fields:

- `id`
- `sheet_name`
- `sheet_file`
- `component_refs`
- `ports`
- `child_ids`
- `parent_id`
- `is_leaf`

### 11.4 `SubCircuitLayout`

Frozen solved layout artifact.

Suggested fields:

- `subcircuit_id`
- `components`
- `traces`
- `vias`
- `bounding_box`
- `interface_anchors`
- `score`
- `artifact_paths`
- `frozen`

### 11.5 `SubCircuitInstance`

A placed instance of a solved subcircuit in a parent board.

Suggested fields:

- `layout_id`
- `origin`
- `rotation`
- `transformed_bbox`
- `access_mode`

### 11.6 `HierarchyLevelState`

Represents one composition level.

Suggested fields:

- `child_instances`
- `local_components`
- `interconnect_nets`
- `board_outline`
- `constraints`

---

## 12. Scoring Redesign

The current scoring system is mostly board-level. The new pipeline needs hierarchical scoring.

### 12.1 Leaf score

Each leaf subcircuit should be scored on:

- placement quality
- internal route completion
- internal DRC
- compactness
- manufacturability
- interface cleanliness
- SMT-over-THT efficiency
- local congestion

### 12.2 Parent score

Each parent composition should be scored on:

- child packing quality
- interconnect route completion
- interconnect trace length
- congestion near child boundaries
- interface alignment quality
- parent-level DRC
- board containment

### 12.3 Aggregate score

The final top-level score should combine:

- child layout quality
- parent composition quality
- final board quality

Important rule:
- a parent should not score highly if it depends on poor child layouts

### 12.4 Future scoring extensions

Potential future additions:

- interface accessibility score
- thermal separation score
- return-path quality score
- hierarchy-aware congestion score
- reuse/cache hit bonus for stable subcircuits

---

## 13. Caching Strategy

Caching is important for scalability.

### 13.1 Why caching matters

If a leaf sheet has not changed, the pipeline should not need to re-solve it every time. This is especially important for large projects with many stable functional blocks.

### 13.2 Cache key inputs

Suggested cache key inputs:

- sheet schematic hash
- footprint set hash
- config hash
- solver version
- interface schema version

### 13.3 Cache behavior

If the cache key matches:
- reuse the existing leaf artifact
- skip leaf solving
- continue upward composition

If the cache key changes:
- invalidate and re-solve that leaf
- invalidate any dependent parent compositions as needed

### 13.4 First-version recommendation

Design for caching from the start, even if the first implementation only partially exploits it.

---

## 14. Backward Compatibility Strategy

This redesign is large enough that it should not be forced into the existing pipeline path.

### 14.1 Recommended approach

Keep the current pipeline as:
- legacy flat / group-based mode

Add a new pipeline as:
- subcircuits mode

### 14.2 Why separate paths are better

Benefits:
- lower migration risk
- easier debugging
- easier A/B comparison
- less accidental regression in the current workflow

### 14.3 Long-term direction

Once the new pipeline is stable:
- legacy mode may remain as a fallback
- or be deprecated later

That decision can be made after the redesign proves itself.

---

## 15. Proposed Module Layout

The redesign likely needs new modules rather than overloading the current group-placement modules.

Suggested additions:

- `autoplacer/brain/hierarchy_parser.py`
  - parse true schematic hierarchy

- `autoplacer/brain/interface_model.py`
  - strict interface typing and normalization

- `autoplacer/brain/subcircuit_types.py`
  - hierarchy and artifact dataclasses

- `autoplacer/brain/subcircuit_solver.py`
  - leaf solve loop

- `autoplacer/brain/subcircuit_artifacts.py`
  - save/load JSON and mini PCB artifacts

- `autoplacer/brain/subcircuit_composer.py`
  - parent-level rigid composition

- `autoplacer/brain/subcircuit_router.py`
  - inter-subcircuit routing policy

- `autoplacer/pipeline_subcircuits.py`
  - new end-to-end pipeline

Potential legacy/transitional modules:
- existing `groups.py`
- existing `group_placer.py`

These may remain for compatibility or be partially reused during migration.

---

## 16. Implementation Roadmap

This redesign should be implemented in milestones.

### Milestone 1: Design scaffolding

Goal:
- establish the new hierarchy and interface model

Deliverables:
- design doc
- new dataclasses
- hierarchy parser for true sheets
- leaf/non-leaf identification
- interface normalization
- debug CLI to print hierarchy and interfaces

### Milestone 2: Leaf extraction and artifact generation

Goal:
- extract leaf-local board states and persist artifacts

Deliverables:
- leaf extraction logic
- local board-state builder
- JSON artifact writer
- mini PCB artifact writer
- artifact schema versioning

### Milestone 3: Leaf placement/routing solve

Goal:
- independently solve leaf subcircuits

Deliverables:
- local placement
- local routing
- local scoring
- candidate search loop
- best-artifact selection

### Milestone 4: Parent composition

Goal:
- compose solved children as rigid macros

Deliverables:
- rigid macro placement
- parent-local component support
- interconnect net extraction
- parent-level scoring

### Milestone 5: Top-level routing and final assembly

Goal:
- assemble the final board from frozen children

Deliverables:
- final board stamping
- inter-subcircuit routing
- interface-only routing mode
- optional open-access toggle
- final DRC and experiment score integration

### Milestone 6: Caching and optimization

Goal:
- make the pipeline practical for large projects

Deliverables:
- leaf artifact cache
- invalidation rules
- faster reruns
- better diagnostics and logging

---

## 17. First Implementation Session Plan

The first implementation session after branch setup should focus on foundation, not routing.

Recommended tasks:

1. add this design doc
2. create new hierarchy/interface/subcircuit dataclasses
3. implement true sheet hierarchy parsing
4. add a debug CLI that prints:
   - hierarchy tree
   - leaf sheets
   - component membership
   - normalized interfaces

This creates a stable base for later routing and artifact work.

---

## 18. Risks and Open Questions

### 18.1 KiCad artifact representation

Open question:
- should the JSON artifact be the canonical representation, with mini PCB as a debug export?
- or should the mini PCB be canonical and JSON be derived?

Recommendation:
- JSON should be canonical for pipeline logic
- mini PCB should be an inspectable export

### 18.2 Interface inference quality

If interface extraction is weak, parent-level routing quality will suffer.

Mitigation:
- prefer explicit hierarchical pins and labels
- normalize aggressively
- validate interface completeness early

### 18.3 Zone ownership

Copper zones are difficult to merge across hierarchy.

Recommendation for first version:
- keep zone ownership mostly top-level
- allow local copper only where necessary
- defer hierarchical zone merging

### 18.4 Cross-hierarchy constraints

Some constraints span multiple subcircuits:
- thermal separation
- connector edge placement
- analog isolation
- return-path quality

These must remain visible at parent and top levels.

### 18.5 Mixed local/global optimization

There is a tension between:
- preserving rigid subcircuits
- allowing global routing flexibility

The `INTERFACE_ONLY` vs `OPEN_ACCESS` toggle is the first mechanism for managing that tradeoff.

---

## 19. Deferred Features

The following are intentionally deferred:

- whole-subcircuit backside flipping
- arbitrary non-rigid child edits at parent level
- deep multi-level optimization beyond parent-child composition
- automatic interface-side inference from routing feedback
- hierarchical copper zone merging
- cross-project subcircuit library reuse
- interface-preferred-but-not-required routing mode
- advanced thermal-aware floorplanning
- automatic port ordering optimization from congestion feedback

---

## 20. Success Criteria

The redesign should be considered successful if it achieves the following:

### 20.1 Structural success

- true schematic sheets drive grouping
- leaf sheets are independently solved
- solved children are reused as rigid macros
- parent levels compose rather than redesign children

### 20.2 Functional success

- the pipeline can solve a multi-sheet project bottom-up
- artifacts are saved and reloadable
- top-level assembly preserves child internals exactly
- final board generation works end-to-end

### 20.3 Scalability success

Compared to the current pipeline, the new pipeline should:
- handle larger designs more predictably
- reduce routing search explosion
- improve reuse of good local layouts
- reduce instability across optimization rounds

### 20.4 Debuggability success

The new system should make it easy to inspect:
- hierarchy structure
- leaf extraction
- interface definitions
- saved subcircuit artifacts
- parent-level composition decisions

---

## 21. Recommended Defaults

For the first implementation, use these defaults:

- grouping source: true schematic sheets only
- independently solved units: leaf sheets only
- subcircuit transform policy: translate + rotate only
- whole-subcircuit flip: disabled
- top-level routing access: `INTERFACE_ONLY`
- artifact outputs: JSON + mini `.kicad_pcb`
- THT policy: preserve current back-side preference for large THT parts
- SMT policy: preserve front-side preference opposite THT where useful
- zone policy: mostly top-level
- compatibility strategy: separate new pipeline path, keep legacy path intact

---

## 22. Summary

This redesign turns the KiCad helper from a mostly whole-board optimizer into a **hierarchical layout system**.

The key shift is conceptual:

- from **groups as placement hints**
- to **subcircuits as frozen layout artifacts**

That shift enables:
- scalability
- reuse
- stability
- better alignment between schematic structure and physical layout

The implementation should proceed in milestones, starting with hierarchy parsing and interface modeling, then moving to leaf solving, artifact persistence, parent composition, and final board assembly.

This is intentionally a major redesign. The new branch exists to allow aggressive refactoring where needed without being constrained by the assumptions of the current pipeline.