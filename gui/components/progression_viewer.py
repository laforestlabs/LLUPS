"""Hierarchical progression viewer for subcircuit and top-level experiment frames."""

from __future__ import annotations

import glob
import json
from pathlib import Path
from typing import Any

from nicegui import ui


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _discover_frame_sets(experiments_dir: Path) -> list[dict[str, Any]]:
    """Discover available frame collections.

    Supported layouts:
    - legacy: .experiments/frames/frame_*.png
    - hierarchical:
      - .experiments/frames/leaves/frame_*.png
      - .experiments/frames/top/frame_*.png
      - .experiments/frames/<stage>/frame_*.png
    """
    frames_root = experiments_dir.resolve() / "frames"
    if not frames_root.is_dir():
        return []

    frame_sets: list[dict[str, Any]] = []

    legacy_frames = sorted(glob.glob(str(frames_root / "frame_*.png")))
    if legacy_frames:
        frame_sets.append(
            {
                "key": "legacy",
                "label": "Whole Run",
                "frames_dir": frames_root,
                "frame_paths": legacy_frames,
            }
        )

    for child in sorted(frames_root.iterdir()):
        if not child.is_dir():
            continue
        frame_paths = sorted(glob.glob(str(child / "frame_*.png")))
        if not frame_paths:
            continue
        label = child.name.replace("_", " ").replace("-", " ").title()
        frame_sets.append(
            {
                "key": child.name,
                "label": label,
                "frames_dir": child,
                "frame_paths": frame_paths,
            }
        )

    return frame_sets


def _load_round_lookup(experiments_dir: Path) -> dict[int, dict[str, Any]]:
    """Load round metadata from round JSON files and JSONL fallback."""
    rounds_dir = experiments_dir.resolve() / "rounds"
    round_meta: dict[int, dict[str, Any]] = {}

    if rounds_dir.is_dir():
        for rpath in sorted(rounds_dir.glob("round_*.json")):
            data = _safe_load_json(rpath)
            if not data:
                continue
            rnum = _coerce_int(data.get("round", data.get("round_num", 0)))
            round_meta[rnum] = {
                "kept": bool(data.get("kept", False)),
                "score": _coerce_float(data.get("score", 0.0)),
                "mode": str(data.get("mode", "")),
                "stage": str(data.get("stage", "")),
                "sheet_name": str(data.get("sheet_name", "")),
                "instance_path": str(data.get("instance_path", "")),
                "accepted": data.get("accepted"),
                "artifact_dir": str(data.get("artifact_dir", "")),
            }

    if round_meta:
        return round_meta

    jsonl_path = experiments_dir / "experiments.jsonl"
    if not jsonl_path.exists():
        return round_meta

    try:
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict):
                    continue
                rnum = _coerce_int(data.get("round_num", data.get("round", 0)))
                round_meta[rnum] = {
                    "kept": bool(data.get("kept", False)),
                    "score": _coerce_float(data.get("score", 0.0)),
                    "mode": str(data.get("mode", "")),
                    "stage": str(data.get("stage", "")),
                    "sheet_name": str(data.get("sheet_name", "")),
                    "instance_path": str(data.get("instance_path", "")),
                    "accepted": data.get("accepted"),
                    "artifact_dir": str(data.get("artifact_dir", "")),
                }
    except OSError:
        pass

    return round_meta


def _load_status_metadata(experiments_dir: Path) -> dict[str, Any]:
    """Load hierarchical status metadata if present."""
    candidates = [
        experiments_dir / "run_status.json",
        experiments_dir / "hierarchical_status.json",
    ]
    for path in candidates:
        data = _safe_load_json(path)
        if data:
            return data
    return {}


def _frame_sidecar_metadata(frame_path: Path) -> dict[str, Any]:
    """Load optional per-frame sidecar metadata.

    Supports:
    - frame_0001.json next to frame_0001.png
    """
    sidecar = frame_path.with_suffix(".json")
    return _safe_load_json(sidecar) or {}


