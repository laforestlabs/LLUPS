"""Shared application state for the hierarchical experiment manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .db import Database

if TYPE_CHECKING:
    from .experiment_runner import ExperimentRunner


HIERARCHICAL_CONTROLS = [
    {
        "key": "leaf_rounds",
        "label": "Leaf Solve Rounds",
        "default": 1,
        "min": 1,
        "max": 20,
        "step": 1,
        "enabled": True,
        "group": "Leaf Solving",
        "description": "How many local solve attempts to run per leaf in each experiment round.",
    },
    {
        "key": "top_level_rounds",
        "label": "Top-Level Assembly Rounds",
        "default": 1,
        "min": 1,
        "max": 10,
        "step": 1,
        "enabled": True,
        "group": "Top-Level Assembly",
        "description": "How many visible parent/top-level assembly passes to run per experiment round.",
    },
    {
        "key": "compose_spacing_mm",
        "label": "Parent Composition Spacing (mm)",
        "default": 12.0,
        "min": 4.0,
        "max": 40.0,
        "step": 1.0,
        "enabled": True,
        "group": "Top-Level Assembly",
        "description": "Spacing used when composing routed child artifacts into a parent layout.",
    },
    {
        "key": "max_leaf_candidates",
        "label": "Max Leaf Candidates",
        "default": 1,
        "min": 1,
        "max": 8,
        "step": 1,
        "enabled": False,
        "group": "Search Strategy",
        "description": "Reserved for future multi-candidate leaf exploration.",
    },
]

DEFAULT_STRATEGY = {
    "rounds": 10,
    "workers": 1,
    "plateau_threshold": 1,
    "seed": 0,
    "pcb_file": "LLUPS.kicad_pcb",
    "schematic_file": "LLUPS.kicad_sch",
    "parent_selector": "/",
    "only_selectors": [],
}

DEFAULT_SCORE_WEIGHTS = {
    "leaf_acceptance": 0.55,
    "leaf_routing_quality": 0.20,
    "parent_composition": 0.10,
    "top_level_ready": 0.15,
}

DEFAULT_TOGGLES = {
    "skip_visible_top_level": False,
    "render_top_level_png": True,
    "preserve_existing_subcircuit_artifacts": True,
    "show_only_accepted_frames": False,
}


def _project_root() -> Path:
    """Find the LLUPS project root."""
    p = Path(__file__).resolve().parent.parent
    if (p / "LLUPS.kicad_pcb").exists():
        return p
    return Path.cwd()


@dataclass
class AppState:
    """Mutable singleton holding current GUI state."""

    project_root: Path = field(default_factory=_project_root)
    db: Database = field(default=None)

    hierarchical_controls: list[dict[str, Any]] = field(
        default_factory=lambda: [{**d} for d in HIERARCHICAL_CONTROLS]
    )
    strategy: dict[str, Any] = field(default_factory=lambda: {**DEFAULT_STRATEGY})
    score_weights: dict[str, float] = field(
        default_factory=lambda: {**DEFAULT_SCORE_WEIGHTS}
    )
    toggles: dict[str, Any] = field(default_factory=lambda: {**DEFAULT_TOGGLES})

    active_experiment_id: int | None = None
    runner_pid: int | None = None
    _runner: ExperimentRunner | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.db is None:
            self.db = Database()

    @property
    def runner(self) -> ExperimentRunner:
        """Lazy-init singleton experiment runner."""
        if self._runner is None:
            from .experiment_runner import ExperimentRunner

            self._runner = ExperimentRunner(
                self.project_root,
                self.scripts_dir,
                self.experiments_dir,
            )
        return self._runner

    @property
    def experiments_dir(self) -> Path:
        return self.project_root / ".experiments"

    @property
    def scripts_dir(self) -> Path:
        return self.project_root / ".claude" / "skills" / "kicad-helper" / "scripts"

    def to_config_dict(self) -> dict[str, Any]:
        """Build the full hierarchical config dict for the GUI and persistence."""
        config: dict[str, Any] = {}

        for control in self.hierarchical_controls:
            key = control["key"]
            config[key] = control["default"]
            if control.get("enabled", False):
                config[f"_control_{key}"] = {
                    "min": control["min"],
                    "max": control["max"],
                    "step": control["step"],
                    "group": control.get("group", "General"),
                    "description": control.get("description", ""),
                }

        config["_strategy"] = {**self.strategy}
        config["_score_weights"] = {**self.score_weights}
        config.update(self.toggles)
        config["pipeline"] = "hierarchical_subcircuits"
        return config

    def load_from_config(self, config: dict[str, Any]) -> None:
        """Restore state from a saved config dict."""
        for control in self.hierarchical_controls:
            key = control["key"]
            if key in config:
                control["default"] = config[key]
            control_key = f"_control_{key}"
            if control_key in config and isinstance(config[control_key], dict):
                meta = config[control_key]
                control["min"] = meta.get("min", control["min"])
                control["max"] = meta.get("max", control["max"])
                control["step"] = meta.get("step", control["step"])
                control["enabled"] = True

        if "_strategy" in config and isinstance(config["_strategy"], dict):
            self.strategy.update(config["_strategy"])

        if "_score_weights" in config and isinstance(config["_score_weights"], dict):
            self.score_weights.update(config["_score_weights"])

        for key in DEFAULT_TOGGLES:
            if key in config:
                self.toggles[key] = config[key]

    def get_control_ranges(self) -> dict[str, list[float | int]]:
        """Return enabled hierarchical control ranges."""
        ranges: dict[str, list[float | int]] = {}
        for control in self.hierarchical_controls:
            if control.get("enabled", False):
                ranges[control["key"]] = [control["min"], control["max"]]
        return ranges

    def get_enabled_controls(self) -> list[dict[str, Any]]:
        return [c for c in self.hierarchical_controls if c.get("enabled", False)]

    def get_disabled_controls(self) -> list[dict[str, Any]]:
        return [c for c in self.hierarchical_controls if not c.get("enabled", False)]

    def get_only_selectors_text(self) -> str:
        selectors = self.strategy.get("only_selectors", [])
        if not selectors:
            return ""
        return "\n".join(str(s) for s in selectors)

    def set_only_selectors_from_text(self, text: str) -> None:
        selectors = [line.strip() for line in text.splitlines() if line.strip()]
        self.strategy["only_selectors"] = selectors


_state: AppState | None = None


def get_state() -> AppState:
    global _state
    if _state is None:
        _state = AppState()
    return _state
