"""Default configuration — project-agnostic placement/routing engine defaults.

Project-specific overrides (ic_groups, component_zones, etc.) should be
passed as config dict at runtime.  See LLUPS_CONFIG below for an example,
or load from a JSON file with load_project_config().
"""

import json
import os
from pathlib import Path

DEFAULT_CONFIG = {
    # Trace widths (5 mil = 0.127mm)
    "signal_width_mm": 0.127,
    "power_width_mm": 0.127,

    # Via
    "via_drill_mm": 0.3,
    "via_size_mm": 0.6,

    # Placement clearance — minimum gap between component bounding boxes.
    # 2.5mm leaves room for vias/traces, reduces courtyard overlaps.
    "placement_clearance_mm": 2.5,

    # Power nets (common names — projects override with their own)
    "power_nets": set(),

    # Placement (spread components — room to route, no courtyard overlaps)
    "placement_grid_mm": 1.0,
    "edge_margin_mm": 6.0,
    "force_attract_k": 0.02,
    "force_repel_k": 200.0,
    "cooling_factor": 0.97,

    # Placement solver iterations
    "max_placement_iterations": 300,
    "placement_convergence_threshold": 0.5,
    "placement_score_every_n": 1,
    "intra_cluster_iters": 80,

    # Placement diversity: "cluster" (centroid-based) or "random" (uniform scatter).
    # MINOR mode always uses "cluster"; MAJOR uses "random" 50% of the time;
    # EXPLORE always uses "random".  Set by autoexperiment per mutation mode.
    "scatter_mode": "cluster",

    # Temperature reheat: at 50% of max_iterations, apply a random perturbation
    # kick to escape local minima. 0 = disabled, 0.1 = moderate, 0.3 = aggressive.
    "reheat_strength": 0.1,

    # Randomize IC-group internal layout (radius spread + angular shuffle).
    # True for MAJOR/EXPLORE, False for MINOR.
    "randomize_group_layout": False,

    # Courtyard overlap padding — extra margin (mm) added when scoring
    # courtyard overlaps.  Drives the optimizer to leave breathing room.
    "courtyard_padding_mm": 0.5,

    # Pad inset margin — minimum distance (mm) all electrical pads must be
    # inside the board Edge.Cuts boundary.  Pads outside are unfabricatable.
    "pad_inset_margin_mm": 0.3,

    # Edge jitter — maximum random displacement (mm) along the assigned edge
    # for edge-pinned components (connectors, mounting holes).  Provides
    # placement diversity across rounds while keeping components on edges.
    "edge_jitter_mm": 5.0,

    # Connector gap — spacing (mm) between connectors grouped on the same edge.
    "connector_gap_mm": 2.0,

    # Connector edge inset — distance (mm) from board edge to the nearest
    # edge of the connector body.  0 = flush, positive = inset, negative =
    # overhang.  Only applies to edge-pinned connectors.
    "connector_edge_inset_mm": 1.0,

    # Orderedness — how strongly passives are snapped into neat rows/columns.
    # 0.0 = organic/force-directed layout, 1.0 = full grid alignment.
    # Intermediate values blend proportionally.  Searchable by autoexperiment.
    "orderedness": 0.0,

    # Through-hole backside threshold — THT components with bounding-box area
    # above this value (mm²) are placed on B.Cu so SMT parts can use F.Cu.
    # SMT passives always stay on F.Cu — IC group connectivity forces keep
    # them near their THT group leaders, achieving dual-sided board usage.
    "tht_backside_min_area_mm2": 50.0,

    # Minimum placement score to proceed to routing.
    # Below this threshold routing is skipped (saves 15-30s on degenerate layouts).
    "min_placement_score": 20.0,

    # Component zone constraints — per-reference placement rules.
    # Each key is a component reference; value is a dict with one of:
    #   {"edge": "left"|"right"|"top"|"bottom"}  — snap to named edge, lock
    #   {"zone": "center-bottom"|"top-left"|...}  — confine to board region
    #   {"corner": "top-left"|"top-right"|"bottom-left"|"bottom-right"} — pin
    # Unassigned connectors fall back to nearest-edge heuristic.
    "component_zones": {},

    # Signal flow order — ordered list of IC group leader references.
    # Biases cluster centroids along the X-axis (left-to-right) during
    # initial placement.  Gives the layout a natural signal-flow direction.
    "signal_flow_order": [],

    # Skip GND from net counting (routed as zones)
    "skip_gnd_routing": True,

    # Net priority overrides (higher = routed earlier among same class)
    "net_priority": {},

    # Thermal
    "thermal_refs": [],
    "thermal_radius_mm": 3.0,

    # FreeRouting
    "freerouting_jar": os.path.expanduser("~/.local/lib/freerouting-1.9.0.jar"),
    "freerouting_timeout_s": 60,
    "freerouting_max_passes": 40,
    # Nets excluded from trace routing (use copper zones instead).
    # Add power nets that have zone fills (e.g. "GND") to reduce
    # spurious "unconnected" DRC violations.
    "freerouting_ignore_nets": ["GND"],

    # GND zone pour — automatically created/updated to cover full board.
    # Set gnd_zone_net to "" to disable automatic zone creation.
    "gnd_zone_net": "GND",
    "gnd_zone_layer": "B.Cu",
    "gnd_zone_margin_mm": 0.5,

    # Explicit IC groups (IC + supporting components that should stay together).
    # Each key is the group leader (typically an IC reference), value is a list
    # of supporting component references.
    "ic_groups": {},

    # Human-readable group labels for silkscreen annotation.
    "group_labels": {},

    # --- Search space flags ---
    # When True, batteries/connectors/mounting holes are NOT auto-locked;
    # edge_compliance scoring still incentivizes edge placement.
    "unlock_all_footprints": True,

    # When True, the autoexperiment loop can vary board_width_mm / board_height_mm.
    "enable_board_size_search": True,
    # Default board dimensions (mm) — overridden per-round when board size search is active.
    "board_width_mm": 90.0,
    "board_height_mm": 58.0,

    # Board size overhead factor — minimum board area is estimated as
    # total_component_area * overhead_factor.  Larger = more routing room.
    "board_size_overhead_factor": 2.5,
}


