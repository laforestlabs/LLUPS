# LLUPS Subcircuits Pipeline Redesign

> **STALE**: The "current blocker" and status references below are outdated. The pipeline now works end-to-end (all 6 leaves solve+route+accept, parent composes and routes). See `ROADMAP.md` for current state.

> Status: In progress, but not yet MVP
> Branch target: `feature/sub-circuits-redesign`
> Scope: Major architectural redesign of the KiCad helper pipeline
> Goal: Replace whole-board-first layout with a scalable hierarchical subcircuit pipeline
> Progress: Milestone 1 complete; Milestone 2 substantially implemented; Milestone 3 partially implemented with FreeRouting-backed leaf and parent routing; MVP not yet achieved

---

## Current Status and Agreed Direction

This document remains the primary design reference for the subcircuits redesign. The implementation has advanced enough that the original milestone descriptions are no longer sufficient on their own, so this section records the current state, the current blocker, the agreed architectural direction, and the revised MVP definition.

### Current implementation status

Implemented or substantially implemented:
- true-sheet hierarchy parsing
- normalized subcircuit/interface dataclasses
- hierarchy inspection/debug CLI
- leaf-local board-state extraction from the full PCB
- internal/external/ignored net partitioning
- leaf-local placement solving
- canonical solved layout persistence in `solved_layout.json`
- solved artifact loading and rigid transform helpers
- parent composition scaffolding
- hierarchy-aware parent selection in the composition CLI
- lightweight parent-level scoring
- preservation of routed child copper in parent composition
- lightweight parent interconnect routing from transformed interface anchors
- stamping composed parent state into a real `.kicad_pcb` for inspection

Implemented but explicitly provisional:
- leaf-local internal-net routing uses FreeRouting exclusively (via leaf_routing.py)
- parent interconnect routing uses FreeRouting exclusively (via compose_subcircuits.py)
- demo board stamping and preview generation exist only as inspection scaffolding
- compact parent composition layout exists only as a readability aid, not as a real placement optimizer

Partially implemented or incomplete:
- interface anchor inference exists in the leaf solve flow, but solved artifacts still do not reliably carry complete usable anchors for all LLUPS leaves
- parent composition can merge rigid children and route between some of them, but the result is not yet a production-quality routed parent board
- parent-local component support exists in the composition layer API, but is not yet fully wired through a real hierarchy-driven parent workflow
- no true leaf-level FreeRouting solve loop exists yet
- no true parent-level FreeRouting session exists yet that starts from preloaded routed child copper and continues routing from that state
- no hierarchical DRC gate exists that validates each solved leaf before it is accepted as a rigid artifact
- no artifact acceptance policy exists yet for rejecting poor leaf layouts before parent composition

Current observed blocker:
- the current pipeline now reaches real stamped KiCad leaf boards and real FreeRouting invocation, but at least one LLUPS leaf (`USB INPUT`) is still illegal before routing begins
- the stamped `leaf_pre_freerouting.kicad_pcb` is now explicitly rejected by a pre-route legality gate with `illegal_pre_route_geometry`
- this means the immediate blocker is no longer “FreeRouting produced bad copper” but “the stamped pre-route leaf board is already malformed or preserves edge-coupled geometry incorrectly”
- the current pipeline can therefore produce a technically composed parent board, but it is not yet a minimum viable product because accepted routed leaf artifacts do not yet exist, the parent board is not yet placement-optimized, and the resulting board is not yet credible for human review or DRC-driven acceptance

### What is not acceptable as MVP

The following are explicitly not sufficient for MVP:
- a synthetic or readability-only demo board
- a parent board composed from unrouted or insufficiently-routed leaves without DRC acceptance
- a parent board that visually demonstrates hierarchy but is not a credible routed PCB
- a preview image that is readable only after manual interpretation
- a FreeRouting DSN load that starts from a malformed or non-credible parent board

The recent “demo” path proved that routed child copper can be preserved and stamped into a parent board, but it also proved that this is not enough. The resulting board was not human-readable, not placement-optimized, and not a convincing hierarchical routing product. That path should now be treated as a debugging scaffold, not as the target deliverable.

### Revised MVP definition

For LLUPS, the minimum viable product is:

