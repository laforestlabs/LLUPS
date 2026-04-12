"""PCB progression viewer — animated playback of per-round board renders."""
from __future__ import annotations

import json
import glob
from pathlib import Path

from nicegui import ui


def _load_frame_metadata(experiments_dir: Path) -> list[dict]:
    """Load frame info: round number, kept status, score, mode.

    Returns list of dicts sorted by round_num, each with:
        round_num, kept, score, mode, frame_path
    """
    frames_dir = experiments_dir.resolve() / "frames"
    rounds_dir = experiments_dir.resolve() / "rounds"
    if not frames_dir.is_dir():
        return []

    frame_files = sorted(glob.glob(str(frames_dir / "frame_*.png")))
    if not frame_files:
        return []

    # Build round metadata lookup from round JSON files
    round_meta: dict[int, dict] = {}
    if rounds_dir.is_dir():
        for rpath in sorted(rounds_dir.glob("round_*.json")):
            try:
                with open(rpath) as f:
                    data = json.load(f)
                rnum = data.get("round", 0)
                round_meta[rnum] = {
                    "kept": data.get("kept", False),
                    "score": data.get("score", 0.0),
                    "mode": data.get("mode", ""),
                }
            except (json.JSONDecodeError, OSError):
                continue

    # Fallback: try experiments.jsonl
    if not round_meta:
        jsonl_path = experiments_dir / "experiments.jsonl"
        if jsonl_path.exists():
            try:
                with open(jsonl_path) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            rnum = data.get("round_num", data.get("round", 0))
                            round_meta[rnum] = {
                                "kept": data.get("kept", False),
                                "score": data.get("score", 0.0),
                                "mode": data.get("mode", ""),
                            }
                        except json.JSONDecodeError:
                            continue
            except OSError:
                pass

    frames = []
    for fpath in frame_files:
        fname = Path(fpath).stem  # frame_0000
        try:
            rnum = int(fname.replace("frame_", ""))
        except ValueError:
            continue
        meta = round_meta.get(rnum, {})
        frames.append({
            "round_num": rnum,
            "kept": meta.get("kept", rnum == 0),  # baseline always "kept"
            "score": meta.get("score", 0.0),
            "mode": meta.get("mode", "baseline" if rnum == 0 else ""),
            "frame_path": fpath,
        })

    frames.sort(key=lambda f: f["round_num"])
    return frames


