"""Default configuration for the LLUPS board."""

DEFAULT_CONFIG = {
    # Grid (0.5mm = good speed/quality tradeoff for 2-layer board)
    "grid_resolution_mm": 0.5,

    # Trace widths (5 mil = 0.127mm)
    "signal_width_mm": 0.127,
    "power_width_mm": 0.127,

    # Via
    "via_drill_mm": 0.3,
    "via_size_mm": 0.6,

    # Routing clearance (trace-to-trace / trace-to-pad). 0.2mm is the DRC minimum.
    "clearance_mm": 0.2,

    # Placement clearance — minimum gap between component bounding boxes.
    # Kept separate from routing clearance so the router isn't over-constrained.
    # 2.5mm gives breathing room for traces between pads of adjacent parts.
    "placement_clearance_mm": 2.5,

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
    "force_repel_k": 400.0,   # stronger repulsion to keep parts separated
    "cooling_factor": 0.97,

    # Routing — cost applied per cell when crossing an existing trace.
    # Intra-net soft obstacles only (100.0). Cross-net traces are hard-blocked (1e6).
    "existing_trace_cost": 100.0,
    "skip_gnd_routing": True,

    # Max A* search nodes per path (raised due to hard-block detours)
    "max_search": 2_000_000,

    # RRR
    "max_rips_per_net": 5,
    "rip_stagnation_limit": 5,
    "rrr_timeout_s": 60,

    # Retry MST from different roots on failure (0=disabled, matches original behavior)
    "mst_retry_limit": 0,

    # Thermal
    "thermal_refs": ["U2", "U4"],
    "thermal_radius_mm": 3.0,
}