def _build_frame_record(
    frame_path: Path,
    round_lookup: dict[int, dict[str, Any]],
    default_stage: str,
) -> dict[str, Any]:
    stem = frame_path.stem
    try:
        round_num = int(stem.replace("frame_", ""))
    except ValueError:
        round_num = 0

    round_meta = round_lookup.get(round_num, {})
    sidecar = _frame_sidecar_metadata(frame_path)

    stage = str(
        sidecar.get("stage")
        or round_meta.get("stage")
        or default_stage
        or ("baseline" if round_num == 0 else "")
    )
    mode = str(
        sidecar.get("mode")
        or round_meta.get("mode")
        or ("baseline" if round_num == 0 else "")
    )
    score = _coerce_float(
        sidecar.get("score", round_meta.get("score", 0.0)),
        0.0,
    )

    accepted_value = sidecar.get("accepted", round_meta.get("accepted"))
    kept = bool(
        sidecar.get(
            "kept",
            round_meta.get(
                "kept", accepted_value if accepted_value is not None else round_num == 0
            ),
        )
    )

    return {
        "round_num": round_num,
        "kept": kept,
        "score": score,
        "mode": mode,
        "stage": stage,
        "sheet_name": str(
            sidecar.get("sheet_name") or round_meta.get("sheet_name") or ""
        ),
        "instance_path": str(
            sidecar.get("instance_path") or round_meta.get("instance_path") or ""
        ),
        "accepted": accepted_value,
        "artifact_dir": str(
            sidecar.get("artifact_dir") or round_meta.get("artifact_dir") or ""
        ),
        "frame_path": str(frame_path),
    }


def _load_hierarchical_frames(experiments_dir: Path) -> list[dict[str, Any]]:
    """Load all available frame groups with metadata."""
    round_lookup = _load_round_lookup(experiments_dir)
    frame_sets = _discover_frame_sets(experiments_dir)

    result: list[dict[str, Any]] = []
    for frame_set in frame_sets:
        key = str(frame_set["key"])
        label = str(frame_set["label"])
        frames_dir = Path(frame_set["frames_dir"])
        default_stage = key
        frames = [
            _build_frame_record(Path(path), round_lookup, default_stage)
            for path in frame_set["frame_paths"]
        ]
        frames.sort(key=lambda f: f["round_num"])
        result.append(
            {
                "key": key,
                "label": label,
                "frames_dir": str(frames_dir),
                "frames": frames,
            }
        )

    return result


