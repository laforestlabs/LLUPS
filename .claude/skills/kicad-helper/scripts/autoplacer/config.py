"""Default configuration — project-agnostic placement/routing engine defaults.

Project-specific overrides (ic_groups, component_zones, etc.) should be
passed as config dict at runtime.  See LLUPS_CONFIG below for an example.
"""

import os

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
    "max_placement_iterations": 100,
    "placement_convergence_threshold": 1.5,
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

    # Minimum placement score to proceed to routing.
    # Below this threshold routing is skipped (saves 15-30s on degenerate layouts).
    "min_placement_score": 30.0,

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

    # Explicit IC groups (IC + supporting components that should stay together).
    # Each key is the group leader (typically an IC reference), value is a list
    # of supporting component references.
    "ic_groups": {},

    # Human-readable group labels for silkscreen annotation.
    "group_labels": {},
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

    # Component zone constraints for the LLUPS board layout.
    # Signal flow: USB input (left) → charger → protection → boost → LDO → output (right)
    "component_zones": {
        "J1":  {"edge": "left"},           # USB-C input connector
        "J2":  {"edge": "right"},          # Output header
        "J3":  {"edge": "right"},          # Debug header
        "BT1": {"zone": "center-bottom"},  # Battery holder
        "BT2": {"zone": "center-bottom"},  # Battery holder
        "H4":  {"corner": "bottom-left"},
        "H86": {"corner": "bottom-right"},
    },

    # Signal flow left-to-right: USB → charger → protection → boost → LDO
    "signal_flow_order": ["U1", "U2", "U3", "U4", "U5"],
}
