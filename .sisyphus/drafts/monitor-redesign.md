# Draft: Experiment Manager Monitor Redesign

## Requirements (confirmed)
- Current monitor tab is "messy and hard to understand"
- User can't distinguish between rounds, workers, and leaf solve rounds
- Want a **graphical** view showing experiment progression
- Clearly show which nodes are in progress vs finished
- Click or hover on a node to see a **compact PCB render** at that stage
- GUI should be: simple, uncluttered, but dense with usable info
- PCB renders are the primary information-dense element

## User Pain Points (from screenshot)
- Too many text-heavy cards with opaque data
- "Current Target" and "Parent Routing" cards are walls of pipe-delimited text
- "Worker Activity" is cryptic ("Run: total=1 active=0 idle=1 | Leaf: total=3...")
- Round Progress vs Leaf Progress distinction unclear
- No visual hierarchy showing which subcircuits relate to which
- No PCB visualization at all - just numbers and text

## Technical Decisions
- **Visualization**: Pipeline flowchart (horizontal: leaves left, parent right, arrows showing data flow)
- **Node detail**: Inline panel slides in beside tree; shows PCB render, score plot, round history
- **Round detail**: Per-leaf round timeline with thumbnail renders; click a round to see PCB render
- **Score display**: Score plots shown in detail panel when a node is selected (no global score chart)
- **PCB renders**: Use existing PNGs from renders/ directory (kicad-cli + ImageMagick already generates these)
- **Interaction**: Click node to select, inline panel shows detail. Nodes show status badges.
- **Start/Stop controls**: Keep as compact bar at top
- **Technology**: NiceGUI with custom HTML/SVG for flowchart, ui.image for renders, ui.timer for polling

## Research Findings

### LLUPS Hierarchy (7 nodes, flat)
```
LLUPS (root, composite, 0 own components)
  ├── USB INPUT    (leaf, 6 comps, 1 port: VBUS)
  ├── CHARGER      (leaf, 13 comps, 5 ports)
  ├── BATT PROT    (leaf, 3 comps, 2 ports)
  ├── BOOST 5V     (leaf, 6 comps, 3 ports)
  ├── LDO 3.3V     (leaf, 7 comps, 5 ports)
  └── BT1          (leaf, 2 comps, 1 port: VBAT)
```
- 1 root + 6 leaves. No intermediate parents.
- Pipeline: leaves solve (placement + routing) -> acceptance -> parent composition -> parent routing

### Existing PCB Renders
- Pipeline already generates high-quality PNGs per leaf per round:
  - `renders/round_NNNN_pre_route_front_all.png` / `routed_front_all.png`
  - `renders/pre_route_copper_both.png` / `routed_copper_both.png`
  - Contact sheets, DRC overlays
- Parent also has `parent_stamped.png` / `parent_routed.png`
- These are generated via kicad-cli + ImageMagick

### PCB Rendering Options
- **Option A: Use existing PNGs** - pipeline already generates renders. Just display them.
- **Option B: Lightweight SVG renderer** - build from solved_layout.json (has components, pads, traces, vias with mm coordinates). No KiCad needed. Good for inline thumbnails.
- **Option C: Both** - SVG thumbnails for quick view, existing PNGs on click for detail

### NiceGUI Visualization Options
- `ui.echart` - Apache ECharts has native tree layout. Good fit for 7 nodes.
- `ui.tree` - Quasar tree component (list-style, not graphical)
- Custom SVG via `ui.html` - full control over graph layout
- `ui.image` supports PIL objects, base64, file paths - good for PCB renders
- `ui.dialog` for click-to-expand previews
- `ui.tooltip` for hover info
- `ui.timer(2s)` polling pattern (already used)

### Current Monitor Tab Structure (to replace)
- ~16 text cards with opaque pipe-delimited data
- Plotly score chart
- Pipeline events, artifact listings, top-level outputs panels
- Board preview in collapsed expansion at bottom
- All in single `monitor_page()` function (~500+ lines)
- Polls `run_status.json` + `experiments.jsonl` every 2s via `ui.timer`

## Open Questions
- (asking user now)

## Scope Boundaries
- INCLUDE: Monitor tab complete redesign
- EXCLUDE: Setup tab, Analysis tab (unless minor integration needed)
