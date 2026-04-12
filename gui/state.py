"""Shared application state — singleton holding config, DB, and runtime info."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .db import Database

if TYPE_CHECKING:
    from .experiment_runner import ExperimentRunner


# Default search dimension definitions
# Each: (display_name, key, default_value, min, max, step, sigma_frac, enabled)
SEARCH_DIMENSIONS = [
    {
        "key": "force_attract_k",
        "label": "Attract Force (k)",
        "default": 0.02,
        "min": 0.005,
        "max": 0.15,
        "step": 0.005,
        "enabled": True,
        "group": "Placement Physics",
    },
    {
        "key": "force_repel_k",
        "label": "Repel Force (k)",
        "default": 200.0,
        "min": 100.0,
        "max": 500.0,
        "step": 10.0,
        "enabled": True,
        "group": "Placement Physics",
    },
    {
        "key": "cooling_factor",
        "label": "Cooling Factor",
        "default": 0.97,
        "min": 0.90,
        "max": 0.995,
        "step": 0.005,
        "enabled": True,
        "group": "Placement Physics",
    },
    {
        "key": "edge_margin_mm",
        "label": "Edge Margin (mm)",
        "default": 6.0,
        "min": 4.0,
        "max": 10.0,
        "step": 0.5,
        "enabled": True,
        "group": "Board Layout",
    },
    {
        "key": "placement_clearance_mm",
        "label": "Placement Clearance (mm)",
        "default": 2.5,
        "min": 1.0,
        "max": 5.0,
        "step": 0.1,
        "enabled": True,
        "group": "Board Layout",
    },
    {
        "key": "board_width_mm",
        "label": "Board Width (mm)",
        "default": 90.0,
        "min": 50.0,
        "max": 120.0,
        "step": 5.0,
        "enabled": False,
        "group": "Board Dimensions",
    },
    {
        "key": "board_height_mm",
        "label": "Board Height (mm)",
        "default": 58.0,
        "min": 35.0,
        "max": 80.0,
        "step": 5.0,
        "enabled": False,
        "group": "Board Dimensions",
    },
]

DEFAULT_STRATEGY = {
    "rounds": 50,
    "workers": 0,  # 0 = auto
    "plateau_threshold": 3,
    "seed": 0,
    "pcb_file": "LLUPS.kicad_pcb",
}

DEFAULT_SCORE_WEIGHTS = {
    "placement": 0.15,
    "route_completion": 0.50,
    "via_penalty": 0.10,
    "containment": 0.05,
    "drc": 0.20,
}

DEFAULT_TOGGLES = {
    "unlock_all_footprints": False,
    "enable_backside_placement": False,
    "enable_board_size_search": False,
}


def _project_root() -> Path:
    """Find the LLUPS project root (has LLUPS.kicad_pcb)."""
    p = Path(__file__).resolve().parent.parent
    if (p / "LLUPS.kicad_pcb").exists():
        return p
    return Path.cwd()


@dataclass
class AppState:
    """Mutable singleton holding current GUI state."""
    project_root: Path = field(default_factory=_project_root)
    db: Database = field(default=None)

    # Current experiment config being edited in Setup page
    search_dimensions: list[dict] = field(default_factory=lambda: [
        {**d} for d in SEARCH_DIMENSIONS
    ])
    strategy: dict = field(default_factory=lambda: {**DEFAULT_STRATEGY})
    score_weights: dict = field(default_factory=lambda: {**DEFAULT_SCORE_WEIGHTS})
    toggles: dict = field(default_factory=lambda: {**DEFAULT_TOGGLES})

    # Runtime
    active_experiment_id: int | None = None
    runner_pid: int | None = None
    _runner: ExperimentRunner | None = field(default=None, repr=False)

    def __post_init__(self):
        if self.db is None:
            self.db = Database()

    @property
    def runner(self) -> ExperimentRunner:
        """Lazy-init singleton ExperimentRunner."""
        if self._runner is None:
            from .experiment_runner import ExperimentRunner
            self._runner = ExperimentRunner(
                self.project_root, self.scripts_dir, self.experiments_dir)
        return self._runner

    @property
    def experiments_dir(self) -> Path:
        return self.project_root / ".experiments"

    @property
    def scripts_dir(self) -> Path:
        return (self.project_root / ".claude" / "skills" /
                "kicad-helper" / "scripts")

    def to_config_dict(self) -> dict:
        """Build the full config dict for autoexperiment.py."""
        config = {}
        # Search dimensions
        for dim in self.search_dimensions:
            if dim["enabled"]:
                config[f"_search_{dim['key']}"] = {
                    "min": dim["min"],
                    "max": dim["max"],
                    "step": dim["step"],
                }
            config[dim["key"]] = dim["default"]
        # Strategy
        config["_strategy"] = {**self.strategy}
        # Score weights
        config["_score_weights"] = {**self.score_weights}
        # Toggles
        config.update(self.toggles)
        return config

    def load_from_config(self, config: dict) -> None:
        """Restore state from a saved config dict."""
        for dim in self.search_dimensions:
            key = dim["key"]
            if key in config:
                dim["default"] = config[key]
            search_key = f"_search_{key}"
            if search_key in config:
                s = config[search_key]
                dim["min"] = s.get("min", dim["min"])
                dim["max"] = s.get("max", dim["max"])
                dim["step"] = s.get("step", dim["step"])
                dim["enabled"] = True
            elif f"_search_{key}" not in config and key not in (
                "board_width_mm", "board_height_mm"
            ):
                dim["enabled"] = True
        if "_strategy" in config:
            self.strategy.update(config["_strategy"])
        if "_score_weights" in config:
            self.score_weights.update(config["_score_weights"])
        for k in DEFAULT_TOGGLES:
            if k in config:
                self.toggles[k] = config[k]

    def get_param_ranges(self) -> dict:
        """Build param_ranges dict for autoexperiment mutation functions."""
        ranges = {}
        for dim in self.search_dimensions:
            if dim["enabled"]:
                ranges[dim["key"]] = [dim["min"], dim["max"]]
        return ranges

    def get_enabled_dimensions(self) -> list[dict]:
        return [d for d in self.search_dimensions if d["enabled"]]

    def get_disabled_dimensions(self) -> list[dict]:
        return [d for d in self.search_dimensions if not d["enabled"]]


# Module-level singleton
_state: AppState | None = None


def get_state() -> AppState:
    global _state
    if _state is None:
        _state = AppState()
    return _state