1. solve selected leaf subcircuits with real placement optimization
2. route those leaf subcircuits with FreeRouting
3. validate each accepted leaf artifact with at least a basic DRC / legality gate
4. persist those accepted routed leaf artifacts as the canonical child inputs
5. compose a parent board from those routed leaf artifacts
6. preserve the routed child copper exactly in the parent board
7. launch parent FreeRouting from that preloaded parent board without clearing the child copper
8. produce a parent board that is human-readable on screen and credible enough to inspect in KiCad
9. make the entire flow reproducible from CLI without ad hoc manual patching

This MVP does not require full recursive hierarchy, full global optimization, or perfect final routing quality. It does require a real hierarchical routing flow that starts from accepted routed leaves and continues at the parent level.

### Agreed architectural direction

The agreed direction is:

1. schematic hierarchy is the source of truth for logical connectivity
2. solved artifacts must carry explicit physical interface anchors
3. parent composition combines logical interconnect definitions with physical anchor geometry
4. heuristic anchor synthesis may exist as a fallback, but not as the primary contract
5. FreeRouting is the sole routing engine for both leaf and parent levels
6. FreeRouting-backed routed leaf artifacts must become the canonical inputs to parent routing for MVP

In practical terms:

- hierarchy and normalized interfaces define what connects
- solved artifacts define where those connections can physically enter or leave a rigid child layout
- parent composition should not depend on heuristic geometry reconstruction when canonical anchor data is available
- fallback anchor synthesis is acceptable only for backward compatibility, incomplete artifacts, or debugging
- FreeRouting is the sole routing engine for both leaf and parent levels

### Why this direction was chosen

This hybrid model separates concerns cleanly:

- logical connectivity belongs to the schematic hierarchy
- physical routing entry points belong to solved layout artifacts
- parent composition should consume both, rather than trying to derive both from one side alone

This is more robust than a purely anchor-driven design because composition can still understand connectivity even when physical anchors are missing. It is also more robust than a purely hierarchy-driven design because parent routing eventually needs explicit physical entry points on rigid child layouts.

The recent implementation work also clarified an additional point: preserving routed child copper in a parent board is necessary but not sufficient. The routed child artifacts themselves must be credible, and the parent board must start from a sane composed placement. Otherwise the result is only a technical proof of data flow, not a usable product.

### Immediate next implementation sequence

The next implementation sequence should be:

1. update this design doc to reflect the current state, the failed demo path, and the revised MVP definition
2. stop treating any unrouted or heuristic parent demo as a target deliverable
3. keep the true leaf-level FreeRouting solve path and fix the stamped pre-route board legality:
   - stamp a real leaf board
   - validate the stamped pre-route board before routing
   - reject immediately if the stamped board is already illegal
   - only then run FreeRouting on the leaf board
   - import SES
   - persist the routed leaf board as the canonical artifact once accepted
4. keep and extend the leaf acceptance gates:
   - no Python exceptions
   - no malformed board geometry
   - no illegal pre-route board geometry
   - no obviously illegal routed geometry
   - basic DRC / legality summary persisted with the artifact
   - render diagnostics persisted with the artifact
5. improve anchor completeness for the LLUPS leaves that still have incomplete or missing anchors:
   - `USB INPUT`
   - `BATT PROT`
   - battery holder / battery sheet artifacts as needed
6. compose the real root parent from accepted routed leaf artifacts
7. implement a parent FreeRouting path that preserves preloaded child copper instead of clearing all traces first
8. produce a real parent `.kicad_pcb` that can be opened in KiCad and inspected before and after parent FreeRouting
9. only after the above works, revisit preview rendering and presentation polish

### Current LLUPS-specific reality

At the time of writing, the LLUPS schematic hierarchy consists of:
- one root sheet
- direct leaf children only
- no deeper non-root composite parents yet

That means the current hierarchy-aware composition flow can already compose the real root parent, but deeper recursive parent composition cannot yet be exercised on this project until the schematic hierarchy grows beyond one level.

This is acceptable for MVP. The immediate goal is not arbitrary recursive depth. The immediate goal is a credible root-level hierarchical routing flow for the existing LLUPS hierarchy.

### Render diagnostics direction

A lightweight render-diagnostics workflow is now part of the debugging direction for this branch.

The purpose is not presentation polish. The purpose is to make these questions answerable quickly for each leaf artifact:

- is the stamped pre-route leaf board already illegal?
- are footprints outside or misaligned to `Edge.Cuts`?
- did FreeRouting add meaningful copper?
- did routing improve or worsen the board visually?
- what exact persisted `.kicad_pcb` file produced the preview being reviewed?
- what machine-readable routing/log summary corresponds to that board snapshot?

The preferred artifact location is:

- `.experiments/subcircuits/<slug>/renders/`

The preferred minimal artifact set per leaf is:

- `pre_route_copper_both.png`
- `pre_route_front_all.png`
- `pre_route_drc.json`
- `pre_route_drc_overlay.png` when coordinate-bearing violations exist
- `routed_copper_both.png`
- `routed_front_all.png`
- `routed_drc.json`
- `routed_drc_overlay.png` when coordinate-bearing violations exist
- `pre_vs_routed_contact_sheet.png`

These artifacts should be treated as debugging aids that expose geometry and legality problems early. They do not change the MVP definition, but they do make the current blocker much easier to inspect.

Just as important, renders should not become the only inspectable artifact. The preferred direction for this branch is now board-first observability:

- persist a meaningful `.kicad_pcb` stage snapshot first
- render PNG previews from that persisted board
- expose the board path alongside the preview in monitoring and analysis surfaces
- preserve enough machine-readable metadata to correlate optimizer logs with the exact board artifact

For leaf candidate rounds, that means the preferred observability bundle is no longer only artifact-level renders. It should include round-specific board snapshots such as:

- `round_0003_leaf_pre_freerouting.kicad_pcb`
- `round_0003_leaf_routed.kicad_pcb`

and round-specific metadata that can answer:

- whether the round routed, failed, or was skipped
- which internal nets routed or failed (stored in routing metadata)
- which router was used (always FreeRouting)
- which preview images and board files belong to that round

This keeps KiCad board files as the visual source of truth while JSON remains the machine-readable source of truth.

### Current LLUPS-specific status

The LLUPS subcircuit pipeline is functional end-to-end:
- all 6 leaves solve, route via FreeRouting, and pass acceptance gates
- parent composition assembles routed leaf artifacts and routes interconnects via FreeRouting
- DRC acceptance gates block boards with shorts from being persisted
- the parent acceptance gate currently rejects due to FreeRouting routing quality (a tuning target, not a functional gap)
- interface anchor coverage is sufficient for all current leaves

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

The interface model now has two distinct layers:

1. logical interface definition
2. physical interface realization

Logical interface definition comes from the schematic hierarchy and includes:
- port name
- net name
- role
- direction
- preferred side
- access policy
- cardinality
- required/optional status

Physical interface realization comes from the solved layout artifact and includes:
- one or more physical anchor points for the port
- layer
- backing pad reference when applicable
- anchor provenance
- whether the anchor is canonical or fallback-generated

This separation is intentional. The hierarchy defines what must connect. The solved artifact defines where that connection can physically occur on the rigid child layout.

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

**Implemented so far:**
- true leaf extraction from the full project `BoardState`
- internal / external / ignored net partitioning
- local synthetic board envelope derivation
- local coordinate translation for components, pads, traces, and vias
- JSON artifact/debug export under `.experiments/subcircuits/`

### 4.4 Phase 3: Leaf solve loop

For each leaf:
- generate candidate placements
- route internal nets
- score each candidate
- keep the best result
- freeze it as a subcircuit layout artifact

**Implemented so far:**
- local placement search now runs on extracted leaf-local `BoardState` objects
- the existing `PlacementSolver` is reused for early leaf solving
- multiple local placement rounds can be searched per leaf
- the best local placement round is selected by placement score
- inferred interface anchors are generated from solved pad geometry
- solved placement summaries are persisted into artifact debug output
- solved local placement geometry is now persisted into artifact debug output
- solved component positions, rotations, layers, body centers, and pad geometry are serialized for reuse
- a first mini-board export utility now exists for solved leaf layouts
- the leaf solve CLI now writes a synthetic `.kicad_pcb` snapshot for solved leaf layouts
- leaf-local routing for internal nets is implemented via FreeRouting (leaf_routing.py)
  - routes only nets classified as internal by the extractor
  - uses FreeRouting DSN/SES flow on the stamped leaf mini-board
  - is invoked by the solve CLI when local routing is enabled
- canonical solved layout artifacts are now being introduced:
  - solved component geometry
  - solved trace/via geometry
  - inferred interface anchors
  - bounding box and score metadata
  - stable artifact hashes for later reuse/loading
  - a canonical `solved_layout.json` file per solved leaf artifact directory
- rigid solved-artifact loading and transform helpers are now being introduced:
  - solved artifacts can be reconstructed into `SubCircuitLayout`
  - the loader prefers canonical `solved_layout.json` when present
  - the loader falls back to `debug.json` for older artifacts that do not yet persist canonical solved layout files
  - rigid instances can be created with translation + rotation
  - transformed anchors, copper, and bounding boxes can be derived for parent composition
