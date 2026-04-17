"""Analysis page — hierarchical experiment statistics and progression."""

from __future__ import annotations

import json
from typing import Any

from nicegui import ui

from ..components.experiment_table import create_experiment_table
from ..components.param_sensitivity import (
    build_correlation_matrix,
    build_sensitivity_figure,
)
from ..components.progression_viewer import create_progression_viewer
from ..components.score_chart import (
    build_score_figure,
    build_stage_figure,
    build_subscore_figure,
)
from ..state import get_state


def analysis_page() -> None:
    state = get_state()

    ui.label("Experiment Analysis").classes("text-2xl font-bold mb-2")
    ui.label(
        "Review hierarchical experiment runs: routed leaf acceptance, parent "
        "composition, top-level readiness, and visual progression."
    ).classes("text-sm text-gray-400 mb-4")

    with ui.tabs().classes("w-full") as top_tabs:
        exp_tab = ui.tab("Experiment Data", icon="analytics")
        prog_tab = ui.tab("Board Progression", icon="slideshow")

    with ui.tab_panels(top_tabs, value=exp_tab).classes("w-full"):
        with ui.tab_panel(exp_tab):
            _experiment_data_panel(state)

        with ui.tab_panel(prog_tab):
            create_progression_viewer(state.experiments_dir)


def _experiment_data_panel(state) -> None:
    experiments = state.db.get_experiments()
    if not experiments:
        ui.label(
            "No experiments found. Import JSONL data or run a hierarchical experiment."
        ).classes("text-gray-500 italic")

        async def _import() -> None:
            from ..migrations.init_db import import_all_jsonl

            ids = import_all_jsonl(state.db, state.experiments_dir)
            if ids:
                ui.notify(f"Imported {len(ids)} experiments", type="positive")
                ui.navigate.reload()
            else:
                ui.notify("No JSONL files found to import", type="warning")

        ui.button("Import from .experiments/", icon="upload", on_click=_import)
        return

    def _build_exp_options() -> dict[int, str]:
        exps = state.db.get_experiments()
        return {
            exp.id: (
                f"#{exp.id} — {exp.name} "
                f"({exp.completed_rounds}r, best={exp.best_score:.1f})"
            )
            for exp in exps
        }

    exp_options = _build_exp_options()
    best_default = max(experiments, key=lambda e: e.completed_rounds or 0)
    selected_exp = {"id": best_default.id}

    content = ui.column().classes("w-full")

    def _load_experiment(exp_id: int) -> None:
        selected_exp["id"] = exp_id
        content.clear()
        rounds = state.db.get_round_dicts(exp_id)

        if not rounds:
            with content:
                ui.label("No round data for this experiment.").classes(
                    "text-gray-500 italic"
                )

                async def _sync() -> None:
                    from ..migrations.init_db import import_all_jsonl

                    ids = import_all_jsonl(state.db, state.experiments_dir)
                    if ids:
                        ui.notify(
                            f"Re-imported {len(ids)} experiments", type="positive"
                        )
                        ui.navigate.reload()
                    else:
                        ui.notify("No new data to import", type="info")

                ui.button("Sync from disk", icon="sync", on_click=_sync).classes("mt-2")
            return

        with content:
            _summary_cards(rounds)

            with ui.tabs().classes("w-full") as tabs:
                scores_tab = ui.tab("Scores", icon="show_chart")
                stages_tab = ui.tab("Stages", icon="timeline")
                table_tab = ui.tab("All Rounds", icon="table_chart")
                sensitivity_tab = ui.tab("Sensitivity", icon="tune")
                correlation_tab = ui.tab("Correlations", icon="grid_view")
                convergence_tab = ui.tab("Convergence", icon="trending_up")
                export_tab = ui.tab("Export", icon="download")

            with ui.tab_panels(tabs, value=scores_tab).classes("w-full"):
                with ui.tab_panel(scores_tab):
                    fig = build_score_figure(rounds, "Hierarchical Score vs Round")
                    ui.plotly(fig).classes("w-full h-96")

                    ui.separator()
                    fig2 = build_subscore_figure(
                        rounds, "Leaf / Parent / Top-Level Progress"
                    )
                    ui.plotly(fig2).classes("w-full h-80")

                with ui.tab_panel(stages_tab):
                    fig_stage = build_stage_figure(rounds, "Pipeline Stage Timeline")
                    ui.plotly(fig_stage).classes("w-full h-80")
                    _stage_summary(rounds)

                with ui.tab_panel(table_tab):
                    create_experiment_table(rounds)

                with ui.tab_panel(sensitivity_tab):
                    param_keys = _param_keys_from_rounds(rounds)
                    fig_sens = build_sensitivity_figure(rounds, param_keys)
                    if fig_sens:
                        ui.plotly(fig_sens).classes("w-full")
                    else:
                        ui.label(
                            "Not enough numeric variation for sensitivity analysis "
                            "(need at least a few rounds with numeric config deltas)."
                        ).classes("text-gray-500 italic")

                with ui.tab_panel(correlation_tab):
                    param_keys = _param_keys_from_rounds(rounds)
                    fig_corr = build_correlation_matrix(rounds, param_keys)
                    if fig_corr:
                        ui.plotly(fig_corr).classes("w-full")
                    else:
                        ui.label(
                            "Not enough data for correlation matrix "
                            "(or optional scientific dependencies are unavailable)."
                        ).classes("text-gray-500 italic")

                with ui.tab_panel(convergence_tab):
                    _convergence_panel(rounds)

                with ui.tab_panel(export_tab):
                    _export_panel(rounds, exp_id)

    with ui.row().classes("w-full items-center gap-4 mb-4"):
        exp_select = ui.select(
            options=exp_options,
            value=selected_exp["id"],
            label="Select Experiment",
            on_change=lambda e: _load_experiment(e.value),
        ).classes("w-96")

        async def _import() -> None:
            from ..migrations.init_db import import_all_jsonl

            ids = import_all_jsonl(state.db, state.experiments_dir)
            if ids:
                ui.notify(f"Imported {len(ids)} experiments", type="positive")
                ui.navigate.reload()
            else:
                ui.notify("No new JSONL files to import", type="info")

        ui.button("Import JSONL", icon="upload", on_click=_import).props("flat")

        def _refresh() -> None:
            new_options = _build_exp_options()
            exp_select.options = new_options
            exp_select.update()
            if selected_exp["id"]:
                _load_experiment(selected_exp["id"])

        ui.button("Refresh", icon="refresh", on_click=_refresh).props("flat")

    def _auto_refresh() -> None:
        if selected_exp["id"]:
            exp = state.db.get_experiment(selected_exp["id"])
            if exp and exp.status == "running":
                new_options = _build_exp_options()
                exp_select.options = new_options
                exp_select.update()
                _load_experiment(selected_exp["id"])

    ui.timer(10.0, _auto_refresh)

    if selected_exp["id"]:
        _load_experiment(selected_exp["id"])


