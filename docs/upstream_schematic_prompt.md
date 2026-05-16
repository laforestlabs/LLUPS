# Upstream schematic prompt for KiCraft

You produce KiCad 9 project files that the **KiCraft** tool ingests to solve PCB placement and routing. Your output is the **schematic side** of the design only — KiCraft owns the PCB layout (component placement, routing, copper, silkscreen). You do not place parts on the board, you do not route traces, and you do not edit `.kicad_pcb` content.

Your job ends when a fresh KiCraft run can parse your files, identify every subcircuit, and start solving. Treat the file contract below as a hard interface — KiCraft will not be patched to accommodate variations.

---

## 1. What you must produce

Drop all files in a single project directory whose name matches the project stem you pick (e.g., for project name `MYPROJ`, the directory is conventionally `MYPROJ/` and the file stems are `MYPROJ.kicad_sch`, `MYPROJ.kicad_pro`, etc.).

| File | Status | Purpose |
|---|---|---|
| `<PROJECT>.kicad_sch` (root) | **REQUIRED** | Hierarchical root containing `(sheet ...)` instances |
| `<SHEET>.kicad_sch` (one per leaf sheet) | **REQUIRED** | Per-sheet schematic content; one file per leaf |
| `<PROJECT>.kicad_pro` | **STRONGLY RECOMMENDED** | Design rules + netclasses (else KiCraft inherits 0.20 mm clearance defaults that may fail your DRC) |
| `<PROJECT>_autoplacer.json` | **STRONGLY RECOMMENDED** | IC groups, power nets, zone hints, signal flow (else KiCraft falls back to generic 90×58 mm board defaults) |
| `<PROJECT>.pretty/` | **CONDITIONAL** | Custom footprint directory — only ship if you reference footprints not in stock KiCad libraries |
| `<PROJECT>.kicad_pcb` (empty stub) | **OPTIONAL** | KiCraft will create one if absent |

**Explicitly do NOT produce or modify:**

- `.kicad_pcb` content — KiCraft overwrites placement and routing wholesale
- Netlists (`.net`) — KiCraft generates these from the schematic
- `program.md` — KiCraft auto-generates and overwrites this
- `sym-lib-table` / `fp-lib-table` — KiCraft ignores library tables and trusts the `Footprint` property embedded in each symbol

---

## 2. Schematic format — `.kicad_sch`

The schematic is **KiCad 9 S-expression format**. The first three lines of every `.kicad_sch` file you produce must be:

```
(kicad_sch
	(version 20250114)
	(generator "eeschema")
```

If your tooling emits an older version number, KiCad 9 will not open it cleanly and KiCraft's parser will reject it.

### 2.1 Hierarchy model

KiCraft requires a **hierarchical** schematic — one root file plus one file per leaf sheet. A flat schematic with all parts in one file is not acceptable: KiCraft uses the hierarchy to identify subcircuits, place each as a cohesive unit, then compose them onto the parent board.

- The **root** `.kicad_sch` contains `(sheet ...)` instances and (usually) no components of its own.
- Each `(sheet ...)` instance references a child file via the `Sheetfile` property.
- **All `.kicad_sch` files live in the same directory** as the root. KiCraft does not recurse into subdirectories.
- Sheets may themselves contain other sheets (multi-level hierarchy), but every leaf must be its own file.

### 2.2 Sheet instance structure (in the root file)

Each child sheet is declared in the root as one `(sheet ...)` block. Minimum required fields:

```
(sheet
	(at 30 40)              ; placement on the root canvas; any non-overlapping coords are fine
	(size 30 15)            ; visual size on the root canvas
	(uuid "<unique-uuid>")  ; generate fresh UUIDs for every block
	(property "Sheetname" "USB INPUT"
		(at 30 39 0)
		(effects (font (size 1.27 1.27)) (justify left bottom))
	)
	(property "Sheetfile" "USB_INPUT.kicad_sch"
		(at 30 56 0)
		(effects (font (size 1.27 1.27)) (justify left top) (hide yes))
	)
	(pin "VBUS" bidirectional
		(at 60 45 0)
		(effects (font (size 1.27 1.27)))
		(uuid "<unique-uuid>")
	)
)
```

