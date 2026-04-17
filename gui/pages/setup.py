"""Setup page — hierarchical experiment configuration UI."""

from __future__ import annotations

import json

from nicegui import ui

from ..state import get_state


def setup_page():
    state = get_state()

    ui.label("Hierarchical Experiment Setup").classes("text-2xl font-bold mb-2")
    ui.label(
        "Configure the bottom-up subcircuit experiment flow: routed leaf solving, "
        "parent composition, and visible top-level progression."
    ).classes("text-sm text-gray-400 mb-4")

    with ui.tabs().classes("w-full") as tabs:
        strategy_tab = ui.tab("Run Strategy", icon="play_circle")
        hierarchy_tab = ui.tab("Hierarchy Scope", icon="account_tree")
        visuals_tab = ui.tab("Visual Feedback", icon="image")
        presets_tab = ui.tab("Presets", icon="bookmark")

    with ui.tab_panels(tabs, value=strategy_tab).classes("w-full"):
        with ui.tab_panel(strategy_tab):
            _strategy_panel(state)

        with ui.tab_panel(hierarchy_tab):
            _hierarchy_panel(state)

        with ui.tab_panel(visuals_tab):
            _visuals_panel(state)

        with ui.tab_panel(presets_tab):
            _presets_panel(state)


def _strategy_panel(state):
    ui.label("Run Strategy").classes("text-lg font-bold mb-2")
    ui.label(
        "These settings control the outer experiment loop. Each round runs the "
        "hierarchical pipeline from routed leaves upward."
    ).classes("text-sm text-gray-400 mb-4")

    with ui.grid(columns=2).classes("w-full gap-4"):
        ui.number(
            "Experiment rounds",
            value=state.strategy.get("rounds", 10),
            min=1,
            max=1000,
            step=1,
            on_change=lambda e: state.strategy.update({"rounds": int(e.value)}),
        ).tooltip("How many full hierarchical attempts to run.")

        ui.number(
            "Leaf solve rounds per experiment round",
            value=state.strategy.get("leaf_rounds", 1),
            min=1,
            max=20,
            step=1,
            on_change=lambda e: state.strategy.update({"leaf_rounds": int(e.value)}),
        ).tooltip(
            "How many local solve attempts each leaf subcircuit gets inside one "
            "experiment round."
        )

        ui.number(
            "Workers (reserved)",
            value=state.strategy.get("workers", 1),
            min=1,
            max=64,
            step=1,
            on_change=lambda e: state.strategy.update({"workers": int(e.value)}),
        ).tooltip(
            "Currently reserved for compatibility. The hierarchical runner is "
            "executed in a single coordinated flow."
        )

        ui.number(
            "Base seed",
            value=state.strategy.get("seed", 0),
            min=0,
            step=1,
            on_change=lambda e: state.strategy.update({"seed": int(e.value)}),
        ).tooltip("Master seed for reproducible hierarchical runs.")

    ui.separator().classes("my-4")

    with ui.grid(columns=2).classes("w-full gap-4"):
        ui.input(
            "PCB file",
            value=state.strategy.get("pcb_file", "LLUPS.kicad_pcb"),
            on_change=lambda e: state.strategy.update({"pcb_file": e.value.strip()}),
        ).classes("w-full").tooltip("Top-level PCB used as the project anchor.")

        ui.input(
            "Schematic file",
            value=state.strategy.get("schematic_file", "LLUPS.kicad_sch"),
            on_change=lambda e: state.strategy.update(
                {"schematic_file": e.value.strip()}
            ),
        ).classes("w-full").tooltip("Top-level schematic for hierarchy parsing.")

        ui.input(
            "Parent selector",
            value=state.strategy.get("parent", "/"),
            on_change=lambda e: state.strategy.update(
                {"parent": e.value.strip() or "/"}
            ),
        ).classes("w-full").tooltip(
            "Parent node to compose and visualize. Use '/' for the top-level parent."
        )

        ui.input(
            "Only selectors (comma-separated)",
            value=", ".join(state.strategy.get("only", [])),
            on_change=lambda e: state.strategy.update({"only": _split_csv(e.value)}),
        ).classes("w-full").tooltip(
            "Optional leaf filters. Leave empty to solve the full leaf set."
        )

    ui.separator().classes("my-4")

    with ui.row().classes("w-full items-start gap-8"):
        with ui.column().classes("gap-2"):
            ui.switch(
                "Run visible top-level stage",
                value=not state.toggles.get("skip_visible", False),
                on_change=lambda e: state.toggles.update(
                    {"skip_visible": not bool(e.value)}
                ),
            ).tooltip(
                "When enabled, the experiment also runs the visible parent/top-level "
                "stage after leaf solving and composition."
            )

            ui.switch(
                "Render PNG previews",
                value=state.toggles.get("render_png", True),
                on_change=lambda e: state.toggles.update({"render_png": bool(e.value)}),
            ).tooltip(
                "Keep visual artifacts up to date so the monitor and analysis pages "
                "can show progression."
            )

        with ui.column().classes("gap-2"):
            ui.switch(
                "Keep per-round detail artifacts",
                value=state.toggles.get("save_round_details", True),
                on_change=lambda e: state.toggles.update(
                    {"save_round_details": bool(e.value)}
                ),
            ).tooltip("Preserve round JSON and related metadata for later inspection.")

            ui.switch(
                "Auto-import best hierarchical result as preset",
                value=state.toggles.get("import_best_as_preset", True),
                on_change=lambda e: state.toggles.update(
                    {"import_best_as_preset": bool(e.value)}
                ),
            ).tooltip(
                "Lets the GUI treat the best hierarchical run summary as a reusable preset."
            )