def _summary_cards(rounds: list[dict[str, Any]]) -> None:
    best_round = max(rounds, key=lambda r: _as_float(r.get("score", 0)))
    total_kept = sum(1 for r in rounds if r.get("kept"))
    avg_score = (
        sum(_as_float(r.get("score", 0)) for r in rounds) / len(rounds)
        if rounds
        else 0.0
    )
    total_duration = sum(_as_float(r.get("duration_s", 0)) for r in rounds)

    best_leaf_accept = 0.0
    top_ready_count = 0
    for r in rounds:
        leaf_total = _as_int(r.get("leaf_total", 0))
        leaf_accepted = _as_int(r.get("leaf_accepted", 0))
        if leaf_total > 0:
            best_leaf_accept = max(best_leaf_accept, leaf_accepted / leaf_total)
        if r.get("top_level_ready"):
            top_ready_count += 1

    with ui.row().classes("w-full gap-4 mb-4"):
        _stat_card("Rounds", str(len(rounds)))
        _stat_card("Best Score", f"{_as_float(best_round.get('score', 0)):.2f}")
        _stat_card("Avg Score", f"{avg_score:.2f}")
        _stat_card("Kept", f"{total_kept} ({(total_kept / len(rounds)):.0%})")
        _stat_card("Best Leaf Acceptance", f"{best_leaf_accept:.0%}")
        _stat_card("Top-Level Ready", f"{top_ready_count}/{len(rounds)}")
        _stat_card("Total Time", f"{total_duration / 60:.0f}m")


def _stage_summary(rounds: list[dict[str, Any]]) -> None:
    stage_counts: dict[str, int] = {}
    for r in rounds:
        stage = str(r.get("latest_stage", r.get("stage", "done")) or "done")
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

    ui.label("Stage Summary").classes("text-lg font-bold mt-4 mb-2")
    if not stage_counts:
        ui.label("No stage data available").classes("text-gray-500 italic")
        return

    with ui.row().classes("gap-3 flex-wrap"):
        for stage, count in sorted(stage_counts.items()):
            color = _stage_badge_color(stage)
            ui.badge(f"{stage}: {count}", color=color)