Field rules:

- **`Sheetname`** — human-readable label, usually uppercase with spaces (e.g., `"USB INPUT"`, `"CHARGER"`, `"BOOST 5V"`). Used by KiCraft for silkscreen labels and logs.
- **`Sheetfile`** — must match an actual `.kicad_sch` filename in the same directory, case-sensitive. By convention this is the sheetname uppercase with underscores plus `.kicad_sch` (`USB_INPUT.kicad_sch`).
- **`uuid`** — every `(sheet ...)`, `(pin ...)`, `(symbol ...)`, and other block needing identity must carry a fresh RFC-4122 UUID. Reusing UUIDs across blocks will silently break KiCad's instance tracking.

### 2.3 Sheet pins (the inter-sheet interface)

Every signal that crosses the sheet boundary is declared as a `(pin ...)` inside the parent's `(sheet ...)` block AND mirrored as a hierarchical label inside the child schematic with the same name.

Direction values, exact spelling:

| Direction | Meaning | Use for |
|---|---|---|
| `input` | Signal flows into the sheet | Inputs to a subcircuit (e.g., clock in) |
| `output` | Signal flows out of the sheet | Subcircuit outputs (e.g., regulated rail out) |
| `bidirectional` | Signal flows both ways | Power rails, I2C, shared buses, anything not clearly one-way |
| `passive` | No directionality | Plain net connections without polarity |

When in doubt, prefer `bidirectional` for power/ground and `passive` for plain signals. KiCraft maps these to its `InterfaceDirection` enum (`kicraft/hierarchy_parser.py`) — wrong directions will not crash the parse but may bias placement poorly.

### 2.4 Components inside leaf sheets

A leaf `.kicad_sch` contains:

1. A `(lib_symbols ...)` block defining every symbol used in the sheet. These are copied from the stock KiCad symbol libraries at `/usr/share/kicad/symbols/*.kicad_sym` (or wherever your install lives) — copy the matching symbol definitions in full.
2. `(symbol ...)` instances (one per component placed on this sheet).
3. `(wire ...)`, `(junction ...)`, `(hierarchical_label ...)`, and `(global_label ...)` for connectivity.

**Every component `(symbol ...)` instance must carry:**

```
(property "Reference" "U1" ...)
(property "Value" "BQ24072RGT" ...)
(property "Footprint" "Package_DFN_QFN:VQFN-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm" ...)
```

Rules:

- **Reference designator** must match the regex `^[A-Z]+[0-9]+[A-Z0-9_-]*$`. Examples that work: `U1`, `C12`, `R3`, `RT1`, `H86`, `BT1`. Examples that fail: `1U`, `U`, `u1`, `U-1`, `MyPart`.
- **Footprint** must be in the form `LibraryName:FootprintName` and must resolve to an actual `.kicad_mod` file — either in stock KiCad footprint libraries (e.g., `Package_DFN_QFN`, `Capacitor_SMD`, `Resistor_SMD`, `Connector_USB`) or in your project-local `<PROJECT>.pretty/` directory.
- **Footprint must not be empty** — KiCraft does **no** footprint lookup. The string in the schematic is what gets placed. An empty footprint property aborts the run.
- **Value** is informational for KiCraft but should still be set correctly (MPN or part value) — it surfaces in logs and silkscreen.

### 2.5 Net name conventions for power and ground

KiCraft identifies power and ground nets by **name pattern**, not by `POWER_FLAG` symbols. POWER_FLAG is optional in KiCad 9 and you may omit it.

**Recognized power names** (substring match, case-insensitive): `VCC`, `VDD`, `VBAT`, `VBUS`, `VSYS`, `+5V`, `+3V3`, `+3.3V`, `3V3`, `3.3V`, `5V`, `+12V`, `12V`, and similar `+<N>V` / `<N>V` patterns.

**Recognized ground names**: `GND`, `PGND`, `AGND`, `DGND`, anything ending in `_GND`.

**Anything else** is treated as a signal net.

