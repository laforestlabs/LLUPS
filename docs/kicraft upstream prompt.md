# KiCraft Upstream Pipeline — Implementation Brief

Build the upstream portion of KiCraft: the part that turns a user's natural-language project description into the file set that the existing KiCraft layout/routing pipeline ingests.

The downstream contract is fixed and documented in `upstream_schematic_prompt.md` (treat it as authoritative — KiCraft will not be patched). Your output is the file set described there: a hierarchical KiCad 9 schematic, a `.kicad_pro`, and an `_autoplacer.json`, plus any custom footprints.

## Architecture

A multi-turn chat application with five stages and one orchestrator. State is a single mutable object; stages overwrite their slot when re-run. The first four stages are LLM-driven; the fifth is mechanical.

### Stages

Each stage is a function: `(conversation_history, current_state) -> (updated_slot, open_questions)`.

1. **Intent** — goal, constraints, named parts, inferred user expertise.
2. **Functional spec** — abstract functional blocks (sense/process/drive/power/interface), inter-block signal types, no topology choices.
3. **Architecture** — commits to topologies, regulation strategy, MCU vs. analog, comms protocols, rail voltages, **and the sheet hierarchy** (each functional block becomes a leaf sheet; sheet names follow §7 of the contract doc). Also fixes the set of power nets and inter-sheet connectivity.
4. **BOM** — selects real parts with MPN, value, package, sourcing info, **reference designator**, and **footprint string in `Library:Name` form**. Assigns each part to a sheet. Identifies IC groups (each non-trivial IC with its supporting passives), signal flow order, thermal hotspots, and any edge/corner placement constraints (connectors, mounting holes, batteries).
5. **Synthesis** — deterministic, non-LLM. Reads the full state and writes the KiCraft file set. Enforces every rule in §2, §3, §4, §7 of the contract doc. Runs the mechanical checks in §9 before returning success.

Stages are stateless over the state object. When re-run, they overwrite their own slot. Downstream stages re-run on change; do not attempt fine-grained invalidation.

### Orchestrator

A single agent that, on each user turn, decides one of: run a stage, ask a clarifying question, or respond conversationally. Implement as an LLM call seeing the conversation, current state, and open questions. No turn-classifier taxonomy, no explicit state machine.

### Clarification

Not a separate agent. Stages emit `open_questions` alongside their output. The orchestrator surfaces blocking questions immediately, batches material questions (~3–5) at stage boundaries, and silently defaults cosmetic ones. Any default a stage applies must be recorded in that stage's slot (e.g., `assumptions: ["package: SMD (defaulted)"]`) so the user can see and override it in chat.

## State

```python
{
    "intent": ...,
    "functional_spec": ...,
    "architecture": ...,   # includes sheet hierarchy, power nets, inter-sheet nets
    "bom": ...,            # parts with ref, footprint, sheet assignment, grouping hints
    "open_questions": [...],
}
```

Pydantic models for each slot. Stages refuse to run if required upstream slots are missing or fail validation.

## Handoff contract (read the doc, but key points)

The synthesis stage must produce, at minimum:

- `<PROJECT>.kicad_sch` (hierarchical root) and one `<SHEET>.kicad_sch` per leaf — all in the project root, no subdirectories, KiCad 9 format (`version 20250114`).
- Every component carries Reference (regex `^[A-Z]+[0-9]+[A-Z0-9_-]*$`), Value, and a non-empty Footprint in `Library:Name` form.
- Power and ground nets use the recognized name patterns (§2.5); anything else gets listed in `power_nets`.
- `<PROJECT>.kicad_pro` with design rules and at least `Default` + `Power` netclasses.
- `<PROJECT>_autoplacer.json` with `power_nets`, `ic_groups`, `group_labels`, `thermal_refs`, `signal_flow_order`, and any `component_zones`.
- `<PROJECT>.pretty/` only if custom footprints are referenced.

The pragmatic implementation path for synthesis is `kicad-skip` (linked in the doc) rather than hand-writing S-expressions. The `(lib_symbols)` blocks are copied from `/usr/share/kicad/symbols/*.kicad_sym` based on the symbols actually used.

Run the §9 mechanical validations after synthesis and fail loudly if any check fails — do not ship a broken file set.

## Expert mode

A settings toggle. On: UI renders the state object as structured data alongside the chat. Off: agent narrates stage outputs in natural prose at stage boundaries. Same state, different rendering. Edits in expert mode are made by telling the chat what to change.

## Stage transitions

Stages propose completion ("I think we have enough for architecture — want me to proceed?"). The orchestrator surfaces these; the user confirms or redirects.

## Out of scope

- Audit trails, dependency tracking, superseded entries
- Undo/redo or revision history
- Cross-session preference memory
- Replay logic for revisions (just re-run downstream stages)
- Hand-placing components or routing — KiCraft owns the `.kicad_pcb`

## Open contracts to confirm before building

- LLM provider/SDK conventions already in use elsewhere in KiCraft
- Whether stage prompts live alongside code or in a separate prompts directory
- Whether the existing codebase already has Pydantic models or other types for design state worth reusing

## Deliverables

- Pydantic models for each state slot
- One module per stage (intent, functional_spec, architecture, bom, synthesis)
- Orchestrator module
- Minimal chat loop wiring it together
- Expert-mode rendering toggle
- Synthesis stage with validation per §9 of the contract doc

Keep modules small and composable. Prefer clear function boundaries over class hierarchies.

## Reference

The downstream contract doc (`upstream_schematic_prompt.md`) is authoritative for file format, naming, and validation. When in doubt, defer to it rather than reinventing.
