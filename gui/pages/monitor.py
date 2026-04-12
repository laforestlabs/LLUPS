"""Monitor page — live experiment dashboard."""
from __future__ import annotations

import time
from pathlib import Path

from nicegui import ui

from ..state import get_state
from ..experiment_runner import ExperimentRunner
from ..components.score_chart import create_score_chart, build_score_figure


def monitor_page():
    state = get_state()
    runner = ExperimentRunner(state.project_root, state.scripts_dir,
                              state.experiments_dir)

    ui.label("Experiment Monitor").classes("text-2xl font-bold mb-4")

    # ── Controls ──
    with ui.row().classes("w-full items-center gap-4 mb-4"):
        start_btn = ui.button("Start Experiment", icon="play_arrow",
                              color="green")
        stop_btn = ui.button("Stop", icon="stop", color="red")
        stop_btn.set_visibility(False)

    # ── Status cards ──
    with ui.row().classes("w-full gap-4 mb-4"):
        with ui.card().classes("p-3 flex-1"):
            ui.label("Status").classes("text-xs text-gray-400")
            status_badge = ui.badge("IDLE", color="gray").classes("text-lg")

        with ui.card().classes("p-3 flex-1"):
            ui.label("Progress").classes("text-xs text-gray-400")
            progress_label = ui.label("0 / 0")
            progress_bar = ui.linear_progress(value=0).classes("w-full")

        with ui.card().classes("p-3 flex-1"):
            ui.label("Best Score").classes("text-xs text-gray-400")
            best_score_label = ui.label("—").classes("text-2xl font-bold text-green-400")

        with ui.card().classes("p-3 flex-1"):
            ui.label("Timing").classes("text-xs text-gray-400")
            timing_label = ui.label("Elapsed: — | ETA: —")

    with ui.row().classes("w-full gap-4 mb-4"):
        with ui.card().classes("p-3 flex-1"):
            ui.label("Workers").classes("text-xs text-gray-400")
            workers_label = ui.label("—")

        with ui.card().classes("p-3 flex-1"):
            ui.label("Latest").classes("text-xs text-gray-400")
            latest_label = ui.label("—")

        with ui.card().classes("p-3 flex-1"):
            ui.label("Kept Count").classes("text-xs text-gray-400")
            kept_label = ui.label("—")

        with ui.card().classes("p-3 flex-1"):
            ui.label("Health").classes("text-xs text-gray-400")
            health_label = ui.label("—")

    # ── Score chart ──
    chart_container = ui.column().classes("w-full")
    with chart_container:
        chart = create_score_chart([], "Live Score")

    # ── Recent rounds table ──
    with ui.expansion("Recent Rounds", icon="table_chart", value=False
                      ).classes("w-full"):
        rounds_container = ui.column().classes("w-full")

    # ── Board preview ──
    with ui.expansion("Best Board Preview", icon="image", value=False
                      ).classes("w-full"):
        board_container = ui.column().classes("w-full items-center")
        with board_container:
            ui.label("Start an experiment to see board previews").classes(
                "text-gray-500 italic")

    # ── State tracking ──
    live_rounds: list[dict] = []
    last_round_seen = {"value": 0}

    def _format_time(seconds: float) -> str:
        s = max(0, int(seconds))
        return f"{s // 60}m{s % 60:02d}s"

    def _update_status():
        """Poll run_status.json and update UI."""
        status = runner.read_status()
        phase = status.get("phase", "idle")

        # Status badge
        badge_colors = {
            "idle": "gray", "running": "blue",
            "done": "green", "error": "red",
        }
        status_badge.set_text(phase.upper())
        status_badge._props["color"] = badge_colors.get(phase, "gray")
        status_badge.update()

        # Progress
        rnd = status.get("round", 0)
        total = status.get("total_rounds", 0)
        pct = status.get("progress_percent", 0)
        progress_label.set_text(f"{rnd} / {total}")
        progress_bar.set_value(pct / 100 if pct else 0)

        # Best score
        best = status.get("best_score", 0)
        best_score_label.set_text(f"{best:.2f}" if best else "—")

        # Timing
        elapsed = status.get("elapsed_s", 0)
        eta = status.get("eta_s", 0)
        timing_label.set_text(
            f"Elapsed: {_format_time(elapsed)} | ETA: {_format_time(eta)}"
        )

        # Workers
        w = status.get("workers", {})
        workers_label.set_text(
            f"Total: {w.get('total', 0)} | "
            f"Active: {w.get('in_flight', 0)} | "
            f"Idle: {w.get('idle', 0)}"
        )

        # Latest
        latest = status.get("latest_score")
        marker = status.get("latest_marker", "")
        latest_label.set_text(
            f"{latest:.2f} ({marker})" if latest else "—"
        )

        # Kept
        kept_label.set_text(str(status.get("kept_count", 0)))

        # Health
        stuck = status.get("maybe_stuck", False)
        if stuck:
            health_label.set_text("⚠ POSSIBLY STUCK")
            health_label.classes(replace="text-red-400")
        elif phase == "running":
            health_label.set_text("✓ Active")
            health_label.classes(replace="text-green-400")
        else:
            health_label.set_text("—")
            health_label.classes(replace="")

        # Button visibility
        is_running = phase == "running" or runner.is_running
        start_btn.set_visibility(not is_running)
        stop_btn.set_visibility(is_running)

        # New rounds
        new_rounds = runner.read_latest_rounds(last_round_seen["value"])
        if new_rounds:
            live_rounds.extend(new_rounds)
            last_round_seen["value"] = max(
                r.get("round_num", 0) for r in new_rounds
            )
            # Update chart
            chart_container.clear()
            with chart_container:
                create_score_chart(live_rounds, "Live Score")

        # Board preview
        best_png = state.experiments_dir / "best_preview.png"
        if best_png.exists():
            board_container.clear()
            with board_container:
                ui.image(str(best_png)).classes("max-w-lg")

    # Start timer for live updates
    timer = ui.timer(2.0, _update_status)

    async def _start():
        try:
            pid = runner.start(
                pcb_file=state.strategy["pcb_file"],
                rounds=state.strategy["rounds"],
                workers=state.strategy["workers"],
                plateau=state.strategy["plateau_threshold"],
                seed=state.strategy.get("seed"),
                param_ranges=state.get_param_ranges(),
                score_weights=state.score_weights,
            )
            # Create experiment record
            exp = state.db.create_experiment(
                name=f"Run {time.strftime('%Y-%m-%d %H:%M')}",
                pcb_file=state.strategy["pcb_file"],
                total_rounds=state.strategy["rounds"],
                config=state.to_config_dict(),
            )
            state.active_experiment_id = exp.id
            state.db.update_experiment(exp.id, status="running")

            ui.notify(f"Started experiment (PID {pid})", type="positive")
            live_rounds.clear()
            last_round_seen["value"] = 0
        except Exception as e:
            ui.notify(f"Failed to start: {e}", type="negative")

    def _stop():
        runner.stop()
        ui.notify("Stop requested — experiment will finish current round",
                  type="info")
        if state.active_experiment_id:
            state.db.update_experiment(state.active_experiment_id,
                                       status="stopping")

    start_btn.on_click(_start)
    stop_btn.on_click(_stop)
