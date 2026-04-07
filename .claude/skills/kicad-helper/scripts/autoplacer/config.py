"""Default configuration for the LLUPS board."""

DEFAULT_CONFIG = {
    # Grid (0.5mm = good speed/quality tradeoff for 2-layer board)
    "grid_resolution_mm": 0.5,

    # Trace widths (thin to start — give router headroom)
    "signal_width_mm": 0.15,
    "power_width_mm": 0.5,

    # Via
    "via_drill_mm": 0.3,
    "via_size_mm": 0.6,

    # Routing clearance (trace-to-trace / trace-to-pad)
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
    # Combined with 0.5 multiplier in A*, this gives ~50-cell detour budget
    # before the router considers shorting through. Heavier than via (8)
    # so detours via other layer are preferred.
    "existing_trace_cost": 100.0,
    "skip_gnd_routing": True,

    # RRR
    "max_rips_per_net": 5,
    "rip_stagnation_limit": 5,

    # Thermal
    "thermal_refs": ["U2", "U4"],
    "thermal_radius_mm": 3.0,
}