# ---------------------------------------------------------------------------
# LLUPS project overrides — used when running against the LLUPS board.
# Merge with:  cfg = {**DEFAULT_CONFIG, **LLUPS_CONFIG}
# ---------------------------------------------------------------------------
LLUPS_CONFIG = {
    "power_nets": {
        "VBUS", "VBAT", "5V", "3V3", "3.3V", "+5V", "+3V3", "GND",
        "/VBUS", "/VBAT", "/5V", "/3V3", "/VSYS", "/VSYS_BOOST",
        "/CELL_NEG", "/EN",
    },

    "thermal_refs": ["U2", "U4"],

    "ic_groups": {
        "U1": ["C1", "R1", "R2", "F1", "J1"],
        "U2": ["C2", "C3", "C4", "R3", "R4", "R5", "R6", "R7", "R8", "RT1", "D1", "D2"],
        "U3": ["Q1", "U6"],
        "U4": ["C5", "C6", "C7", "L1", "D3"],
        "U5": ["C8", "R9", "R10", "R11", "J2", "J3"],
        "BT1": ["BT2"],
    },

    "group_labels": {
        "U1": "USB INPUT",
        "U2": "CHARGER",
        "U3": "BATT PROT",
        "U4": "BOOST 5V",
        "U5": "LDO 3.3V",
    },

    # Board size search enabled — autoexperiment will vary board dimensions
    # to find smallest board that still routes cleanly.
    "enable_board_size_search": True,

    # Component zone constraints for the LLUPS board layout.
    # Signal flow: USB input (left) → charger → protection → boost → LDO → output (right)
    "component_zones": {
        "J1":  {"edge": "left"},            # USB-C input connector
        "J2":  {"edge": "right"},          # Output header
        "J3":  {"edge": "right"},          # Debug header
        "BT1": {"zone": "bottom"},        # Battery holders — shared zone, sibling
        "BT2": {"zone": "bottom"},        # grouping pulls them adjacent
        "H4":  {"corner": "top-left"},
        "H86": {"corner": "bottom-right"},
    },

    # Signal flow left-to-right: USB → charger → protection → boost → LDO
    "signal_flow_order": ["U1", "U2", "U3", "U4", "U5"],
}


def load_project_config(config_path: str = None) -> dict:
    """Load a project config from a JSON file.

    If config_path is None, looks for a *_config.json in the autoplacer
    directory. Returns empty dict if no file found.

    JSON values are converted: lists of strings in "power_nets" become sets.
    """
    if config_path is None:
        # Auto-discover config file next to this module
        module_dir = Path(__file__).parent
        candidates = sorted(module_dir.glob("*_config.json"))
        if not candidates:
            return {}
        config_path = str(candidates[0])

    with open(config_path) as f:
        cfg = json.load(f)

    # Convert power_nets list to set for efficient lookup
    if "power_nets" in cfg and isinstance(cfg["power_nets"], list):
        cfg["power_nets"] = set(cfg["power_nets"])

    return cfg
