"""Analysis page — post-experiment statistics and comparison."""
from __future__ import annotations

import json
from io import StringIO

from nicegui import ui

from ..state import get_state
from ..components.score_chart import build_score_figure, build_subscore_figure
from ..components.experiment_table import create_experiment_table
from ..components.param_sensitivity import (
    build_sensitivity_figure,
    build_correlation_matrix,
)


def analysis_page():
    state = get_state()

    ui.label("Experiment Analysis").classes("text-2xl font-bold mb-4")

    # ── Experiment selector ──
    experiments = state.db.get_experiments()
    if not experiments:
        ui.label("No experiments found. Import JSONL data or run an experiment."
                 ).classes("text-gray-500 italic")

        async def _import():
            from ..migrations.init_db import import_all_jsonl
            ids = import_all_jsonl(state.db, state.experiments_dir)
            if ids:
                ui.notify(f"Imported {len(ids)} experiments", type="positive")
                ui.navigate.reload()
            else:
                ui.notify("No JSONL files found to import", type="warning")

        ui.button("Import from .experiments/", icon="upload",
                  on_click=_import)
        return

    exp_options = {
        exp.id: f"#{exp.id} — {exp.name} ({exp.completed_rounds}r, "
                f"best={exp.best_score:.1f})"
        for exp in experiments
    }

    selected_exp = {"id": experiments[0].id if experiments else None}

    # Content containers
    content = ui.column().classes("w-full")

    def _load_experiment(exp_id: int):
        selected_exp["id"] = exp_id
        content.clear()
        rounds = state.db.get_round_dicts(exp_id)

        if not rounds:
            with content:
                ui.label("No round data for this experiment").classes(
                    "text-gray-500 italic")
            return

        with content:
            # ── Summary cards ──
            best_round = max(rounds, key=lambda r: r.get("score", 0))
            total_kept = sum(1 for r in rounds if r.get("kept"))
            avg_score = sum(r.get("score", 0) for r in rounds) / len(rounds)
            total_duration = sum(r.get("duration_s", 0) or 0 for r in rounds)

            with ui.row().classes("w-full gap-4 mb-4"):
                _stat_card("Rounds", str(len(rounds)))
                _stat_card("Best Score", f"{best_round['score']:.2f}")
                _stat_card("Avg Score", f"{avg_score:.2f}")
                _stat_card("Kept", f"{total_kept} ({total_kept/len(rounds):.0%})")
                _stat_card("Total Time",
                           f"{total_duration/60:.0f}m")

            # ── Sub-tabs ──
            with ui.tabs().classes("w-full") as tabs:
                scores_tab = ui.tab("Scores")
                table_tab = ui.tab("All Rounds")
                sensitivity_tab = ui.tab("Parameter Sensitivity")
                correlation_tab = ui.tab("Correlations")
                convergence_tab = ui.tab("Convergence")
                export_tab = ui.tab("Export")

            with ui.tab_panels(tabs, value=scores_tab).classes("w-full"):
                # ── Scores ──
                with ui.tab_panel(scores_tab):
                    fig = build_score_figure(rounds, "Score vs Round")
                    ui.plotly(fig).classes("w-full h-96")

                    ui.separator()
                    fig2 = build_subscore_figure(rounds, "Sub-score Breakdown")
                    ui.plotly(fig2).classes("w-full h-80")

                # ── All Rounds ──
                with ui.tab_panel(table_tab):
                    create_experiment_table(rounds)

                # ── Parameter Sensitivity ──
                with ui.tab_panel(sensitivity_tab):
                    param_keys = [d["key"] for d in state.search_dimensions]
                    fig_sens = build_sensitivity_figure(rounds, param_keys)
                    if fig_sens:
                        ui.plotly(fig_sens).classes("w-full")
                    else:
                        ui.label("Not enough data for sensitivity analysis "
                                 "(need ≥5 rounds)"
                                 ).classes("text-gray-500 italic")

                # ── Correlations ──
                with ui.tab_panel(correlation_tab):
                    fig_corr = build_correlation_matrix(rounds, param_keys)
                    if fig_corr:
                        ui.plotly(fig_corr).classes("w-full")
                    else:
                        ui.label("Not enough data for correlation matrix "
                                 "(need ≥10 rounds with scipy installed)"
                                 ).classes("text-gray-500 italic")

                # ── Convergence ──
                with ui.tab_panel(convergence_tab):
                    _convergence_panel(rounds)

                # ── Export ──
                with ui.tab_panel(export_tab):
                    _export_panel(rounds, exp_id)

    with ui.row().classes("w-full items-center gap-4 mb-4"):
        ui.select(
            options=exp_options,
            value=selected_exp["id"],
            label="Select Experiment",
            on_change=lambda e: _load_experiment(e.value),
        ).classes("w-96")

        async def _import():
            from ..migrations.init_db import import_all_jsonl
            ids = import_all_jsonl(state.db, state.experiments_dir)
            if ids:
                ui.notify(f"Imported {len(ids)} experiments", type="positive")
                ui.navigate.reload()
            else:
                ui.notify("No new JSONL files to import", type="info")

        ui.button("Import JSONL", icon="upload", on_click=_import
                  ).props("flat")

    # Load initial
    if selected_exp["id"]:
        _load_experiment(selected_exp["id"])


