"""Analysis page — hierarchical experiment statistics and progression."""

from __future__ import annotations

import json
from datetime import datetime
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
            _progression_panel(state)


def _experiment_data_panel(state) -> None:
    def _ensure_latest_running_experiment() -> None:
        active_id = state.active_experiment_id
        if not active_id:
            return

        exp = state.db.get_experiment(active_id)
        if exp is not None:
            return

        status = state.runner.read_status()
        total_rounds = int(
            status.get("total_rounds", 0) or state.strategy.get("rounds", 0) or 0
        )
        best_score = float(status.get("best_score", 0) or 0)
        completed_rounds = int(status.get("round", 0) or 0)
        phase = str(status.get("phase", "running") or "running")
        if phase not in {"running", "stopping", "done", "error"}:
            phase = "running"

        exp = state.db.create_experiment(
            name=f"Hierarchical Run {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            pcb_file=state.strategy.get("pcb_file", "LLUPS.kicad_pcb"),
            total_rounds=total_rounds,
            config=state.to_config_dict(),
        )
        state.active_experiment_id = exp.id
        state.db.update_experiment(
            exp.id,
            status=phase,
            best_score=best_score,
            completed_rounds=completed_rounds,
        )

    _ensure_latest_running_experiment()

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
    best_default = (
        next((exp for exp in experiments if exp.id == state.active_experiment_id), None)
        or experiments[0]
    )
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
            _ensure_latest_running_experiment()
            new_options = _build_exp_options()
            exp_select.options = new_options

            active_id = state.active_experiment_id
            if active_id and active_id in new_options:
                selected_exp["id"] = active_id
                exp_select.value = active_id
            elif selected_exp["id"] not in new_options and new_options:
                selected_exp["id"] = next(iter(new_options))
                exp_select.value = selected_exp["id"]

            exp_select.update()
            if selected_exp["id"]:
                _load_experiment(selected_exp["id"])

        ui.button("Refresh", icon="refresh", on_click=_refresh).props("flat")

    def _auto_refresh() -> None:
        _ensure_latest_running_experiment()
        new_options = _build_exp_options()
        exp_select.options = new_options

        active_id = state.active_experiment_id
        if active_id and active_id in new_options:
            if selected_exp["id"] != active_id:
                selected_exp["id"] = active_id
                exp_select.value = active_id
        elif selected_exp["id"] not in new_options and new_options:
            selected_exp["id"] = next(iter(new_options))
            exp_select.value = selected_exp["id"]

        exp_select.update()

        if selected_exp["id"]:
            exp = state.db.get_experiment(selected_exp["id"])
            if exp and exp.status in {"running", "stopping"}:
                _load_experiment(selected_exp["id"])

    ui.timer(10.0, _auto_refresh)

    if selected_exp["id"]:
        _load_experiment(selected_exp["id"])


def _progression_panel(state) -> None:
    ui.label("Hierarchical Progression").classes("text-xl font-bold mb-2")
    ui.label(
        "Browse accepted leaf artifacts and parent/top-level previews separately. "
        "This view is intended to make the bottom-up flow visually inspectable."
    ).classes("text-sm text-gray-400 mb-4")

    with ui.tabs().classes("w-full") as prog_tabs:
        viewer_tab = ui.tab("Timeline Viewer", icon="slideshow")
        leaf_tab = ui.tab("Accepted Leaf Gallery", icon="view_module")
        parent_tab = ui.tab("Parent / Top-Level Previews", icon="dashboard")

    with ui.tab_panels(prog_tabs, value=viewer_tab).classes("w-full"):
        with ui.tab_panel(viewer_tab):
            create_progression_viewer(state.experiments_dir)

        with ui.tab_panel(leaf_tab):
            _leaf_gallery_panel(state)

        with ui.tab_panel(parent_tab):
            _parent_preview_panel(state)