def create_progression_viewer(experiments_dir: Path):
    """Build the hierarchical PCB progression viewer with playback controls."""
    frame_groups = _load_hierarchical_frames(experiments_dir)
    status_meta = _load_status_metadata(experiments_dir)

    if not frame_groups:
        ui.label("No frame images found in .experiments/frames/").classes(
            "text-gray-500 italic"
        )
        ui.label(
            "Run a hierarchical experiment first — leaf and top-level frames "
            "will appear automatically as the pipeline progresses."
        ).classes("text-gray-500 text-sm")
        return

    state = {
        "group_key": frame_groups[0]["key"],
        "mode": "all",  # all | kept
        "index": 0,
        "playing": False,
        "speed_fps": 4,
    }

    group_lookup = {g["key"]: g for g in frame_groups}

    def _current_group() -> dict[str, Any]:
        return group_lookup.get(state["group_key"], frame_groups[0])

    def _filtered_frames() -> list[dict[str, Any]]:
        frames = list(_current_group()["frames"])
        if state["mode"] == "kept":
            return [f for f in frames if f.get("kept")]
        return frames

    def _clamp_index():
        frames = _filtered_frames()
        if not frames:
            state["index"] = 0
            return
        state["index"] = max(0, min(state["index"], len(frames) - 1))

    with ui.column().classes("w-full gap-4"):
        with ui.card().classes("w-full p-4"):
            with ui.row().classes("w-full items-center gap-4 mb-1 flex-wrap"):
                ui.label("View:").classes("text-sm font-bold")
                group_options = {g["key"]: g["label"] for g in frame_groups}
                group_select = ui.select(
                    options=group_options,
                    value=state["group_key"],
                    label="Frame Set",
                ).classes("w-64")

                ui.separator().props("vertical")

                ui.label("Show:").classes("text-sm font-bold")
                mode_toggle = ui.toggle(
                    {"all": "All Frames", "kept": "Accepted / Kept Only"},
                    value="all",
                ).classes("text-sm")

                ui.separator().props("vertical")

                frame_count_label = ui.label("").classes("text-sm text-gray-400")

        with ui.row().classes("w-full gap-4"):
            with ui.card().classes("p-3 flex-1"):
                ui.label("Pipeline").classes("text-xs text-gray-400")
                pipeline_label = ui.label("—").classes("text-lg font-bold")

            with ui.card().classes("p-3 flex-1"):
                ui.label("Leaf Progress").classes("text-xs text-gray-400")
                leaf_progress_label = ui.label("—")

            with ui.card().classes("p-3 flex-1"):
                ui.label("Top Level").classes("text-xs text-gray-400")
                top_progress_label = ui.label("—")

            with ui.card().classes("p-3 flex-1"):
                ui.label("Latest Event").classes("text-xs text-gray-400")
                latest_event_label = ui.label("—")

        with ui.card().classes("w-full p-4"):
            image_container = ui.column().classes(
                "w-full items-center justify-center rounded-xl bg-slate-950/80 p-4"
            )

            with ui.row().classes(
                "w-full items-center justify-center gap-4 mt-4 flex-wrap"
            ):
                round_label = ui.label("").classes("text-lg font-mono")
                score_label = ui.label("").classes("text-lg")
                stage_label = ui.badge("", color="gray").classes("text-sm")
                mode_label = ui.badge("", color="gray").classes("text-sm")
                kept_label = ui.badge("", color="gray").classes("text-sm")

            with ui.row().classes(
                "w-full items-center justify-center gap-4 mt-2 flex-wrap"
            ):
                sheet_label = ui.label("").classes("text-sm text-gray-200")
                instance_label = ui.label("").classes("text-sm text-gray-400 font-mono")

            with ui.row().classes("w-full items-center gap-3 mt-4"):
                frame_slider = (
                    ui.slider(
                        min=0,
                        max=max(len(_current_group()["frames"]) - 1, 1),
                        value=0,
                        step=1,
                    )
                    .classes("flex-grow")
                    .props("label-always")
                )

            with ui.row().classes("w-full items-center justify-center gap-2 mt-3"):
                first_btn = ui.button(icon="first_page").props("flat dense")
                prev_btn = ui.button(icon="skip_previous").props("flat dense")
                play_btn = ui.button(icon="play_arrow").props("flat dense")
                next_btn = ui.button(icon="skip_next").props("flat dense")
                last_btn = ui.button(icon="last_page").props("flat dense")

                ui.separator().props("vertical")

                ui.label("Speed:").classes("text-sm")
                speed_slider = (
                    ui.slider(
                        min=1,
                        max=15,
                        value=4,
                        step=1,
                    )
                    .classes("w-32")
                    .props('label-always label="FPS"')
                )

    def _update_status_cards():
        phase = str(status_meta.get("phase", "idle"))
        pipeline_label.set_text(phase.replace("_", " ").upper())

        leaf = (
            status_meta.get("leaf_progress", {})
            if isinstance(status_meta, dict)
            else {}
        )
        leaf_done = _coerce_int(leaf.get("completed", leaf.get("done", 0)))
        leaf_total = _coerce_int(leaf.get("total", 0))
        leaf_progress_label.set_text(
            f"{leaf_done} / {leaf_total}" if leaf_total else "—"
        )

        top = (
            status_meta.get("top_progress", {}) if isinstance(status_meta, dict) else {}
        )
        top_done = _coerce_int(top.get("completed", top.get("done", 0)))
        top_total = _coerce_int(top.get("total", 0))
        if top_total:
            top_progress_label.set_text(f"{top_done} / {top_total}")
        else:
            top_progress_label.set_text(str(status_meta.get("top_level_status", "—")))

        latest_event_label.set_text(str(status_meta.get("latest_marker", "—")))

    def _render_frame():
        _update_status_cards()
        frames = _filtered_frames()
        _clamp_index()

        total_in_group = len(_current_group()["frames"])
        frame_count_label.set_text(
            f"{len(frames)} frames"
            + (
                f" (of {total_in_group} in this stage)"
                if state["mode"] == "kept"
                else ""
            )
        )

        if not frames:
            image_container.clear()
            with image_container:
                ui.label("No frames match current filter").classes(
                    "text-gray-500 italic"
                )
            round_label.set_text("")
            score_label.set_text("")
            stage_label.set_text("")
            mode_label.set_text("")
            kept_label.set_text("")
            sheet_label.set_text("")
            instance_label.set_text("")
            return

        frame = frames[state["index"]]

        image_container.clear()
        with image_container:
            ui.image(frame["frame_path"]).classes(
                "w-full max-w-[1400px] max-h-[82vh] rounded-lg border border-slate-700 bg-slate-900 object-contain shadow-2xl"
            )

        round_label.set_text(f"Round {frame['round_num']}")
        score = frame.get("score", 0.0)
        score_label.set_text(f"Score: {score:.2f}" if score else "Score: —")

        stage = str(frame.get("stage", "") or "—")
        stage_colors = {
            "legacy": "purple",
            "baseline": "purple",
            "leaves": "blue",
            "leaf": "blue",
            "top": "green",
            "top_level": "green",
            "parent": "amber",
            "composition": "orange",
        }
        stage_label.set_text(stage.upper())
        stage_label._props["color"] = stage_colors.get(stage.lower(), "gray")
        stage_label.update()

        mode = str(frame.get("mode", "") or "—")
        mode_colors = {
            "minor": "blue",
            "major": "red",
            "explore": "gray",
            "elite": "amber",
            "baseline": "purple",
            "leaf": "blue",
            "top": "green",
            "compose": "orange",
            "hierarchical": "blue",
        }
        mode_label.set_text(mode.upper())
        mode_label._props["color"] = mode_colors.get(mode.lower(), "gray")
        mode_label.update()

        accepted = frame.get("accepted")
        if accepted is True or frame.get("kept"):
            kept_label.set_text("ACCEPTED")
            kept_label._props["color"] = "green"
        elif accepted is False:
            kept_label.set_text("REJECTED")
            kept_label._props["color"] = "red"
        else:
            kept_label.set_text("INFO")
            kept_label._props["color"] = "gray"
        kept_label.update()

        sheet_name = str(frame.get("sheet_name", "")).strip()
        instance_path = str(frame.get("instance_path", "")).strip()
        artifact_dir = str(frame.get("artifact_dir", "")).strip()

        if sheet_name:
            sheet_label.set_text(f"Sheet: {sheet_name}")
        elif artifact_dir:
            sheet_label.set_text(f"Artifact: {artifact_dir}")
        else:
            sheet_label.set_text("")

        instance_label.set_text(f"Instance: {instance_path}" if instance_path else "")

        frame_slider._props["max"] = max(len(frames) - 1, 1)
        frame_slider.value = state["index"]
        frame_slider.update()

    def _on_group_change(e):
        state["group_key"] = e.value
        state["index"] = 0
        _render_frame()

    def _on_mode_change(e):
        state["mode"] = e.value
        state["index"] = 0
        _render_frame()

    def _on_slider_change(e):
        state["index"] = int(e.value)
        _render_frame()

    def _step(delta: int):
        state["index"] += delta
        _clamp_index()
        _render_frame()

    def _first():
        state["index"] = 0
        _render_frame()

    def _last():
        frames = _filtered_frames()
        state["index"] = len(frames) - 1 if frames else 0
        _render_frame()

    timer_ref = {"timer": None}

    def _tick():
        if not state["playing"]:
            return
        frames = _filtered_frames()
        if not frames:
            _stop()
            return
        state["index"] += 1
        if state["index"] >= len(frames):
            state["index"] = 0
        _render_frame()

    def _play():
        state["playing"] = True
        play_btn._props["icon"] = "pause"
        play_btn.update()
        if timer_ref["timer"] is None:
            timer_ref["timer"] = ui.timer(1.0 / max(state["speed_fps"], 1), _tick)
        else:
            timer_ref["timer"].interval = 1.0 / max(state["speed_fps"], 1)
            timer_ref["timer"].activate()

    def _stop():
        state["playing"] = False
        play_btn._props["icon"] = "play_arrow"
        play_btn.update()
        if timer_ref["timer"] is not None:
            timer_ref["timer"].deactivate()

    def _toggle_play():
        if state["playing"]:
            _stop()
        else:
            _play()

    def _on_speed_change(e):
        state["speed_fps"] = int(e.value)
        if state["playing"] and timer_ref["timer"] is not None:
            timer_ref["timer"].interval = 1.0 / max(state["speed_fps"], 1)

    group_select.on_value_change(_on_group_change)
    mode_toggle.on_value_change(_on_mode_change)
    frame_slider.on_value_change(_on_slider_change)
    play_btn.on_click(_toggle_play)
    first_btn.on_click(_first)
    last_btn.on_click(_last)
    prev_btn.on_click(lambda: _step(-1))
    next_btn.on_click(lambda: _step(1))
    speed_slider.on_value_change(_on_speed_change)

    _render_frame()