- parent composition scaffolding is now being introduced:
  - solved child artifacts can be treated as rigid modules
  - transformed child geometry can be inspected before stamping into a parent state
  - composition-side tooling can now reason about child bounding boxes and interface anchors

**Not implemented yet:**
- DSN/SES-based local autorouting for leaf mini-boards
- persistence of solved copper into reusable high-fidelity mini `.kicad_pcb` artifacts from an actual routed solve
- full parent-level composition using solved rigid child layouts

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

Each solved leaf subcircuit must produce two canonical artifact families, and may also produce additional stage-specific observability artifacts.

### 10.1 JSON metadata artifact

Purpose:
- machine-readable pipeline input
- caching
- reproducibility
- score tracking
- optimizer/log review

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
- acceptance / rejection status
- routing summary
- preview paths
- board paths for meaningful stage snapshots

The preferred canonical machine-readable artifact for accepted layouts is `solved_layout.json`.

### 10.2 Mini `.kicad_pcb` artifact

Purpose:
- human inspection
- debugging
- visual diffing
- optional replay/import
- visual source of truth for stage review

Suggested contents:

- only the subcircuit's footprints
- local traces and vias
- synthetic local outline
- interface labels or markers
- optional score annotation in comments or metadata

For this branch, the preferred board-first artifact rule is:

- persist `.kicad_pcb` stage snapshots first
- render PNG previews from those persisted boards
- expose the board paths anywhere previews are shown

For accepted leaves, the preferred board artifacts are:

- `leaf_pre_freerouting.kicad_pcb`
- `leaf_routed.kicad_pcb`

For candidate-round observability, the preferred board artifacts are:

- `round_000N_leaf_pre_freerouting.kicad_pcb`
- `round_000N_leaf_routed.kicad_pcb`

For parent composition/routing, the preferred board artifacts are:

- `parent_pre_freerouting.kicad_pcb`
- `parent_routed.kicad_pcb`

### 10.3 Artifact identity

Artifacts should be keyed by a stable identity derived from:

- sheet instance path
- schematic hash
- config hash
- solver version
- interface schema version

This enables caching and invalidation.

### 10.4 Observability artifacts

In addition to canonical accepted artifacts, the pipeline should preserve enough stage-specific observability data to support both human and machine review.

Preferred observability contents include:

- round-specific preview image paths
- round-specific board paths
- router name
- routed / failed / skipped state
- failure reason
- routed internal nets
- failed internal nets
- routed copper summary
- DRC summaries and reports

These observability artifacts are not a replacement for canonical solved geometry. They exist to make optimizer behavior and board-state transitions inspectable without ambiguity.

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

**Status: implemented**
- shared subcircuit/interface dataclasses were added to `types.py`
- a true-sheet hierarchy parser was added
- a debug inspection CLI was added and wired to the shared parser
- the current LLUPS hierarchy has been successfully parsed and inspected

### Milestone 2: Leaf extraction and artifact generation

Goal:
- extract leaf-local board states and persist artifacts

Deliverables:
- leaf extraction logic
- local board-state builder
- JSON artifact writer
- mini PCB artifact writer
- artifact schema versioning

**Status: partially implemented**
- leaf extraction records and artifact metadata helpers were added
- artifact path resolution and stable hashing were added
- a CLI now exports per-leaf metadata/debug artifacts
- leaf-local board-state extraction from the full PCB is implemented
- internal/external/ignored net partitioning is implemented
- local envelope sizing and coordinate translation are implemented
- mini `.kicad_pcb` generation is implemented for solved leaf layouts
- canonical solved layout persistence is implemented
- explicit physical interface-anchor persistence still needs to be strengthened into a first-class validated artifact contract

### Milestone 3: Leaf placement/routing solve

Goal:
- independently solve leaf subcircuits

Deliverables:
- local placement
- local routing
- local scoring
- candidate search loop
- best-artifact selection