Use these recognized names directly. Do not invent variants like `BATT_POSITIVE` when `VBAT` works, or `EARTH` when `GND` works. Custom names work but will not get power-class trace widths or thermal handling unless you also list them in `power_nets` in the autoplacer config (§4).

### 2.6 Minimal root example

A two-sheet root with one connection between them:

```
(kicad_sch
	(version 20250114)
	(generator "eeschema")
	(generator_version "9.0")
	(uuid "11111111-1111-1111-1111-111111111111")
	(paper "A3")

	(title_block
		(title "MYPROJ - Example")
		(rev "1.0")
	)

	(lib_symbols)

	(sheet
		(at 30 40) (size 30 15)
		(uuid "22222222-2222-2222-2222-222222222222")
		(property "Sheetname" "INPUT" (at 30 39 0) (effects (font (size 1.27 1.27)) (justify left bottom)))
		(property "Sheetfile" "INPUT.kicad_sch" (at 30 56 0) (effects (font (size 1.27 1.27)) (justify left top) (hide yes)))
		(pin "VBUS" bidirectional (at 60 45 0) (effects (font (size 1.27 1.27))) (uuid "33333333-3333-3333-3333-333333333333"))
	)

	(sheet
		(at 80 40) (size 30 15)
		(uuid "44444444-4444-4444-4444-444444444444")
		(property "Sheetname" "REGULATOR" (at 80 39 0) (effects (font (size 1.27 1.27)) (justify left bottom)))
		(property "Sheetfile" "REGULATOR.kicad_sch" (at 80 56 0) (effects (font (size 1.27 1.27)) (justify left top) (hide yes)))
		(pin "VBUS" bidirectional (at 80 45 0) (effects (font (size 1.27 1.27))) (uuid "55555555-5555-5555-5555-555555555555"))
		(pin "+3V3" output (at 110 45 0) (effects (font (size 1.27 1.27))) (uuid "66666666-6666-6666-6666-666666666666"))
	)

	(wire (pts (xy 60 45) (xy 80 45)) (stroke (width 0) (type default)) (uuid "77777777-7777-7777-7777-777777777777"))
)
```

The two sheets are connected via the wire on net `VBUS`. Inside each child file, a `(hierarchical_label "VBUS" ...)` marks where the signal connects to the sheet's internal circuitry.

### 2.7 Minimal leaf example

A leaf sheet with one IC, one decoupling cap, and one hierarchical label:

```
(kicad_sch
	(version 20250114)
	(generator "eeschema")
	(generator_version "9.0")
	(uuid "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
	(paper "A4")

	(lib_symbols
		;; Paste full symbol definitions here for every symbol used below.
		;; Copy from /usr/share/kicad/symbols/<Library>.kicad_sym — find the
		;; (symbol "Library:Name" ...) block and include the whole block verbatim.
	)

	(symbol
		(lib_id "Regulator_Linear:AP2112K-3.3")
		(at 100 80 0)
		(uuid "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
		(property "Reference" "U1" (at 100 70 0))
		(property "Value" "AP2112K-3.3" (at 100 73 0))
		(property "Footprint" "Package_TO_SOT_SMD:SOT-23-5" (at 100 86 0) (effects (hide yes)))
		(instances
			(project "MYPROJ"
				(path "/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" (reference "U1") (unit 1))
			)
		)
	)

	(symbol
		(lib_id "Device:C")
		(at 110 85 0)
		(uuid "cccccccc-cccc-cccc-cccc-cccccccccccc")
		(property "Reference" "C1" (at 112 84 0))
		(property "Value" "1uF" (at 112 86 0))
		(property "Footprint" "Capacitor_SMD:C_0402_1005Metric" (at 110 87 0) (effects (hide yes)))
		(instances
			(project "MYPROJ"
				(path "/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" (reference "C1") (unit 1))
			)
		)
	)

	(hierarchical_label "VBUS" (shape input)
		(at 90 78 180)
		(effects (font (size 1.27 1.27)) (justify right))
		(uuid "dddddddd-dddd-dddd-dddd-dddddddddddd")
	)
	(hierarchical_label "+3V3" (shape output)
		(at 110 78 0)
		(effects (font (size 1.27 1.27)) (justify left))
		(uuid "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
	)

	;; ... wires connecting U1 pins to the hierarchical labels and to C1 ...
)
```

