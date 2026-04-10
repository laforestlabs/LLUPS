"""Default configuration for the LLUPS board."""

import os

DEFAULT_CONFIG = {
    # Trace widths (5 mil = 0.127mm)
    "signal_width_mm": 0.127,
    "power_width_mm": 0.254,

    # Via
    "via_drill_mm": 0.3,
    "via_size_mm": 0.6,

    # Placement clearance — minimum gap between component bounding boxes.
    # 2.0mm leaves room for vias/traces, still keeps groups tight.
    "placement_clearance_mm": 2.0,

    # Power nets
    "power_nets": {
        "VBUS", "VBAT", "5V", "3V3", "3.3V", "+5V", "+3V3", "GND",
        "/VBUS", "/VBAT", "/5V", "/3V3", "/VSYS", "/VSYS_BOOST",
        "/CELL_NEG", "/EN",
    },

    # Placement (spread components — room to route, no courtyard overlaps)
    "placement_grid_mm": 1.0,
    "edge_margin_mm": 6.0,
    "force_attract_k": 0.02,
    "force_repel_k": 200.0,
    "cooling_factor": 0.97,

    # Placement solver iterations (reduced for speed)
    "max_placement_iterations": 100,
    "placement_convergence_threshold": 1.5,
    "placement_score_every_n": 1,
    "intra_cluster_iters": 80,

    # Skip GND from net counting (routed as zones)
    "skip_gnd_routing": True,

    # Net priority overrides (higher = routed earlier among same class)
    "net_priority": {},

    # Thermal
    "thermal_refs": ["U2", "U4"],
    "thermal_radius_mm": 3.0,

    # FreeRouting
    "freerouting_jar": os.path.expanduser("~/.local/lib/freerouting-2.1.0.jar"),
    "freerouting_timeout_s": 120,
    "freerouting_max_passes": 40,

    # Explicit IC groups (IC + supporting components that should stay together)
    "ic_groups": {
        "U1": ["C1", "C2", "R1", "R2", "F1", "J1"],
        "U2": ["C4", "R3", "R4", "R5", "RT1", "D1", "D2"],
        "U3": ["Q1"],
        "U4": ["C5", "C6", "C7", "L1", "D3"],
        "U5": ["C8", "R9", "R10", "R11", "J2"],
        "U6": ["J3"],
    },
}