def _leaf_gallery_panel(state) -> None:
    sub_root = state.experiments_dir / "subcircuits"
    if not sub_root.exists():
        ui.label("No subcircuit artifacts found yet.").classes("text-gray-500 italic")
        return

    accepted: list[dict[str, Any]] = []

    def _open_preview_dialog(title: str, preview_path, subtitle: str = "") -> None:
        with (
            ui.dialog().props("maximized") as dialog,
            ui.card().classes("w-full h-full bg-slate-950 text-white p-4"),
        ):
            with ui.row().classes("w-full items-center gap-3 mb-3"):
                ui.label(title).classes("text-xl font-bold")
                if subtitle:
                    ui.label(subtitle).classes("text-sm text-gray-400 font-mono")
                ui.space()
                ui.button("Close", icon="close", on_click=dialog.close).props(
                    "flat color=white"
                )
            with ui.column().classes("w-full h-full items-center justify-center"):
                ui.image(str(preview_path)).classes(
                    "w-full h-[88vh] object-contain rounded border border-slate-700 bg-slate-900"
                )
        dialog.open()

    for artifact_dir in sorted(sub_root.iterdir()):
        if not artifact_dir.is_dir():
            continue

        solved_path = artifact_dir / "solved_layout.json"
        metadata_path = artifact_dir / "metadata.json"
        if not solved_path.exists():
            continue

        try:
            with open(solved_path, encoding="utf-8") as f:
                solved = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue

        if not isinstance(solved, dict):
            continue

        validation = solved.get("validation", {})
        if not isinstance(validation, dict) or validation.get("accepted") is not True:
            continue

        metadata: dict[str, Any] = {}
        if metadata_path.exists():
            try:
                with open(metadata_path, encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    metadata = loaded
            except (OSError, json.JSONDecodeError):
                metadata = {}

        renders_dir = artifact_dir / "renders"
        front_preview = next(
            (
                p
                for p in [
                    renders_dir / "routed_front_all.png",
                    renders_dir / "pre_route_front_all.png",
                ]
                if p.exists()
            ),
            None,
        )
        back_preview = next(
            (
                p
                for p in [
                    renders_dir / "routed_back_all.png",
                    renders_dir / "pre_route_back_all.png",
                ]
                if p.exists()
            ),
            None,
        )
        copper_preview = next(
            (
                p
                for p in [
                    renders_dir / "routed_copper_both.png",
                    renders_dir / "pre_route_copper_both.png",
                ]
                if p.exists()
            ),
            None,
        )

        accepted.append(
            {
                "sheet_name": solved.get("sheet_name")
                or metadata.get("sheet_name")
                or artifact_dir.name,
                "instance_path": solved.get("instance_path")
                or metadata.get("instance_path")
                or "",
                "trace_count": len(solved.get("traces", [])),
                "via_count": len(solved.get("vias", [])),
                "artifact_dir": artifact_dir.name,
                "front_preview": front_preview,
                "back_preview": back_preview,
                "copper_preview": copper_preview,
            }
        )

    if not accepted:
        ui.label("No accepted routed leaf artifacts yet.").classes(
            "text-gray-500 italic"
        )
        return

    ui.label(f"{len(accepted)} accepted routed leaf artifacts").classes(
        "text-sm text-gray-400 mb-3"
    )
    ui.label(
        "Each leaf now shows separate front, back, and combined-copper previews so "
        "silkscreen and back-layer routing are easier to inspect. Click any preview "
        "to open a larger inspection view."
    ).classes("text-sm text-gray-400 mb-4")

    with ui.grid(columns=1).classes("w-full gap-4"):
        for item in accepted:
            with ui.card().classes("w-full p-4"):
                with ui.row().classes("w-full items-center gap-2"):
                    ui.badge("LEAF", color="green")
                    ui.label(str(item["sheet_name"])).classes("font-bold text-lg")
                    ui.space()
                    ui.badge(f"{item['trace_count']} traces", color="cyan").classes(
                        "text-xs"
                    )
                    ui.badge(f"{item['via_count']} vias", color="amber").classes(
                        "text-xs"
                    )

                if item["instance_path"]:
                    ui.label(str(item["instance_path"])).classes(
                        "text-xs text-gray-400 font-mono"
                    )

                ui.label(str(item["artifact_dir"])).classes(
                    "text-xs text-gray-500 font-mono mb-2"
                )

                with ui.grid(columns=3).classes("w-full gap-3"):
                    for label, preview in [
                        ("Front (silkscreen + copper)", item["front_preview"]),
                        ("Back (silkscreen + copper)", item["back_preview"]),
                        ("Combined copper", item["copper_preview"]),
                    ]:
                        with ui.card().classes("w-full p-2 bg-slate-900"):
                            ui.label(label).classes(
                                "text-xs text-gray-300 font-medium mb-2"
                            )
                            if preview is not None:
                                ui.image(str(preview)).classes(
                                    "w-full h-[360px] object-contain rounded border border-slate-700 bg-slate-950 cursor-pointer"
                                ).on(
                                    "click",
                                    lambda _, p=preview, preview_label=label, item=item: (
                                        _open_preview_dialog(
                                            f"{item['sheet_name']} — {preview_label}",
                                            p,
                                            str(
                                                item["instance_path"]
                                                or item["artifact_dir"]
                                            ),
                                        )
                                    ),
                                )
                                ui.button(
                                    "Open full resolution",
                                    icon="open_in_full",
                                    on_click=lambda p=preview, preview_label=label, item=item: (
                                        _open_preview_dialog(
                                            f"{item['sheet_name']} — {preview_label}",
                                            p,
                                            str(
                                                item["instance_path"]
                                                or item["artifact_dir"]
                                            ),
                                        )
                                    ),
                                ).props("flat dense").classes("mt-2 text-cyan-300")
                            else:
                                ui.label("Preview not available").classes(
                                    "text-gray-500 italic text-sm"
                                )


def _parent_preview_panel(state) -> None:
    ui.label(
        "The parent previews below now come from the single unified parent pipeline. "
        "The stamped parent image is the source of truth for preserved routed child copper, "
        "and the routed parent image shows the result after parent interconnect routing. "
        "If the parent pipeline cannot produce valid geometry, it should fail explicitly "
        "instead of silently continuing to routing."
    ).classes("text-sm text-amber-300 mb-4")

    preview_sets: list[dict[str, Any]] = []

    def _open_preview_dialog(title: str, preview_path, subtitle: str = "") -> None:
        with (
            ui.dialog().props("maximized") as dialog,
            ui.card().classes("w-full h-full bg-slate-950 text-white p-4"),
        ):
            with ui.row().classes("w-full items-center gap-3 mb-3"):
                ui.label(title).classes("text-xl font-bold")
                if subtitle:
                    ui.label(subtitle).classes("text-sm text-gray-400 font-mono")
                ui.space()
                ui.button("Close", icon="close", on_click=dialog.close).props(
                    "flat color=white"
                )
            with ui.column().classes("w-full h-full items-center justify-center"):
                ui.image(str(preview_path)).classes(
                    "w-full h-[88vh] object-contain rounded border border-slate-700 bg-slate-900"
                )
        dialog.open()

    def _normalize_copper_accounting(payload: dict[str, Any]) -> dict[str, int]:
        return {
            "expected_preserved_child_trace_count": int(
                payload.get("expected_preserved_child_trace_count", 0) or 0
            ),
            "expected_preserved_child_via_count": int(
                payload.get("expected_preserved_child_via_count", 0) or 0
            ),
            "preserved_child_trace_count": int(
                payload.get("preserved_child_trace_count", 0) or 0
            ),
            "preserved_child_via_count": int(
                payload.get("preserved_child_via_count", 0) or 0
            ),
            "routed_total_trace_count": int(
                payload.get("routed_total_trace_count", 0) or 0
            ),
            "routed_total_via_count": int(
                payload.get("routed_total_via_count", 0) or 0
            ),
            "added_parent_trace_count": int(
                payload.get("added_parent_trace_count", 0) or 0
            ),
            "added_parent_via_count": int(
                payload.get("added_parent_via_count", 0) or 0
            ),
        }

    def _extract_copper_accounting(payload: dict[str, Any]) -> dict[str, int]:
        if not isinstance(payload, dict):
            return {}

        normalized = _normalize_copper_accounting(payload)
        if any(normalized.values()):
            return normalized

        routing_result = payload.get("routing_result", {})
        if isinstance(routing_result, dict):
            copper = routing_result.get("copper_accounting", {})
            if isinstance(copper, dict):
                normalized = _normalize_copper_accounting(copper)
                if any(normalized.values()):
                    return normalized

        hierarchy = payload.get("hierarchical_status", {})
        if isinstance(hierarchy, dict):
            copper = hierarchy.get("copper_accounting", {})
            if isinstance(copper, dict):
                normalized = _normalize_copper_accounting(copper)
                if any(normalized.values()):
                    return normalized

        composition = payload.get("composition", {})
        track_counts = payload.get("track_counts", {})
        if isinstance(composition, dict) and isinstance(track_counts, dict):
            preloaded = track_counts.get("preloaded", {})
            final = track_counts.get("final", {})
            if isinstance(preloaded, dict) and isinstance(final, dict):
                expected_traces = int(composition.get("trace_count", 0) or 0)
                expected_vias = int(composition.get("via_count", 0) or 0)
                preloaded_traces = int(preloaded.get("traces", 0) or 0)
                preloaded_vias = int(preloaded.get("vias", 0) or 0)
                final_traces = int(final.get("traces", 0) or 0)
                final_vias = int(final.get("vias", 0) or 0)
                return {
                    "expected_preserved_child_trace_count": expected_traces,
                    "expected_preserved_child_via_count": expected_vias,
                    "preserved_child_trace_count": min(
                        expected_traces, preloaded_traces
                    ),
                    "preserved_child_via_count": min(expected_vias, preloaded_vias),
                    "routed_total_trace_count": final_traces,
                    "routed_total_via_count": final_vias,
                    "added_parent_trace_count": max(0, final_traces - preloaded_traces),
                    "added_parent_via_count": max(0, final_vias - preloaded_vias),
                }

        return {}

    def _add_preview_set(base_dir, label: str) -> None:
        if not base_dir.exists():
            return

        preloaded = None
        routed = None
        metadata = None

        for candidate in [
            base_dir / "parent_preloaded.png",
            base_dir / "preloaded_png.png",
            base_dir / "preloaded.png",
            base_dir / "board_preloaded.png",
            base_dir / "parent_stamped.png",
            base_dir / "board.png",
            base_dir / "snapshot.png",
        ]:
            if candidate.exists():
                preloaded = candidate
                break

        for candidate in [
            base_dir / "parent_freerouted.png",
            base_dir / "routed_png.png",
            base_dir / "parent_routed.png",
            base_dir / "routed.png",
            base_dir / "board_routed.png",
        ]:
            if candidate.exists():
                routed = candidate
                break

        for candidate in [
            base_dir / "demo_metadata.json",
            base_dir / "debug.json",
            base_dir / "metadata.json",
            base_dir / "summary.json",
            base_dir / "parent_composition.json",
        ]:
            if candidate.exists():
                metadata = candidate
                break

        if preloaded is None and routed is None and metadata is None:
            return

        metadata_payload: dict[str, Any] = {}
        copper_accounting: dict[str, int] = {}
        if metadata is not None:
            try:
                with open(metadata, encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    metadata_payload = loaded
                    copper_accounting = _extract_copper_accounting(loaded)
            except (OSError, json.JSONDecodeError):
                metadata_payload = {}
                copper_accounting = {}

        preview_sets.append(
            {
                "label": label,
                "base_dir": base_dir,
                "preloaded": preloaded,
                "routed": routed,
                "metadata": metadata,
                "metadata_payload": metadata_payload,
                "copper_accounting": copper_accounting,
            }
        )

    _add_preview_set(
        state.experiments_dir / "hierarchical_parent_smoke",
        "Parent Smoke Test",
    )

    auto_root = state.experiments_dir / "hierarchical_autoexperiment"
    if auto_root.exists():
        for round_dir in sorted(auto_root.glob("round_*"), reverse=True):
            visible_dir = round_dir / "visible_parent"
            if visible_dir.exists():
                _add_preview_set(visible_dir, f"Autoexperiment {round_dir.name}")

    if not preview_sets:
        ui.label("No parent/top-level preview artifacts found yet.").classes(
            "text-gray-500 italic"
        )
        return

    with ui.column().classes("w-full gap-6"):
        for item in preview_sets:
            copper = item["copper_accounting"]
            with ui.card().classes("w-full p-4"):
                ui.label(str(item["label"])).classes("text-lg font-bold mb-1")
                ui.label(str(item["base_dir"])).classes(
                    "text-xs text-gray-500 font-mono mb-3"
                )
                ui.label(
                    "Compare the stamped parent against the routed parent from the unified "
                    "parent pipeline. The stamped image is the best visual proof that routed "
                    "child copper survived composition. The routed/final image is mainly for "
                    "checking what parent interconnect was added afterward."
                ).classes("text-sm text-gray-300 mb-4")

                if copper:
                    with ui.row().classes("w-full gap-2 mb-4 flex-wrap"):
                        ui.badge(
                            "Preserved child copper",
                            color="green",
                        )
                        ui.badge(
                            f"traces {copper.get('preserved_child_trace_count', 0)}/"
                            f"{copper.get('expected_preserved_child_trace_count', 0)}",
                            color="cyan",
                        )
                        ui.badge(
                            f"vias {copper.get('preserved_child_via_count', 0)}/"
                            f"{copper.get('expected_preserved_child_via_count', 0)}",
                            color="amber",
                        )
                        ui.badge(
                            f"added parent traces {copper.get('added_parent_trace_count', 0)}",
                            color="blue",
                        )
                        ui.badge(
                            f"added parent vias {copper.get('added_parent_via_count', 0)}",
                            color="purple",
                        )
                        ui.badge(
                            f"final traces {copper.get('routed_total_trace_count', 0)}",
                            color="teal",
                        )
                        ui.badge(
                            f"final vias {copper.get('routed_total_via_count', 0)}",
                            color="orange",
                        )

                with ui.grid(columns=2).classes("w-full gap-4"):
                    with ui.card().classes("w-full p-3 bg-slate-900"):
                        ui.label("Stamped parent").classes(
                            "text-sm font-bold text-gray-200 mb-2"
                        )
                        ui.label(
                            "Use this first when you want to verify preserved child copper, "
                            "module spacing, and the truth of the composed parent before parent "
                            "routing adds anything new. This image is generated by the same "
                            "single parent pipeline that performs stamping and routing."
                        ).classes("text-xs text-gray-400 mb-3")
                        if item["preloaded"] is not None:
                            ui.image(str(item["preloaded"])).classes(
                                "w-full h-[520px] object-contain rounded border border-slate-700 bg-slate-950 cursor-pointer"
                            ).on(
                                "click",
                                lambda _, p=item["preloaded"], label=item["label"]: (
                                    _open_preview_dialog(
                                        f"{label} — Stamped parent",
                                        p,
                                        str(item["base_dir"]),
                                    )
                                ),
                            )
                            ui.button(
                                "Open full resolution",
                                icon="open_in_full",
                                on_click=lambda p=item["preloaded"], label=item["label"]: (
                                    _open_preview_dialog(
                                        f"{label} — Stamped parent",
                                        p,
                                        str(item["base_dir"]),
                                    )
                                ),
                            ).props("flat dense").classes("mt-2 text-cyan-300")
                        else:
                            ui.label("No preloaded preview found").classes(
                                "text-gray-500 italic"
                            )

                    with ui.card().classes("w-full p-3 bg-slate-900"):
                        ui.label("Routed parent").classes(
                            "text-sm font-bold text-gray-200 mb-2"
                        )
                        ui.label(
                            "Use this to inspect newly added parent interconnect. If child copper "
                            "looks visually understated here, compare against the stamped view "
                            "and the copper-accounting badges above."
                        ).classes("text-xs text-gray-400 mb-3")
                        if item["routed"] is not None:
                            ui.image(str(item["routed"])).classes(
                                "w-full h-[520px] object-contain rounded border border-slate-700 bg-slate-950 cursor-pointer"
                            ).on(
                                "click",
                                lambda _, p=item["routed"], label=item["label"]: (
                                    _open_preview_dialog(
                                        f"{label} — Routed parent",
                                        p,
                                        str(item["base_dir"]),
                                    )
                                ),
                            )
                            ui.button(
                                "Open full resolution",
                                icon="open_in_full",
                                on_click=lambda p=item["routed"], label=item["label"]: (
                                    _open_preview_dialog(
                                        f"{label} — Routed parent",
                                        p,
                                        str(item["base_dir"]),
                                    )
                                ),
                            ).props("flat dense").classes("mt-2 text-cyan-300")
                        else:
                            ui.label("No routed preview found").classes(
                                "text-gray-500 italic"
                            )

                if item["metadata"] is not None:
                    with ui.expansion("Metadata", value=False).classes("w-full mt-4"):
                        try:
                            payload = item["metadata_payload"]
                            ui.code(json.dumps(payload, indent=2)).classes(
                                "w-full text-xs"
                            )
                        except (OSError, json.JSONDecodeError, TypeError):
                            ui.label("Could not load metadata").classes(
                                "text-red-400 text-sm"
                            )


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