def _hierarchy_panel(state):
    ui.label("Hierarchy Scope").classes("text-lg font-bold mb-2")
    ui.label(
        "Define what part of the hierarchy the experiment should focus on and how "
        "the GUI should present progression."
    ).classes("text-sm text-gray-400 mb-4")

    with ui.card().classes("w-full p-4"):
        ui.label("Current hierarchical target").classes("text-md font-bold mb-2")
        with ui.grid(columns=2).classes("w-full gap-4"):
            ui.input(
                "Top-level parent selector",
                value=state.strategy.get("parent", "/"),
                on_change=lambda e: state.strategy.update(
                    {"parent": e.value.strip() or "/"}
                ),
            ).tooltip("The parent node that composition and visible assembly target.")

            ui.input(
                "Leaf filter selectors",
                value=", ".join(state.strategy.get("only", [])),
                on_change=lambda e: state.strategy.update(
                    {"only": _split_csv(e.value)}
                ),
            ).tooltip(
                "Optional list of leaf names, files, or instance paths to restrict solving."
            )

    ui.separator().classes("my-4")

    with ui.card().classes("w-full p-4"):
        ui.label("Hierarchy behavior").classes("text-md font-bold mb-2")
        with ui.column().classes("gap-3"):
            ui.switch(
                "Prefer full top-level progression in monitor",
                value=state.toggles.get("show_top_level_progress", True),
                on_change=lambda e: state.toggles.update(
                    {"show_top_level_progress": bool(e.value)}
                ),
            ).tooltip(
                "Bias the monitor toward showing parent/top-level readiness alongside leaf progress."
            )

            ui.switch(
                "Show accepted leaf artifacts prominently",
                value=state.toggles.get("show_leaf_artifacts", True),
                on_change=lambda e: state.toggles.update(
                    {"show_leaf_artifacts": bool(e.value)}
                ),
            ).tooltip(
                "Keep accepted routed leaf artifacts front-and-center in the GUI."
            )

            ui.switch(
                "Track composition outputs",
                value=state.toggles.get("track_composition_outputs", True),
                on_change=lambda e: state.toggles.update(
                    {"track_composition_outputs": bool(e.value)}
                ),
            ).tooltip(
                "Expose parent composition JSON and visible output artifacts in the GUI."
            )

    ui.separator().classes("my-4")

    with ui.card().classes("w-full p-4"):
        ui.label("Summary").classes("text-md font-bold mb-2")
        ui.markdown(
            f"""
- **Schematic:** `{state.strategy.get("schematic_file", "LLUPS.kicad_sch")}`
- **PCB:** `{state.strategy.get("pcb_file", "LLUPS.kicad_pcb")}`
- **Parent:** `{state.strategy.get("parent", "/")}`
- **Leaf filters:** `{", ".join(state.strategy.get("only", [])) or "all leaves"}`
- **Visible stage:** `{"enabled" if not state.toggles.get("skip_visible", False) else "disabled"}`
"""
        )


