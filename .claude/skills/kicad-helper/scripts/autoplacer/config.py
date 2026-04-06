"""Default configuration for the LLUPS board."""

DEFAULT_CONFIG = {
    # Grid (0.5mm = good speed/quality tradeoff for 2-layer board)
    "grid_resolution_mm": 0.5,

    # Trace widths
    "signal_width_mm": 0.25,
    "power_width_mm": 1.0,

    # Via
    "via_drill_mm": 0.3,
    "via_size_mm": 0.6,

    # Clearances
    "clearance_mm": 0.2,

    # Power nets
    "power_nets": {
        "VBUS", "VBAT", "5V", "3V3", "3.3V", "+5V", "+3V3", "GND",
        "/VBUS", "/VBAT", "/5V", "/3V3", "/VSYS", "/VSYS_BOOST",
        "/CELL_NEG", "/EN",
    },

    # Placement
    "placement_grid_mm": 0.5,
    "edge_margin_mm": 2.0,
    "force_attract_k": 0.08,
    "force_repel_k": 40.0,
    "cooling_factor": 0.97,

    # Routing
    "existing_trace_cost": 10.0,
    "skip_gnd_routing": True,

    # RRR
    "max_rips_per_net": 5,
    "rip_stagnation_limit": 5,

    # Thermal
    "thermal_refs": ["U2", "U4"],
    "thermal_radius_mm": 3.0,
}
