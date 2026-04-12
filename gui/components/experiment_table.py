"""AG Grid experiment table component."""
from __future__ import annotations

from nicegui import ui


def create_experiment_table(rounds: list[dict],
                            on_select=None) -> ui.aggrid:
    """Build an AG Grid table for experiment rounds."""
    columns = [
        {"field": "round_num", "headerName": "#", "width": 60,
         "sortable": True, "filter": True},
        {"field": "score", "headerName": "Score", "width": 90,
         "sortable": True, "filter": "agNumberColumnFilter",
         "valueFormatter": "x.value?.toFixed(2)"},
        {"field": "mode", "headerName": "Mode", "width": 80,
         "sortable": True, "filter": True,
         "cellClassRules": {
             "text-blue-400": "x.value === 'minor'",
             "text-red-400": "x.value === 'major'",
             "text-gray-400": "x.value === 'explore'",
             "text-yellow-400": "x.value === 'elite'",
         }},
        {"field": "kept", "headerName": "Kept", "width": 70,
         "sortable": True, "filter": True,
         "cellRenderer": "params.value ? '✓' : '✗'",
         "cellClassRules": {
             "text-green-400": "x.value === true",
             "text-gray-600": "x.value === false",
         }},
        {"field": "placement_score", "headerName": "Place", "width": 80,
         "sortable": True, "valueFormatter": "x.value?.toFixed(1)"},
        {"field": "route_completion", "headerName": "Route%", "width": 80,
         "sortable": True, "valueFormatter": "x.value?.toFixed(1)"},
        {"field": "drc_shorts", "headerName": "Shorts", "width": 80,
         "sortable": True,
         "cellClassRules": {"text-red-500 font-bold": "x.value > 0"}},
        {"field": "drc_total", "headerName": "DRC", "width": 70,
         "sortable": True},
        {"field": "duration_s", "headerName": "Time(s)", "width": 80,
         "sortable": True, "valueFormatter": "x.value?.toFixed(1)"},
    ]

    grid = ui.aggrid({
        "columnDefs": columns,
        "rowData": rounds,
        "defaultColDef": {"resizable": True},
        "rowSelection": "single",
        "domLayout": "autoHeight",
        "pagination": True,
        "paginationPageSize": 25,
        ":getRowStyle": """params => {
            if (params.data.kept) return {background: 'rgba(81,207,102,0.08)'};
            return {};
        }""",
    }).classes("w-full")

    if on_select:
        grid.on("cellClicked", on_select)

    return grid