def _visuals_panel(state):
    ui.label("Visual Feedback").classes("text-lg font-bold mb-2")
    ui.label(
        "Tune how much visual feedback the experiment manager should expect and display."
    ).classes("text-sm text-gray-400 mb-4")

    with ui.row().classes("w-full gap-4 items-start"):
        with ui.card().classes("p-4 flex-1"):
            ui.label("Monitor emphasis").classes("text-md font-bold mb-2")
            ui.switch(
                "Highlight leaf progression",
                value=state.toggles.get("highlight_leaf_progress", True),
                on_change=lambda e: state.toggles.update(
                    {"highlight_leaf_progress": bool(e.value)}
                ),
            )
            ui.switch(
                "Highlight top-level progression",
                value=state.toggles.get("highlight_top_progress", True),
                on_change=lambda e: state.toggles.update(
                    {"highlight_top_progress": bool(e.value)}
                ),
            )
            ui.switch(
                "Show live status JSON",
                value=state.toggles.get("show_status_json", True),
                on_change=lambda e: state.toggles.update(
                    {"show_status_json": bool(e.value)}
                ),
            )

        with ui.card().classes("p-4 flex-1"):
            ui.label("Analysis emphasis").classes("text-md font-bold mb-2")
            ui.switch(
                "Enable progression viewer",
                value=state.toggles.get("enable_progression_viewer", True),
                on_change=lambda e: state.toggles.update(
                    {"enable_progression_viewer": bool(e.value)}
                ),
            )
            ui.switch(
                "Prefer accepted/kept frames",
                value=state.toggles.get("prefer_kept_frames", False),
                on_change=lambda e: state.toggles.update(
                    {"prefer_kept_frames": bool(e.value)}
                ),
            )
            ui.switch(
                "Show artifact metadata in viewer",
                value=state.toggles.get("show_frame_metadata", True),
                on_change=lambda e: state.toggles.update(
                    {"show_frame_metadata": bool(e.value)}
                ),
            )

    ui.separator().classes("my-4")

    with ui.card().classes("w-full p-4"):
        ui.label("Notes").classes("text-md font-bold mb-2")
        ui.label(
            "The hierarchical runner writes live status, per-round JSON, accepted "
            "leaf artifacts, and preview images. These toggles mainly control how "
            "the GUI presents that information."
        ).classes("text-sm text-gray-400")


def _presets_panel(state):
    ui.label("Presets").classes("text-lg font-bold mb-2")
    ui.label("Save and restore hierarchical experiment configurations.").classes(
        "text-sm text-gray-400 mb-4"
    )

    preset_name = ui.input("Preset name", value="").classes("w-64")
    preset_notes = ui.textarea("Notes", value="").classes("w-full").props("rows=2")

    with ui.row().classes("gap-2 mb-4"):

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
                ui.label("No presets saved yet").classes("text-gray-500 italic")
            return

        with presets_container:
            for preset in presets:
                with ui.card().classes("w-full p-3"):
                    with ui.row().classes("items-center gap-3"):
                        ui.label(preset.name).classes("font-bold")
                        ui.label(
                            preset.created_at.strftime("%Y-%m-%d %H:%M")
                            if preset.created_at
                            else ""
                        ).classes("text-xs text-gray-500")
                        ui.space()
                        ui.button(
                            "Load",
                            icon="download",
                            on_click=lambda _, pn=preset.name: _load(pn),
                        ).props("flat dense")
                        ui.button(
                            "Delete",
                            icon="delete",
                            on_click=lambda _, pn=preset.name: _delete(pn),
                            color="red",
                        ).props("flat dense")
                    if preset.notes:
                        ui.label(preset.notes).classes("text-xs text-gray-400 mt-1")
                    with ui.expansion("Preview config", value=False).classes("w-full"):
                        try:
                            cfg = state.db.load_preset(preset.name) or {}
                            ui.code(json.dumps(cfg, indent=2)).classes("w-full text-xs")
                        except Exception:
                            ui.label("Could not render preset preview").classes(
                                "text-xs text-red-400"
                            )

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


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