def _convergence_panel(rounds: list[dict[str, Any]]) -> None:
    if len(rounds) < 2:
        ui.label("Need more rounds for convergence analysis").classes(
            "text-gray-500 italic"
        )
        return

    sorted_rounds = sorted(rounds, key=lambda r: _as_int(r.get("round_num", 0)))
    scores = [_as_float(r.get("score", 0)) for r in sorted_rounds]

    running_best: list[float] = []
    best = float("-inf")
    for score in scores:
        if score > best:
            best = score
        running_best.append(best)

    last_improvement = 0
    for i in range(1, len(running_best)):
        if running_best[i] > running_best[i - 1]:
            last_improvement = i

    useful_rounds = last_improvement + 1
    wasted = len(rounds) - useful_rounds
    initial = scores[0] if scores else 0.0
    improvement = best - initial if scores else 0.0

    top_ready = sum(1 for r in rounds if r.get("top_level_ready"))
    parent_ok = sum(1 for r in rounds if r.get("parent_composed"))

    ui.label("Convergence Summary").classes("text-lg font-bold mb-2")

    with ui.grid(columns=4).classes("w-full gap-4 mb-4"):
        _stat_card("Last Improvement", f"Round {last_improvement + 1}")
        _stat_card("Useful Rounds", f"{useful_rounds}/{len(rounds)}")
        _stat_card("Wasted Tail", str(wasted))
        _stat_card("Total Improvement", f"+{improvement:.2f}")

    ui.label("Hierarchy Outcome Rates").classes("text-md font-bold mt-3")
    with ui.row().classes("gap-4 flex-wrap"):
        ui.badge(
            f"Parent composed: {parent_ok}/{len(rounds)} ({parent_ok / len(rounds):.0%})",
            color="orange",
        )
        ui.badge(
            f"Top-level ready: {top_ready}/{len(rounds)} ({top_ready / len(rounds):.0%})",
            color="green",
        )

    stage_counts: dict[str, int] = {}
    for r in rounds:
        stage = str(r.get("latest_stage", r.get("stage", "done")) or "done")
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

    ui.label("Stage Distribution").classes("text-md font-bold mt-3")
    with ui.row().classes("gap-3 flex-wrap"):
        for stage, count in sorted(stage_counts.items()):
            ui.badge(f"{stage}: {count}", color=_stage_badge_color(stage))


def _export_panel(rounds: list[dict[str, Any]], exp_id: int) -> None:
    ui.label("Export experiment data").classes("text-md font-bold mb-2")

    def _download_csv() -> None:
        if not rounds:
            ui.notify("No data to export", type="warning")
            return

        keys = [
            "round_num",
            "score",
            "mode",
            "kept",
            "leaf_total",
            "leaf_accepted",
            "parent_composed",
            "top_level_ready",
            "accepted_trace_count",
            "accepted_via_count",
            "latest_stage",
            "duration_s",
        ]
        lines = [",".join(keys)]
        for r in rounds:
            lines.append(",".join(_csv_escape(r.get(k, "")) for k in keys))
        csv_data = "\n".join(lines)
        ui.download(csv_data.encode(), f"experiment_{exp_id}.csv")

    def _download_json() -> None:
        if not rounds:
            ui.notify("No data to export", type="warning")
            return
        data = json.dumps(rounds, indent=2)
        ui.download(data.encode(), f"experiment_{exp_id}.json")

    with ui.row().classes("gap-2"):
        ui.button("Download CSV", icon="download", on_click=_download_csv)
        ui.button("Download JSON", icon="download", on_click=_download_json)


def _param_keys_from_rounds(rounds: list[dict[str, Any]]) -> list[str]:
    keys: set[str] = set()
    for r in rounds:
        delta = r.get("config_delta", {})
        if isinstance(delta, dict):
            for key, value in delta.items():
                if isinstance(value, (int, float)):
                    keys.add(str(key))
    return sorted(keys)


def _stat_card(label: str, value: str) -> None:
    with ui.card().classes("p-3 flex-1 text-center"):
        ui.label(label).classes("text-xs text-gray-400")
        ui.label(value).classes("text-xl font-bold")


def _stage_badge_color(stage: str) -> str:
    stage = stage.lower()
    if stage == "solve_leafs":
        return "blue"
    if stage == "compose_parent":
        return "orange"
    if stage in {"visible_top_level", "done", "complete"}:
        return "green"
    if stage == "startup":
        return "gray"
    return "gray"


def _csv_escape(value: Any) -> str:
    text = str(value)
    if any(ch in text for ch in [",", '"', "\n"]):
        return '"' + text.replace('"', '""') + '"'
    return text


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
