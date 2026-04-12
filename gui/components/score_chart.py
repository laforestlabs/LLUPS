"""Score-over-time chart using Plotly."""
from __future__ import annotations

import plotly.graph_objects as go
from nicegui import ui


def create_score_chart(rounds: list[dict], title: str = "Score vs Round") -> ui.plotly:
    """Build a Plotly scatter chart showing score over rounds.

    Color-codes by mutation mode: minor=blue, major=red, explore=gray, elite=gold.
    Shows running best as a line.
    """
    fig = build_score_figure(rounds, title)
    return ui.plotly(fig).classes("w-full h-96")


def build_score_figure(rounds: list[dict],
                       title: str = "Score vs Round") -> go.Figure:
    if not rounds:
        fig = go.Figure()
        fig.update_layout(title=title, template="plotly_dark",
                          xaxis_title="Round", yaxis_title="Score")
        return fig

    mode_colors = {
        "minor": "#4dabf7",   # blue
        "major": "#ff6b6b",   # red
        "explore": "#868e96", # gray
        "elite": "#ffd43b",   # gold
    }

    # Separate by mode
    mode_data: dict[str, dict] = {}
    for r in rounds:
        m = r.get("mode", "minor")
        if m not in mode_data:
            mode_data[m] = {"x": [], "y": [], "text": [], "marker_symbol": []}
        mode_data[m]["x"].append(r["round_num"])
        mode_data[m]["y"].append(r["score"])
        kept = r.get("kept", False)
        mode_data[m]["marker_symbol"].append("circle" if kept else "x")
        mode_data[m]["text"].append(
            f"R{r['round_num']} s={r['score']:.1f} "
            f"{'KEPT' if kept else 'disc'}"
        )

    fig = go.Figure()

    for mode, data in mode_data.items():
        color = mode_colors.get(mode, "#adb5bd")
        fig.add_trace(go.Scatter(
            x=data["x"], y=data["y"],
            mode="markers",
            name=mode.upper(),
            text=data["text"],
            marker=dict(
                color=color,
                size=8,
                symbol=data["marker_symbol"],
                line=dict(width=1, color="white"),
            ),
            hovertemplate="%{text}<extra></extra>",
        ))

    # Running best line
    if rounds:
        best_x, best_y = [], []
        running_best = -1e9
        for r in sorted(rounds, key=lambda r: r["round_num"]):
            if r.get("kept", False) and r["score"] > running_best:
                running_best = r["score"]
            best_x.append(r["round_num"])
            best_y.append(running_best if running_best > -1e9 else r["score"])

        fig.add_trace(go.Scatter(
            x=best_x, y=best_y,
            mode="lines",
            name="Best",
            line=dict(color="#51cf66", width=2, dash="solid"),
            hoverinfo="skip",
        ))

    fig.update_layout(
        title=title,
        template="plotly_dark",
        xaxis_title="Round",
        yaxis_title="Score",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=50, r=20, t=50, b=40),
        hovermode="closest",
    )

    return fig


def build_subscore_figure(rounds: list[dict],
                          title: str = "Sub-scores") -> go.Figure:
    """Multi-line chart showing sub-score breakdown."""
    fig = go.Figure()

    metrics = [
        ("placement_score", "Placement", "#4dabf7"),
        ("route_completion", "Route %", "#51cf66"),
        ("via_score", "Via Score", "#ffd43b"),
    ]

    for key, name, color in metrics:
        x = [r["round_num"] for r in rounds if r.get(key) is not None]
        y = [r[key] for r in rounds if r.get(key) is not None]
        if x:
            fig.add_trace(go.Scatter(
                x=x, y=y, mode="lines+markers", name=name,
                line=dict(color=color, width=1.5),
                marker=dict(size=4),
            ))

    # DRC total (inverted — lower is better, show as 100 - drc_total)
    x_drc = [r["round_num"] for r in rounds if r.get("drc_total") is not None]
    y_drc = [max(0, 100 - r["drc_total"]) for r in rounds
             if r.get("drc_total") is not None]
    if x_drc:
        fig.add_trace(go.Scatter(
            x=x_drc, y=y_drc, mode="lines+markers", name="DRC (100-total)",
            line=dict(color="#ff6b6b", width=1.5),
            marker=dict(size=4),
        ))

    fig.update_layout(
        title=title,
        template="plotly_dark",
        xaxis_title="Round",
        yaxis_title="Score (0-100)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=50, r=20, t=50, b=40),
    )
    return fig