def create_progression_viewer(experiments_dir: Path):
    """Build the PCB progression viewer with playback controls."""
    all_frames = _load_frame_metadata(experiments_dir)

    if not all_frames:
        ui.label("No frame images found in .experiments/frames/").classes(
            "text-gray-500 italic")
        ui.label(
            "Run an experiment first — frames are generated automatically "
            "for each round."
        ).classes("text-gray-500 text-sm")
        return

    # ── State ──
    state = {
        "mode": "all",  # "all" or "kept"
        "index": 0,
        "playing": False,
        "speed_fps": 4,  # frames per second
    }

    def _filtered_frames() -> list[dict]:
        if state["mode"] == "kept":
            return [f for f in all_frames if f["kept"]]
        return all_frames

    def _clamp_index():
        frames = _filtered_frames()
        if not frames:
            state["index"] = 0
            return
        state["index"] = max(0, min(state["index"], len(frames) - 1))

    # ── Filter controls ──
    with ui.row().classes("w-full items-center gap-4 mb-3"):
        ui.label("Show:").classes("text-sm font-bold")
        mode_toggle = ui.toggle(
            {"all": "All Rounds", "kept": "Improvements Only"},
            value="all",
        ).classes("text-sm")

        ui.separator().props("vertical")

        frame_count_label = ui.label("").classes("text-sm text-gray-400")

    # ── Image display ──
    image_container = ui.column().classes(
        "w-full items-center justify-center")

    # ── Info bar ──
    with ui.row().classes("w-full items-center justify-center gap-6 mt-2"):
        round_label = ui.label("").classes("text-lg font-mono")
        score_label = ui.label("").classes("text-lg")
        mode_label = ui.badge("", color="gray").classes("text-sm")
        kept_label = ui.badge("", color="gray").classes("text-sm")

    # ── Slider ──
    slider_container = ui.row().classes("w-full items-center gap-3 mt-2")

    with slider_container:
        frame_slider = ui.slider(
            min=0, max=max(len(all_frames) - 1, 1), value=0, step=1,
        ).classes("flex-grow").props("label-always")

    # ── Playback controls ──
    with ui.row().classes(
        "w-full items-center justify-center gap-2 mt-2"
    ):
        first_btn = ui.button(icon="first_page").props("flat dense")
        prev_btn = ui.button(icon="skip_previous").props("flat dense")
        play_btn = ui.button(icon="play_arrow").props("flat dense")
        next_btn = ui.button(icon="skip_next").props("flat dense")
        last_btn = ui.button(icon="last_page").props("flat dense")

        ui.separator().props("vertical")

        ui.label("Speed:").classes("text-sm")
        speed_slider = ui.slider(
            min=1, max=15, value=4, step=1,
        ).classes("w-32").props('label-always label="FPS"')

    # ── Rendering logic ──
    def _render_frame():
        frames = _filtered_frames()
        _clamp_index()

        frame_count_label.set_text(
            f"{len(frames)} frames"
            + (f" (of {len(all_frames)} total)" if state["mode"] == "kept"
               else "")
        )

        if not frames:
            image_container.clear()
            with image_container:
                ui.label("No frames match current filter").classes(
                    "text-gray-500 italic")
            round_label.set_text("")
            score_label.set_text("")
            mode_label.set_text("")
            kept_label.set_text("")
            return

        idx = state["index"]
        frame = frames[idx]

        # Update image
        image_container.clear()
        with image_container:
            ui.image(frame["frame_path"]).classes(
                "max-w-4xl max-h-[600px] object-contain")

        # Update info
        round_label.set_text(f"Round {frame['round_num']}")

        score = frame["score"]
        score_label.set_text(f"Score: {score:.2f}" if score else "Score: —")

        m = frame["mode"]
        mode_colors = {
            "minor": "blue", "major": "red", "explore": "gray",
            "elite": "amber", "baseline": "purple",
        }
        mode_label.set_text(m.upper() if m else "—")
        mode_label._props["color"] = mode_colors.get(m, "gray")
        mode_label.update()

        if frame["kept"]:
            kept_label.set_text("KEPT")
            kept_label._props["color"] = "green"
        else:
            kept_label.set_text("DISCARDED")
            kept_label._props["color"] = "red"
        kept_label.update()

        # Update slider range + value without re-triggering
        frame_slider._props["max"] = max(len(frames) - 1, 1)
        frame_slider.value = idx
        frame_slider.update()

    # ── Event handlers ──
    def _on_mode_change(e):
        state["mode"] = e.value
        # Try to stay on the same round when switching modes
        frames = _filtered_frames()
        if frames:
            current_frames_before = (
                all_frames if state["mode"] == "kept"
                else [f for f in all_frames if f["kept"]]
            )
            # Just reset to 0 on mode switch for simplicity
            state["index"] = 0
        _render_frame()

    mode_toggle.on_value_change(_on_mode_change)

    def _on_slider_change(e):
        state["index"] = int(e.value)
        _render_frame()

    frame_slider.on_value_change(_on_slider_change)

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
            state["index"] = 0  # loop
        _render_frame()

    def _play():
        state["playing"] = True
        play_btn._props["icon"] = "pause"
        play_btn.update()
        if timer_ref["timer"] is None:
            interval = 1.0 / max(state["speed_fps"], 1)
            timer_ref["timer"] = ui.timer(interval, _tick)
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

    play_btn.on_click(_toggle_play)
    first_btn.on_click(_first)
    last_btn.on_click(_last)
    prev_btn.on_click(lambda: _step(-1))
    next_btn.on_click(lambda: _step(1))
    speed_slider.on_value_change(_on_speed_change)

    # Initial render
    _render_frame()
