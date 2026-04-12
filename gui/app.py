"""NiceGUI application shell — main tabbed layout."""
from __future__ import annotations

from nicegui import app, ui

from .state import get_state
from .pages.setup import setup_page
from .pages.monitor import monitor_page
from .pages.analysis import analysis_page
from .pages.board import board_page


def _auto_import_on_startup():
    """Import existing JSONL experiments + best_config preset on first startup."""
    import json
    state = get_state()

    # Import JSONL experiments if DB is empty
    existing = state.db.get_experiments()
    if not existing:
        from .migrations.init_db import import_all_jsonl
        import_all_jsonl(state.db, state.experiments_dir)

    # Import best_config.json as a preset if available
    best_cfg_path = state.experiments_dir / "best_config.json"
    if best_cfg_path.exists():
        presets = state.db.get_presets()
        if not any(p.name == "Best (imported)" for p in presets):
            try:
                with open(best_cfg_path) as f:
                    data = json.load(f)
                config = data.get("config", data)
                state.db.save_preset("Best (imported)", config,
                                     f"Auto-imported from best_config.json "
                                     f"(score={data.get('score', '?')})")
            except (json.JSONDecodeError, OSError):
                pass


_auto_import_on_startup()


@ui.page("/")
def index():
    """Main page with tabbed layout."""
    state = get_state()

    ui.dark_mode(True)
    ui.add_head_html("""
    <style>
        .nicegui-content { max-width: 1400px; margin: 0 auto; }
        .q-tab-panel { padding: 16px 0 !important; }
    </style>
    """)

    with ui.header().classes("items-center justify-between px-6"):
        ui.label("LLUPS Experiment Manager").classes(
            "text-xl font-bold tracking-wide")
        with ui.row().classes("items-center gap-3"):
            ui.label(f"Project: {state.project_root.name}").classes(
                "text-sm text-gray-400")

    with ui.tabs().classes("w-full") as tabs:
        setup_tab = ui.tab("Setup", icon="tune")
        monitor_tab = ui.tab("Monitor", icon="monitor")
        analysis_tab = ui.tab("Analysis", icon="analytics")
        board_tab = ui.tab("Board", icon="memory")

    with ui.tab_panels(tabs, value=setup_tab).classes("w-full px-4"):
        with ui.tab_panel(setup_tab):
            setup_page()
        with ui.tab_panel(monitor_tab):
            monitor_page()
        with ui.tab_panel(analysis_tab):
            analysis_page()
        with ui.tab_panel(board_tab):
            board_page()
