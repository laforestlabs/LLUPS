"""Setup page — configure search dimensions, strategy, score weights, presets."""
from __future__ import annotations

import json

from nicegui import ui

from ..state import get_state
from ..components.dimension_control import DimensionControl


def setup_page():
    state = get_state()

    ui.label("Experiment Setup").classes("text-2xl font-bold mb-4")

    with ui.tabs().classes("w-full") as tabs:
        dim_tab = ui.tab("Search Dimensions")
        strategy_tab = ui.tab("Strategy")
        weights_tab = ui.tab("Score Weights")
        toggles_tab = ui.tab("Feature Toggles")
        presets_tab = ui.tab("Presets")

    with ui.tab_panels(tabs, value=dim_tab).classes("w-full"):
        # ── Search Dimensions ──
        with ui.tab_panel(dim_tab):
            ui.label("Enable/disable which parameters the optimizer varies. "
                     "Disabled parameters use their fixed value."
                     ).classes("text-sm text-gray-400 mb-3")

            # Group by category
            groups: dict[str, list] = {}
            for dim in state.search_dimensions:
                g = dim.get("group", "Other")
                groups.setdefault(g, []).append(dim)

            for group_name, dims in groups.items():
                with ui.expansion(group_name, value=True).classes("w-full"):
                    for dim in dims:
                        DimensionControl(dim)

        # ── Strategy ──
        with ui.tab_panel(strategy_tab):
            ui.label("Experiment run strategy").classes(
                "text-sm text-gray-400 mb-3")
            with ui.grid(columns=2).classes("w-full gap-4"):
                ui.number("Rounds", value=state.strategy["rounds"],
                          min=1, max=10000, step=1,
                          on_change=lambda e: state.strategy.update(
                              {"rounds": int(e.value)}
                          ))
                ui.number("Workers (0=auto)", value=state.strategy["workers"],
                          min=0, max=64, step=1,
                          on_change=lambda e: state.strategy.update(
                              {"workers": int(e.value)}
                          ))
                ui.number("Plateau threshold",
                          value=state.strategy["plateau_threshold"],
                          min=1, max=20, step=1,
                          on_change=lambda e: state.strategy.update(
                              {"plateau_threshold": int(e.value)}
                          ))
                ui.number("Base seed", value=state.strategy["seed"],
                          min=0, step=1,
                          on_change=lambda e: state.strategy.update(
                              {"seed": int(e.value)}
                          ))
            ui.separator()
            ui.label("PCB File").classes("text-sm text-gray-400 mt-2")
            ui.input("PCB file", value=state.strategy["pcb_file"],
                     on_change=lambda e: state.strategy.update(
                         {"pcb_file": e.value}
                     )).classes("w-full")

        # ── Score Weights ──
        with ui.tab_panel(weights_tab):
            _score_weights_panel(state)

        # ── Feature Toggles ──
        with ui.tab_panel(toggles_tab):
            ui.label("Feature toggles for search space expansion"
                     ).classes("text-sm text-gray-400 mb-3")

            ui.switch("Unlock all footprints",
                      value=state.toggles["unlock_all_footprints"],
                      on_change=lambda e: state.toggles.update(
                          {"unlock_all_footprints": e.value}
                      )).tooltip(
                "When enabled, batteries and connectors are not hard-locked. "
                "They prefer edges via scoring but can be moved freely."
            )

            ui.switch("Enable board size search",
                      value=state.toggles["enable_board_size_search"],
                      on_change=lambda e: _toggle_board_size(state, e.value),
                      ).tooltip(
                "Add board width and height as search dimensions. "
                "Uses discrete 5mm steps with dynamic minimum bounds "
                "computed from total component area."
            )

        # ── Presets ──
        with ui.tab_panel(presets_tab):
            _presets_panel(state)


def _toggle_board_size(state, enabled: bool):
    state.toggles["enable_board_size_search"] = enabled
    for dim in state.search_dimensions:
        if dim["key"] in ("board_width_mm", "board_height_mm"):
            dim["enabled"] = enabled


