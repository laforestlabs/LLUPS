---
name: kicad-helper
description: Use when the user asks to "check trace widths", "audit my layout", "list footprints", "rearrange footprints", "arrange LEDs in a grid", "move component", "run DRC", "check clearances", "align components", or discusses KiCad PCB layout automation. Provides Python scripts using the KiCad 9 pcbnew API to parse and modify .kicad_pcb files.
---

# KiCad PCB Helper

Automate KiCad 9 PCB tasks using Python scripts that call the `pcbnew` API.

## Available Scripts

All scripts are in this skill's `scripts/` directory. Run them with `python3`.

### Inspection

| Script | Usage | Description |
|--------|-------|-------------|
| `list_footprints.py` | `python3 scripts/list_footprints.py <pcb>` | List all footprints with reference, value, position, layer |
| `check_trace_widths.py` | `python3 scripts/check_trace_widths.py <pcb> [--min-mm 0.2]` | Find traces narrower than a minimum width |
| `run_drc.py` | `python3 scripts/run_drc.py <pcb>` | Run Design Rule Check and report violations |
| `net_report.py` | `python3 scripts/net_report.py <pcb>` | List all nets with pad counts and connectivity |

### Modification

| Script | Usage | Description |
|--------|-------|-------------|
| `move_component.py` | `python3 scripts/move_component.py <pcb> <ref> <x_mm> <y_mm> [--rotate-deg N]` | Move a footprint to absolute position |
| `arrange_grid.py` | `python3 scripts/arrange_grid.py <pcb> <ref_prefix> --cols N --spacing-mm S [--start-x X --start-y Y]` | Arrange matching footprints in a grid |
| `align_components.py` | `python3 scripts/align_components.py <pcb> <refs...> --axis x|y` | Align footprints along an axis |

## Important Rules

1. **Always back up before modifying**: Scripts that modify the PCB save to `<filename>_modified.kicad_pcb` by default. Pass `--in-place` to overwrite.
2. **Units**: The pcbnew API uses nanometers internally. Scripts accept millimeters and convert with `pcbnew.FromMM()` / `pcbnew.ToMM()`.
3. **After modification**: Tell the user to reload the PCB in KiCad (`File > Revert`).
4. **Do NOT modify .kicad_pcb files with text editing** — always use these scripts or the pcbnew API.

## Extending

To add a new script, write Python using `pcbnew.LoadBoard(path)` to load and `board.Save(path)` to save. Key API patterns:

```python
import pcbnew

board = pcbnew.LoadBoard("file.kicad_pcb")

# Iterate footprints
for fp in board.Footprints():
    ref = fp.GetReferenceAsString()
    pos = fp.GetPosition()
    x_mm, y_mm = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)

# Iterate tracks
for track in board.GetTracks():
    width_mm = pcbnew.ToMM(track.GetWidth())
    layer = track.GetLayerName()
    net = track.GetNetname()

# Move a footprint
fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
fp.SetOrientationDegrees(angle)

# Save
board.Save("output.kicad_pcb")
```