**Status: implemented**
- a leaf placement solver module was added
- extracted local board states can now be solved with the existing placement engine
- a CLI now runs multi-round local placement search across all leaf sheets
- best-round selection is implemented using local placement score
- solved interface anchors are inferred from placed pad geometry
- solved placement/debug summaries are written back into artifact outputs
- solved component geometry is serialized into artifact debug payloads
- mini-board `.kicad_pcb` snapshots are emitted into the subcircuit artifact directories
- FreeRouting-backed local routing is implemented for internal nets and is active in the solve flow
- canonical solved layout artifact persistence is implemented so parent composition can load a stable machine-readable layout bundle
- canonical solved layouts are written as `solved_layout.json` alongside `metadata.json`, `debug.json`, and `layout.kicad_pcb`
- rigid solved-artifact loading and transform helpers are implemented for parent-level composition work
- parent composition scaffolding is implemented on top of the rigid artifact layer
- DRC acceptance gates validate each leaf before acceptance

### Milestone 4: Parent composition

Goal:
- compose solved children as rigid macros

Deliverables:
- rigid macro placement
- parent-local component support
- interconnect net extraction
- parent-level scoring

**Status: started**
- rigid child composition scaffolding is implemented
- solved child artifacts can be loaded, transformed, and merged into a parent composition state
- hierarchy-aware parent selection is implemented in the composition CLI
- lightweight parent-level scoring is implemented
- parent interconnect extraction is not yet robust enough for production use
- parent-local component support is present in the composition API but not yet fully wired through a real hierarchy-driven workflow
- the next major task is to make parent interconnect extraction hierarchy-driven and then bind it to explicit physical interface anchors from solved artifacts

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

**Completed:**
- the design doc was added
- hierarchy/interface/subcircuit dataclasses were added
- true-sheet hierarchy parsing was implemented
- the inspection CLI was added and validated against LLUPS
- artifact export and leaf board-state extraction were started immediately after this foundation

---

## 18. Risks and Open Questions

### 18.1 KiCad artifact representation

Open question:
- should the JSON artifact be the canonical representation, with mini PCB as a debug export?
- or should the mini PCB be canonical and JSON be derived?

Recommendation:
- JSON should be canonical for pipeline logic
- mini PCB should be a human-inspection/debug artifact

Additional clarification from current implementation experience:
- a stamped parent `.kicad_pcb` is useful for inspection and DSN export, but it is not by itself proof of a valid hierarchical routing product
- the canonical acceptance boundary should remain the routed artifact contract plus validation metadata, not a one-off demo board
- mini PCB should be an inspectable export

### 18.2 Interface inference quality

If interface extraction is weak, parent-level routing quality will suffer.

Mitigation:
- prefer explicit hierarchical pins and labels
- normalize aggressively
- validate interface completeness early

Updated design note:
- logical interface completeness should be validated from the hierarchy
- physical interface-anchor completeness should be validated from solved artifacts
- parent composition should be able to build logical interconnect nets even when physical anchors are missing
- physical routing should prefer canonical anchors and only fall back to synthesized anchors when necessary

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
- parent-level rigid composition and stamping
- solved leaf routing persistence into reusable layout artifacts
- higher-fidelity local autorouting and scoring of internal leaf copper
- upgrading the current lightweight routed leaf output into a reusable high-fidelity rigid artifact
- upgrading the current mini-board exporter from debug snapshot quality to reusable routed artifact quality
- FreeRouting-based local routing flow for leaf mini-boards (implemented)
- local routed-copper scoring and best-round selection that combines placement and internal routing quality
- parent-level loading of canonical solved artifacts as rigid modules
- parent-level transform/stamping of solved child layouts into composition states
- parent-level composition-state builders that merge rigid child geometry and parent-local components into one working state
- parent-level interface-to-interface interconnect extraction and routing

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

**Current implementation note:**
- JSON/debug artifact export is implemented
- extracted local board-state sizing is derived from the actual PCB geometry
- leaf solving with FreeRouting-backed routing is implemented and validated on all LLUPS leaf sheets
- best-round local placement results are persisted into artifact debug output
- solved component geometry is serialized into artifact debug payloads
- mini-board `.kicad_pcb` snapshots are emitted by the leaf solve flow
- the local routing path uses FreeRouting DSN/SES end-to-end:
  - extracted leaf-local board states
  - internal/external net partitioning
  - artifact/debug persistence
  - mini-board copper rendering hooks
  - FreeRouting DSN/SES routing for internal nets
  - solve-flow integration so local routing runs during leaf solving
- canonical solved layout artifacts (`solved_layout.json`) are the machine-readable representation parent composition loads
- rigid solved-artifact loaders and transform helpers treat solved children as true rigid modules
- loader behavior is backward-compatible: canonical solved layout files first, debug payload reconstruction fallback
- parent composition assembles transformed child modules into parent composition states
- parent routing uses FreeRouting with preserved child copper

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