def _score_weights_panel(state):
    ui.label("Relative importance of each score component. "
             "Values are auto-normalized to sum to 1.0."
             ).classes("text-sm text-gray-400 mb-3")

    weight_labels = {
        "placement": "Placement Quality",
        "route_completion": "Route Completion",
        "via_penalty": "Via Penalty",
        "containment": "Board Containment",
        "drc": "DRC Score",
        "area": "Board Area (smaller = better)",
    }

    norm_label = ui.label("").classes("text-sm text-green-400 mt-2")
    sliders: dict[str, ui.slider] = {}

    def _update_norm():
        total = sum(state.score_weights.values())
        if total > 0:
            parts = ", ".join(
                f"{k}={v / total:.0%}" for k, v in state.score_weights.items()
            )
            norm_label.set_text(f"Normalized: {parts}")
        else:
            norm_label.set_text("Warning: all weights are zero")

    for key, label in weight_labels.items():
        with ui.row().classes("w-full items-center gap-2"):
            ui.label(label).classes("w-40 text-sm")
            sl = ui.slider(
                min=0, max=1, step=0.05,
                value=state.score_weights[key],
                on_change=lambda e, k=key: (
                    state.score_weights.update({k: e.value}),
                    _update_norm()
                ),
            ).classes("flex-grow")
            ui.label().bind_text_from(sl, "value",
                                      backward=lambda v: f"{v:.2f}")
            sliders[key] = sl

    _update_norm()


def _presets_panel(state):
    ui.label("Save and load experiment configurations"
             ).classes("text-sm text-gray-400 mb-3")

    preset_name = ui.input("Preset name", value="").classes("w-64")
    preset_notes = ui.textarea("Notes", value="").classes("w-full").props(
        "rows=2")

    with ui.row().classes("gap-2"):
        async def _save():
            name = preset_name.value.strip()
            if not name:
                ui.notify("Enter a preset name", type="warning")
                return
            config = state.to_config_dict()
            state.db.save_preset(name, config, preset_notes.value)
            ui.notify(f"Saved preset '{name}'", type="positive")
            _refresh_presets()

        ui.button("Save Current Config", on_click=_save, icon="save")

    ui.separator()
    ui.label("Saved Presets").classes("text-lg font-bold mt-3")

    presets_container = ui.column().classes("w-full gap-2")

    def _refresh_presets():
        presets_container.clear()
        presets = state.db.get_presets()
        if not presets:
            with presets_container:
                ui.label("No presets saved yet").classes(
                    "text-gray-500 italic")
            return
        with presets_container:
            for p in presets:
                with ui.card().classes("w-full p-2"):
                    with ui.row().classes("items-center gap-3"):
                        ui.label(p.name).classes("font-bold")
                        ui.label(
                            p.created_at.strftime("%Y-%m-%d %H:%M")
                            if p.created_at else ""
                        ).classes("text-xs text-gray-500")
                        ui.space()
                        ui.button("Load", icon="download",
                                  on_click=lambda _, pn=p.name: _load(pn)
                                  ).props("flat dense")
                        ui.button("Delete", icon="delete",
                                  on_click=lambda _, pn=p.name: _delete(pn),
                                  color="red"
                                  ).props("flat dense")
                    if p.notes:
                        ui.label(p.notes).classes(
                            "text-xs text-gray-400 mt-1")

    def _load(name: str):
        config = state.db.load_preset(name)
        if config:
            state.load_from_config(config)
            ui.notify(f"Loaded preset '{name}'", type="positive")
            ui.navigate.reload()
        else:
            ui.notify(f"Preset '{name}' not found", type="warning")

    def _delete(name: str):
        state.db.delete_preset(name)
        ui.notify(f"Deleted preset '{name}'")
        _refresh_presets()

    _refresh_presets()