The pragmatic way to produce these is to use eeschema (the KiCad schematic editor) to draw the circuit, then save — eeschema generates correct S-expressions automatically. Alternatively, use a library like [`kicad-skip`](https://github.com/psychogenic/kicad-skip) to manipulate `.kicad_sch` files in Python. Hand-writing S-expressions is possible but error-prone — the `(lib_symbols)` blocks alone can be hundreds of lines per symbol.

---

## 3. Project file — `<PROJECT>.kicad_pro`

The project file is a JSON file holding design rules, netclasses, and KiCad GUI state. KiCraft reads two sections that matter for routing:

### 3.1 Design rules

Set under `board.design_settings.rules`. Suggested floor for a 2-layer board fabricated at common low-cost houses (JLCPCB, PCBWay):

```json
"rules": {
  "min_clearance": 0.15,
  "min_track_width": 0.1524,
  "min_via_diameter": 0.508,
  "min_via_annular_width": 0.127,
  "min_hole_to_hole": 0.127,
  "min_copper_edge_clearance": 0.381
}
```

Tighten for fine-pitch parts; loosen for cheap-tier processes. If you omit `.kicad_pro`, the pcbnew library auto-creates a sidecar with `min_clearance: 0.20 mm` and no netclasses — KiCraft will inherit those and your DRC may fail. **Ship the file.**

### 3.2 Netclasses

Set under `net_settings.classes`. Provide at minimum two classes:

```json
"net_settings": {
  "classes": [
    {
      "name": "Default",
      "clearance": 0.15,
      "track_width": 0.2,
      "via_diameter": 0.6,
      "via_drill": 0.3,
      "priority": 2147483647
    },
    {
      "name": "Power",
      "clearance": 0.3,
      "track_width": 0.5,
      "via_diameter": 0.8,
      "via_drill": 0.4,
      "priority": 0
    }
  ]
}
```

`Power` gets wider traces and more clearance for current-carrying nets. KiCraft assigns nets to classes based on the `power_nets` list in the autoplacer config (§4).

### 3.3 Why this matters

After routing, KiCraft does an atomic save that copies your `.kicad_pro` over the auto-generated sidecar so your design rules survive into validation and the final artifact. If your `.kicad_pro` is missing or incomplete, KiCraft's DRC check runs against KiCad defaults, which will likely produce phantom clearance violations on nets you intended to widen.

---

## 4. Autoplacer config — `<PROJECT>_autoplacer.json`

Strongly recommended. Without it, KiCraft uses `DEFAULT_CONFIG` (a generic 90×58 mm board, no IC grouping, generic power-net list). Functional but the resulting layouts are mediocre.

The file is plain JSON at the project root. Full key reference:

### 4.1 Identity

```json
"project_name": "MYPROJ",
"pcb_file": "MYPROJ.kicad_pcb"
```

- `project_name` (str) — informational identifier.
- `pcb_file` (str) — target PCB filename (relative to project root). KiCraft writes the routed board here.

### 4.2 Net classification

```json
"power_nets": ["+3V3", "+5V", "VBAT", "VBUS", "GND"]
```

- `power_nets` (list[str]) — net names treated as power class. These get wider traces, higher routing priority, and consideration for thermal zones. Include every rail and `GND`. Include leading `/` variants if your sheet hierarchy generates them (e.g., `/VBAT` is how the same net appears in a child sheet's local namespace).

### 4.3 IC grouping (the most valuable input)

```json
"ic_groups": {
  "U2": ["C2", "C3", "C4", "R3", "R4", "D1"],
  "U4": ["C5", "C6", "L1"]
}
```

- `ic_groups` (dict[str, list[str]]) — maps an IC reference (the "leader") to the supporting passives and discretes that should be placed near it. Decoupling caps, feedback resistors, inductors, thermistors, protection diodes — every part whose physical placement must be tight to the IC.
- This is the single most impactful input for placement quality. Spend time on it.

### 4.4 Group labels (silkscreen)

```json
"group_labels": {
  "U2": "CHARGER",
  "U4": "BOOST 5V"
}
```

- `group_labels` (dict[str, str]) — human-readable label per IC group, rendered on silkscreen near the cluster.

### 4.5 Thermal handling

```json
"thermal_refs": ["U2", "U4"]
```

- `thermal_refs` (list[str]) — IC refs that dissipate enough heat to want a copper pour or thermal-relief pattern. Typically regulator ICs (boost, LDO, charger), power MOSFETs.

### 4.6 Placement constraints per component

```json
"component_zones": {
  "J1": {"edge": "left"},
  "J2": {"edge": "right"},
  "BT1": {"zone": "bottom"},
  "H4": {"corner": "top-left"},
  "H86": {"corner": "bottom-right"}
}
```

- `component_zones` (dict[str, dict]) — per-ref placement hints. Keys: `edge` (`left|right|top|bottom`), `corner` (`top-left|top-right|bottom-left|bottom-right`), `zone` (`top|bottom` — board region, not layer).
- Use for connectors that must reach a board edge, mounting holes that must be at corners, batteries that occupy a specific region.

### 4.7 Signal flow

```json
"signal_flow_order": ["U1", "U2", "U3", "U4", "U5"]
```

- `signal_flow_order` (list[str]) — IC refs in the order signals flow through them. Biases placement toward a left-to-right (or input→output) arrangement that matches the schematic's logical flow.

### 4.8 Edge connectors

```json
"connector_edge_inset_mm": 0.0
```

- `connector_edge_inset_mm` (float) — distance (mm) from the board edge that edge-pinned connectors are inset. `0.0` means flush with the edge.

### 4.9 Board size search

```json
"enable_board_size_search": true
```

- `enable_board_size_search` (bool) — when `true`, KiCraft's autoexperiment varies board outline dimensions during the search. When `false`, the outline is fixed at the value derived from `parent_placement` limits or defaults.

### 4.10 Parent-board (hierarchical compose) configuration

```json
"parent_placement": {
  "candidate_search": {
    "k": 8,
    "time_budget_s": 480.0,
    "max_outline_height_mm": 120.0,
    "max_outline_width_mm": 160.0
  },
  "backside_through_hole_leaves": ["BATT"]
}
```

- `parent_placement.candidate_search.k` (int) — number of candidate parent-board arrangements to evaluate.
- `parent_placement.candidate_search.time_budget_s` (float) — seconds allowed for the parent search.
- `parent_placement.candidate_search.max_outline_*_mm` (float) — hard upper bound on parent board outline.
- `parent_placement.backside_through_hole_leaves` (list[str]) — sheet names whose through-hole parts may have SMT components stacked on the backside (typical: battery holders, where SMT can live underneath).

### 4.11 Tool paths

```json
"freerouting_jar": "/home/jason/.local/lib/freerouting-1.9.0.jar"
```

- `freerouting_jar` (str) — path to the FreeRouting JAR KiCraft will invoke for autorouting. If unknown, omit and KiCraft will use its default discovery.

### 4.12 Minimal autoplacer.json

If you can't fill all of the above, this minimum gets you out of the default-fallback regime:

```json
{
  "project_name": "MYPROJ",
  "pcb_file": "MYPROJ.kicad_pcb",
  "power_nets": ["+3V3", "+5V", "GND"],
  "ic_groups": {
    "U1": ["C1", "C2"]
  },
  "group_labels": {"U1": "REGULATOR"},
  "signal_flow_order": ["U1"]
}
```

---

## 5. Custom footprints — `<PROJECT>.pretty/`

Only ship a `<PROJECT>.pretty/` directory if you reference footprints not in stock KiCad libraries. Stock libraries live at `/usr/share/kicad/footprints/` (Linux) or equivalent — they include `Package_*`, `Capacitor_SMD`, `Resistor_SMD`, `Connector_*`, `Inductor_*`, `LED_SMD`, `Diode_SMD`, and many more.

If you do need custom footprints:

1. Create the directory `<PROJECT>.pretty/` at the project root.
2. Place each footprint as a `<FootprintName>.kicad_mod` file inside.
3. In schematic symbols, reference them as `<PROJECT>:<FootprintName>` — the library name in the colon-pair must match the directory's stem (`MYPROJ.pretty` → `MYPROJ:FootprintName`).

You do **not** need to ship `fp-lib-table` — KiCraft does not consult it. KiCraft reads the footprint string directly from each symbol's `Footprint` property and loads the file at the implied path.

---

## 6. Directory layout on disk

```
MYPROJ/
├── MYPROJ.kicad_sch                ; root hierarchy (REQUIRED)
├── MYPROJ.kicad_pro                ; design rules + netclasses (RECOMMENDED)
├── MYPROJ_autoplacer.json          ; placement config (RECOMMENDED)
├── MYPROJ.kicad_pcb                ; empty stub (OPTIONAL — KiCraft creates if absent)
├── INPUT.kicad_sch                 ; leaf sheet (REQUIRED, one per leaf)
├── REGULATOR.kicad_sch             ; leaf sheet
├── OUTPUT.kicad_sch                ; leaf sheet
└── MYPROJ.pretty/                  ; custom footprints (CONDITIONAL)
    └── MyCustomConnector.kicad_mod
```

**All `.kicad_sch` files must be in the project root, not in subdirectories.** KiCraft's hierarchy parser resolves `Sheetfile` references relative to the root file's directory and does not recurse.

---

## 7. Naming and value conventions

- **Project stem** — pick one identifier (UPPERCASE preferred, no spaces, no hyphens) and use it as the prefix for `.kicad_sch`, `.kicad_pro`, `.kicad_pcb`, and `_autoplacer.json`. Example: project stem `MYPROJ` → `MYPROJ.kicad_sch`, `MYPROJ.kicad_pro`, `MYPROJ.kicad_pcb`, `MYPROJ_autoplacer.json`, `MYPROJ.pretty/`.
- **Sheet names** — uppercase with spaces in `Sheetname` (`"USB INPUT"`), uppercase with underscores in `Sheetfile` (`USB_INPUT.kicad_sch`). Keep them descriptive of function (`CHARGER`, `BOOST_5V`, `LDO_3V3`, `MCU`, `USB_HUB`), not implementation detail.
- **Reference designators** — standard EDA letters: `U` (IC), `Q` (transistor), `C` (capacitor), `R` (resistor), `L` (inductor), `D` (diode), `LED` (LED), `J` (connector), `H` (mounting hole), `F` (fuse), `RT` (thermistor), `BT` (battery), `SW` (switch), `Y` (crystal), `TP` (test point). Append an integer (`U1`, `C12`, `R3`); optionally a suffix (`U1A`, `H4_GND`).
- **Net names** — use the recognized power/ground patterns from §2.5 directly. Avoid synonyms (`BATT+` → use `VBAT`; `EARTH` → use `GND`). For non-power signal nets, name them by function (`MOSI`, `SCL`, `~RESET`, `CHG_STATUS`), not by routing path.
- **Footprint references** — always `Library:Name`. Use stock libraries (`Package_SO`, `Capacitor_SMD`, `Resistor_SMD`, `Connector_USB`) when possible; use `<PROJECT>:` for custom.

---

## 8. Anti-patterns — do not do these

- **Do not flatten the schematic.** A single 200-component flat sheet is rejected. KiCraft needs hierarchy to identify subcircuits.
- **Do not leave footprint slots empty.** No footprint = no placement. KiCraft does not look up footprints from MPN, value, or symbol library.
- **Do not invent net names for power and ground** that aren't in the recognized patterns (§2.5), unless you also list them in `power_nets`.
- **Do not ship a `.kicad_pcb` with hand-placed components or routed traces.** KiCraft overwrites placement and routing — your work will be lost and may confuse the parser. Ship an empty stub or no file at all.
- **Do not edit or ship `program.md`.** KiCraft auto-generates it from the GUI or defaults; your version will be overwritten.
- **Do not ship `sym-lib-table` or `fp-lib-table` expecting KiCraft to honor them.** It does not.
- **Do not nest `.kicad_sch` files in subdirectories.** All schematic files live at the project root.
- **Do not reuse UUIDs** across blocks. Every `(sheet ...)`, `(symbol ...)`, `(pin ...)`, and instance needs a fresh RFC-4122 UUID.
- **Do not set the schematic version to anything below `20250114`** (KiCad 9). Older versions fail KiCraft's parser.
- **Do not include a `.kicad_prl` (project-local) file.** It's user-specific GUI state and KiCraft does not read it.

---

## 9. Self-validation checklist

Before declaring done, run these checks. They are mechanical and fast.

### 9.1 Schematic version is KiCad 9

```bash
grep -H '(version ' *.kicad_sch
```

Every line should show `(version 20250114)` or later.

### 9.2 Every component has a non-empty footprint

```bash
grep -rE '\(property "Footprint" ""' *.kicad_sch && echo "FAIL: empty footprints found" || echo "OK: all footprints set"
```

Must print `OK`. Empty footprint properties abort the run.

### 9.3 Every sheet pin has a valid direction

```bash
grep -hE '^\s*\(pin "' *.kicad_sch \
  | grep -vE ' (input|output|bidirectional|passive) ' \
  && echo "FAIL: pin(s) with missing/invalid direction" \
  || echo "OK: all pin directions valid"
```

Must print `OK`. Pins without one of the four valid directions break KiCraft's interface-direction inference.

### 9.4 Every Sheetfile resolves to a real file

```bash
python3 -c "
import re, pathlib, sys
root = pathlib.Path('.')
refs = []
for sch in root.glob('*.kicad_sch'):
    for m in re.finditer(r'\(property \"Sheetfile\" \"([^\"]+)\"', sch.read_text()):
        refs.append((sch.name, m.group(1)))
missing = [(s, r) for s, r in refs if not (root / r).is_file()]
if missing:
    for s, r in missing: print(f'FAIL: {s} references missing {r}')
    sys.exit(1)
print(f'OK: all {len(refs)} Sheetfile refs resolve')
"
```

### 9.5 Autoplacer config is valid JSON

```bash
python3 -c "import json; json.load(open('<PROJECT>_autoplacer.json')); print('OK')"
```

### 9.6 Every ref named in the autoplacer config exists in the schematic

```bash
python3 -c "
import json, re, pathlib, sys
cfg = json.load(open('<PROJECT>_autoplacer.json'))
refs_in_sch = set()
for sch in pathlib.Path('.').glob('*.kicad_sch'):
    for m in re.finditer(r'\(property \"Reference\" \"([A-Z]+[0-9]+[A-Z0-9_-]*)\"', sch.read_text()):
        refs_in_sch.add(m.group(1))
named = set()
for ic, parts in cfg.get('ic_groups', {}).items():
    named.add(ic); named.update(parts)
named.update(cfg.get('thermal_refs', []))
named.update(cfg.get('signal_flow_order', []))
named.update(cfg.get('component_zones', {}).keys())
missing = sorted(named - refs_in_sch)
if missing: print('FAIL: refs in autoplacer.json not present in schematic:', missing); sys.exit(1)
print(f'OK: all {len(named)} named refs found in schematic')
"
```

### 9.7 KiCraft can parse the hierarchy

If KiCraft is installed in your environment:

```bash
solve-subcircuits <PROJECT>.kicad_sch
```

Exit code `0` with a non-empty subcircuit listing means the contract is satisfied. Any parse error message points to a structural problem you need to fix before handing off.

---

## 10. End-to-end smoke test (optional)

If you have time and KiCraft is installed, run a short autoexperiment to confirm the full pipeline starts:

```bash
autoexperiment <PROJECT>.kicad_pcb --schematic <PROJECT>.kicad_sch --time-budget 60
```

You're not looking for a good final score — 60 seconds is too short. You're looking for: pipeline initializes, parses the schematic, identifies subcircuits, places at least one candidate. If it gets that far, your upstream output is well-formed.

If the pipeline aborts before placing anything, read the error and fix the schematic — do not patch around it or ship anyway. KiCraft will fail the same way on the downstream run.