def _stat_card(label: str, value: str):
    with ui.card().classes("p-3 flex-1 text-center"):
        ui.label(label).classes("text-xs text-gray-400")
        ui.label(value).classes("text-xl font-bold")


def _convergence_panel(rounds: list[dict]):
    """Convergence diagnostics — plateau detection, improvement rate."""
    if len(rounds) < 3:
        ui.label("Need more rounds for convergence analysis").classes(
            "text-gray-500 italic")
        return

    # Running best
    scores = [r.get("score", 0) for r in rounds]
    running_best = []
    best = -1e9
    for s in scores:
        if s > best:
            best = s
        running_best.append(best)

    # Detect plateau: last round where best improved
    last_improvement = 0
    for i in range(1, len(running_best)):
        if running_best[i] > running_best[i - 1]:
            last_improvement = i

    useful_rounds = last_improvement + 1
    wasted = len(rounds) - useful_rounds

    # Improvement rate: best - initial score
    initial = scores[0] if scores else 0
    improvement = best - initial

    # Mode distribution
    modes = {}
    for r in rounds:
        m = r.get("mode", "unknown")
        modes[m] = modes.get(m, 0) + 1

    ui.label("Convergence Summary").classes("text-lg font-bold mb-2")

    with ui.grid(columns=3).classes("w-full gap-4 mb-4"):
        _stat_card("Last Improvement", f"Round {last_improvement + 1}")
        _stat_card("Useful Rounds",
                   f"{useful_rounds}/{len(rounds)} "
                   f"({useful_rounds/len(rounds):.0%})")
        _stat_card("Total Improvement", f"+{improvement:.2f}")

    # Mode distribution
    ui.label("Mutation Mode Distribution").classes("text-md font-bold mt-3")
    with ui.row().classes("gap-4"):
        for mode, count in sorted(modes.items()):
            pct = count / len(rounds) * 100
            colors = {"minor": "blue", "major": "red",
                      "explore": "gray", "elite": "yellow"}
            ui.badge(f"{mode}: {count} ({pct:.0f}%)",
                     color=colors.get(mode, "gray"))

    # Per-mode kept rate
    ui.label("Kept Rate by Mode").classes("text-md font-bold mt-3")
    for mode in sorted(modes):
        mode_rounds = [r for r in rounds if r.get("mode") == mode]
        kept = sum(1 for r in mode_rounds if r.get("kept"))
        total = len(mode_rounds)
        pct = kept / total * 100 if total else 0
        with ui.row().classes("items-center gap-2"):
            ui.label(f"{mode}:").classes("w-16")
            ui.linear_progress(value=pct / 100).classes("w-48")
            ui.label(f"{kept}/{total} ({pct:.0f}%)")


def _export_panel(rounds: list[dict], exp_id: int):
    """Export experiment data as CSV or JSON."""
    ui.label("Export experiment data").classes("text-md font-bold mb-2")

    def _download_csv():
        if not rounds:
            ui.notify("No data to export", type="warning")
            return
        keys = ["round_num", "score", "mode", "kept", "placement_score",
                "route_completion", "via_score", "drc_shorts", "drc_total",
                "duration_s"]
        lines = [",".join(keys)]
        for r in rounds:
            lines.append(",".join(str(r.get(k, "")) for k in keys))
        csv_data = "\n".join(lines)
        ui.download(csv_data.encode(), f"experiment_{exp_id}.csv")

    def _download_json():
        if not rounds:
            ui.notify("No data to export", type="warning")
            return
        data = json.dumps(rounds, indent=2)
        ui.download(data.encode(), f"experiment_{exp_id}.json")

    with ui.row().classes("gap-2"):
        ui.button("Download CSV", icon="download", on_click=_download_csv)
        ui.button("Download JSON", icon="download", on_click=_download_json)
