#!/usr/bin/env python3
"""Generate a self-contained interactive HTML report from experiment data.

Reads experiments.jsonl and round detail JSONs to produce a single HTML file
with embedded CSS/JS (no external dependencies, works offline).

Sections:
  1. Executive Summary — best score, rounds, duration, trajectory
  2. Score Timeline — interactive chart with per-round hover details
  3. Round Browser — filterable, sortable table of all rounds
  4. Net Failure Analysis — nets sorted by failure frequency
  5. Shorts Dashboard — dedicated shorts tracking with locations
  6. Configuration Sensitivity — scatter of each param vs score

Usage:
    python3 generate_report.py <experiments_dir> [--output report.html] [--pcb file.kicad_pcb]
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import sys
from pathlib import Path


def load_jsonl(path: str) -> list[dict]:
    experiments = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                experiments.append(json.loads(line))
    return experiments


def load_rounds(rounds_dir: str) -> dict[int, dict]:
    """Load round detail JSONs indexed by round number."""
    rounds = {}
    for path in sorted(glob.glob(os.path.join(rounds_dir, "round_*.json"))):
        with open(path) as f:
            d = json.load(f)
            rounds[d["round"]] = d
    return rounds


def generate_report(experiments: list[dict], rounds: dict[int, dict],
                    output_path: str) -> None:
    """Generate the self-contained HTML report."""

    # Compute summary stats
    total_rounds = len(experiments)
    kept_rounds = [e for e in experiments if e["kept"]]
    best_score = max((e["score"] for e in experiments), default=0)
    total_dur_s = sum(e.get("duration_s", 0) for e in experiments)
    worst_shorts = max((e.get("drc_shorts", 0) for e in experiments), default=0)

    # Build JSON data for the client-side JS
    experiments_json = json.dumps(experiments, default=str)
    rounds_json = json.dumps({str(k): v for k, v in rounds.items()}, default=str)

    # Net failure aggregation
    net_stats = {}
    for rd in rounds.values():
        for nr in rd.get("per_net", []):
            name = nr.get("net", "")
            if not name:
                continue
            if name not in net_stats:
                net_stats[name] = {"total": 0, "failures": 0, "reasons": {}}
            net_stats[name]["total"] += 1
            if not nr.get("success", True):
                net_stats[name]["failures"] += 1
                r = nr.get("failure_reason", "unknown") or "unknown"
                net_stats[name]["reasons"][r] = net_stats[name]["reasons"].get(r, 0) + 1

    failing_nets = sorted(
        [(n, s) for n, s in net_stats.items() if s["failures"] > 0],
        key=lambda x: x[1]["failures"], reverse=True,
    )

    net_table_rows = ""
    for name, s in failing_nets[:50]:
        rate = s["failures"] / s["total"] * 100
        reasons = ", ".join(f"{r}: {c}" for r, c in sorted(s["reasons"].items(), key=lambda x: -x[1]))
        color = "#e74c3c" if rate > 50 else "#e67e22" if rate > 20 else "#f1c40f"
        net_table_rows += (
            f'<tr><td>{name}</td><td>{s["total"]}</td>'
            f'<td style="color:{color}">{s["failures"]} ({rate:.0f}%)</td>'
            f'<td>{reasons}</td></tr>\n'
        )

    # Shorts dashboard
    shorts_rows = ""
    for e in experiments:
        if e.get("drc_shorts", 0) > 0:
            rd = rounds.get(e["round_num"], {})
            violations = rd.get("drc", {}).get("violations", [])
            shorts_list = [v for v in violations if v.get("type") == "shorting_items"]
            loc_str = "; ".join(
                f"({v.get('x_mm', '?')}, {v.get('y_mm', '?')})"
                for v in shorts_list[:5]
            ) or "no coordinates"
            nets_str = ", ".join(set(
                filter(None, [v.get("net1") for v in shorts_list] +
                             [v.get("net2") for v in shorts_list])
            )) or "unknown"
            shorts_rows += (
                f'<tr><td>R{e["round_num"]}</td><td>{e["score"]:.2f}</td>'
                f'<td style="color:red;font-weight:bold">{e["drc_shorts"]}</td>'
                f'<td>{nets_str}</td><td>{loc_str}</td></tr>\n'
            )

    # Config sensitivity: gather all tunable params and their values
    param_data = {}
    for e in experiments:
        delta = e.get("config_delta", {})
        for k, v in delta.items():
            if isinstance(v, (int, float)):
                if k not in param_data:
                    param_data[k] = []
                param_data[k].append({"score": e["score"], "value": v, "kept": e["kept"]})

    html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<title>Experiment Report — {total_rounds} Rounds</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       max-width: 1200px; margin: 0 auto; padding: 1em; background: #fafafa; color: #333; }}
h1 {{ font-size: 1.6em; border-bottom: 3px solid #2c3e50; padding-bottom: 0.3em; margin-bottom: 0.5em; }}
h2 {{ font-size: 1.2em; color: #2c3e50; margin: 1.5em 0 0.5em; cursor: pointer; }}
h2:hover {{ color: #3498db; }}
.summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 12px; margin: 1em 0; }}
.card {{ background: white; border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);
         text-align: center; }}
.card .value {{ font-size: 1.8em; font-weight: bold; color: #2c3e50; }}
.card .label {{ font-size: 0.85em; color: #7f8c8d; margin-top: 4px; }}
table {{ border-collapse: collapse; width: 100%; margin: 0.5em 0; background: white;
         box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-radius: 4px; overflow: hidden; }}
th, td {{ border-bottom: 1px solid #eee; padding: 8px 12px; text-align: left; font-size: 0.9em; }}
th {{ background: #ecf0f1; font-weight: 600; position: sticky; top: 0; cursor: pointer; }}
th:hover {{ background: #d5dbdb; }}
tr:hover {{ background: #f7f9fa; }}
.collapsible {{ max-height: 0; overflow: hidden; transition: max-height 0.3s ease-out; }}
.collapsible.open {{ max-height: 5000px; }}
canvas {{ max-width: 100%; margin: 1em 0; }}
.chart-container {{ background: white; border-radius: 8px; padding: 16px;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin: 1em 0; }}
.filter-bar {{ margin: 0.5em 0; }}
.filter-bar input {{ padding: 6px 12px; border: 1px solid #ddd; border-radius: 4px; font-size: 0.9em; }}
.filter-bar select {{ padding: 6px; border: 1px solid #ddd; border-radius: 4px; }}
.detail-panel {{ background: #f8f9fa; padding: 12px; margin: 4px 0; border-left: 3px solid #3498db;
                 font-size: 0.85em; display: none; }}
.shorts-alert {{ background: #fdedec; border-left: 4px solid #e74c3c; padding: 12px; margin: 0.5em 0; }}
.tag {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 0.75em; font-weight: 600; }}
.tag-kept {{ background: #d5f5e3; color: #27ae60; }}
.tag-discard {{ background: #fadbd8; color: #e74c3c; }}
.tag-major {{ background: #d6eaf8; color: #2980b9; }}
</style>
</head><body>

<h1>PCB Layout Experiment Report</h1>

<!-- Executive Summary -->
<div class="summary">
  <div class="card"><div class="value">{total_rounds}</div><div class="label">Total Rounds</div></div>
  <div class="card"><div class="value">{len(kept_rounds)}</div><div class="label">Improvements</div></div>
  <div class="card"><div class="value">{best_score:.2f}</div><div class="label">Best Score</div></div>
  <div class="card"><div class="value">{total_dur_s:.0f}s</div><div class="label">Total Time</div></div>
  <div class="card"><div class="value" style="color:{'#e74c3c' if worst_shorts > 0 else '#27ae60'}">{worst_shorts}</div>
    <div class="label">Worst Shorts</div></div>
  <div class="card"><div class="value">{len(failing_nets)}</div><div class="label">Failing Nets</div></div>
</div>

<!-- Score Timeline -->
<h2 onclick="toggle('timeline-section')">▸ Score Timeline</h2>
<div id="timeline-section" class="collapsible open">
<div class="chart-container">
  <canvas id="scoreChart" height="200"></canvas>
</div>
</div>

<!-- Round Browser -->
<h2 onclick="toggle('rounds-section')">▸ Round Browser ({total_rounds} rounds)</h2>
<div id="rounds-section" class="collapsible open">
<div class="filter-bar">
  <input id="roundFilter" placeholder="Filter by round, mode, or net..." oninput="filterRounds()">
  <select id="modeFilter" onchange="filterRounds()">
    <option value="">All modes</option>
    <option value="minor">Minor</option>
    <option value="major">Major</option>
    <option value="explore">Explore</option>
  </select>
  <label><input type="checkbox" id="keptOnly" onchange="filterRounds()"> Kept only</label>
</div>
<table id="roundsTable">
<thead><tr>
  <th onclick="sortTable(0)">Round</th>
  <th onclick="sortTable(1)">Score</th>
  <th onclick="sortTable(2)">Mode</th>
  <th onclick="sortTable(3)">Duration</th>
  <th onclick="sortTable(4)">Routed</th>
  <th onclick="sortTable(5)">Vias</th>
  <th onclick="sortTable(6)">Shorts</th>
  <th onclick="sortTable(7)">DRC</th>
  <th>Status</th>
</tr></thead>
<tbody id="roundsBody"></tbody>
</table>
</div>

<!-- Net Failure Analysis -->
<h2 onclick="toggle('nets-section')">▸ Net Failure Analysis ({len(failing_nets)} failing nets)</h2>
<div id="nets-section" class="collapsible">
<table>
<thead><tr><th>Net</th><th>Attempts</th><th>Failures</th><th>Reasons</th></tr></thead>
<tbody>{net_table_rows if net_table_rows else '<tr><td colspan="4">No net failures</td></tr>'}</tbody>
</table>
</div>

<!-- Shorts Dashboard -->
<h2 onclick="toggle('shorts-section')">▸ Shorts Dashboard</h2>
<div id="shorts-section" class="collapsible{'open' if worst_shorts > 0 else ''}">
{'<div class="shorts-alert">⚠ Shorts detected across experiment rounds</div>' if worst_shorts > 0 else ''}
<table>
<thead><tr><th>Round</th><th>Score</th><th>Shorts</th><th>Nets</th><th>Locations</th></tr></thead>
<tbody>{shorts_rows if shorts_rows else '<tr><td colspan="5">No shorts in any round</td></tr>'}</tbody>
</table>
</div>

<!-- Config Sensitivity -->
<h2 onclick="toggle('config-section')">▸ Configuration Sensitivity</h2>
<div id="config-section" class="collapsible">
<div id="paramCharts"></div>
</div>

<script>
const experiments = {experiments_json};
const rounds = {rounds_json};

// Toggle collapsible sections
function toggle(id) {{
  const el = document.getElementById(id);
  el.classList.toggle('open');
  const h2 = el.previousElementSibling;
  if (h2) h2.textContent = h2.textContent.replace(/[▸▾]/, el.classList.contains('open') ? '▾' : '▸');
}}

// Populate rounds table
function populateRounds() {{
  const tbody = document.getElementById('roundsBody');
  tbody.innerHTML = '';
  experiments.forEach(e => {{
    const tr = document.createElement('tr');
    tr.dataset.round = e.round_num;
    tr.dataset.mode = e.mode;
    tr.dataset.kept = e.kept;
    const tag = e.kept ? '<span class="tag tag-kept">KEPT</span>' :
                e.mode === 'major' ? '<span class="tag tag-major">MAJOR</span>' :
                '<span class="tag tag-discard">-</span>';
    tr.innerHTML = `
      <td>${{e.round_num}}</td>
      <td>${{e.score.toFixed(2)}}</td>
      <td>${{e.mode}}</td>
      <td>${{e.duration_s.toFixed(1)}}s</td>
      <td>${{e.nets_routed || e.route_completion || '-'}}</td>
      <td>${{e.via_score !== undefined ? e.via_score.toFixed(0) : '-'}}</td>
      <td style="color:${{e.drc_shorts > 0 ? 'red' : 'inherit'}};font-weight:${{e.drc_shorts > 0 ? 'bold' : 'normal'}}">${{e.drc_shorts || 0}}</td>
      <td>${{e.drc_total || 0}}</td>
      <td>${{tag}}</td>`;
    tr.style.cursor = 'pointer';
    tr.onclick = () => toggleRoundDetail(e.round_num, tr);
    tbody.appendChild(tr);
  }});
}}

function toggleRoundDetail(roundNum, tr) {{
  const existing = tr.nextElementSibling;
  if (existing && existing.classList.contains('detail-row')) {{
    existing.remove();
    return;
  }}
  const rd = rounds[roundNum];
  if (!rd) return;
  const detailTr = document.createElement('tr');
  detailTr.className = 'detail-row';
  const td = document.createElement('td');
  td.colSpan = 9;
  td.style.padding = '12px';
  td.style.background = '#f8f9fa';
  td.style.fontSize = '0.85em';

  let html = '<strong>Timing:</strong> ';
  const t = rd.timing || {{}};
  html += `Placement: ${{(t.placement_ms/1000).toFixed(1)}}s | Routing: ${{(t.routing_ms/1000).toFixed(1)}}s | RRR: ${{(t.rrr_ms/1000).toFixed(1)}}s<br>`;

  const routing = rd.routing || {{}};
  html += `<strong>Routing:</strong> ${{routing.routed}}/${{routing.total}} nets, ${{routing.vias}} vias, ${{routing.total_length_mm?.toFixed(0)}}mm total<br>`;
  if (routing.failed_nets && routing.failed_nets.length > 0) {{
    html += `<strong>Failed nets:</strong> <span style="color:red">${{routing.failed_nets.join(', ')}}</span><br>`;
  }}

  const perNet = rd.per_net || [];
  if (perNet.length > 0) {{
    html += '<details><summary>Per-net details (' + perNet.length + ' nets)</summary>';
    html += '<table style="font-size:0.85em"><tr><th>Net</th><th>OK</th><th>Segs</th><th>Vias</th><th>Len</th><th>A*</th><th>ms</th><th>Reason</th></tr>';
    perNet.forEach(n => {{
      const c = n.success ? '' : 'style="color:red"';
      html += `<tr ${{c}}><td>${{n.net}}</td><td>${{n.success?'✓':'✗'}}</td><td>${{n.segments}}</td><td>${{n.vias}}</td><td>${{n.length_mm}}</td><td>${{n.a_star_expansions}}</td><td>${{n.time_ms}}</td><td>${{n.failure_reason||''}}</td></tr>`;
    }});
    html += '</table></details>';
  }}

  td.innerHTML = html;
  detailTr.appendChild(td);
  tr.after(detailTr);
}}

function filterRounds() {{
  const text = document.getElementById('roundFilter').value.toLowerCase();
  const mode = document.getElementById('modeFilter').value;
  const keptOnly = document.getElementById('keptOnly').checked;
  const rows = document.querySelectorAll('#roundsBody tr:not(.detail-row)');
  rows.forEach(tr => {{
    const matchMode = !mode || tr.dataset.mode === mode;
    const matchKept = !keptOnly || tr.dataset.kept === 'true';
    const matchText = !text || tr.textContent.toLowerCase().includes(text);
    tr.style.display = (matchMode && matchKept && matchText) ? '' : 'none';
  }});
}}

let sortDir = {{}};
function sortTable(col) {{
  const tbody = document.getElementById('roundsBody');
  const rows = Array.from(tbody.querySelectorAll('tr:not(.detail-row)'));
  sortDir[col] = !sortDir[col];
  rows.sort((a, b) => {{
    let va = a.cells[col].textContent.replace(/[^\\d.\\-]/g, '');
    let vb = b.cells[col].textContent.replace(/[^\\d.\\-]/g, '');
    va = parseFloat(va) || 0;
    vb = parseFloat(vb) || 0;
    return sortDir[col] ? va - vb : vb - va;
  }});
  rows.forEach(r => tbody.appendChild(r));
}}

// Score chart (simple canvas)
function drawScoreChart() {{
  const canvas = document.getElementById('scoreChart');
  const ctx = canvas.getContext('2d');
  const W = canvas.width = canvas.parentElement.clientWidth - 32;
  const H = canvas.height = 250;
  const pad = {{l: 50, r: 20, t: 20, b: 30}};
  const pw = W - pad.l - pad.r;
  const ph = H - pad.t - pad.b;

  if (experiments.length === 0) return;
  const scores = experiments.map(e => e.score);
  const minS = Math.min(...scores.filter(s => s > 0)) - 1;
  const maxS = Math.max(...scores) + 1;

  // Running best line
  let best = 0;
  const bestLine = scores.map(s => {{
    const e = experiments[scores.indexOf(s)];
    if (e && e.kept) best = s;
    return best;
  }});

  ctx.clearRect(0, 0, W, H);

  // Grid
  ctx.strokeStyle = '#eee';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 5; i++) {{
    const y = pad.t + (ph * i / 5);
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
    ctx.fillStyle = '#999'; ctx.font = '11px sans-serif'; ctx.textAlign = 'right';
    ctx.fillText((maxS - (maxS - minS) * i / 5).toFixed(1), pad.l - 6, y + 4);
  }}

  // Points
  experiments.forEach((e, i) => {{
    const x = pad.l + (i / Math.max(experiments.length - 1, 1)) * pw;
    const y = pad.t + (1 - (e.score - minS) / (maxS - minS)) * ph;
    ctx.beginPath();
    ctx.arc(x, y, e.kept ? 5 : 3, 0, Math.PI * 2);
    ctx.fillStyle = e.kept ? '#2ecc71' : (e.mode === 'major' ? '#e74c3c' : '#bdc3c7');
    ctx.fill();
    if (e.kept) {{ ctx.strokeStyle = '#000'; ctx.lineWidth = 1.5; ctx.stroke(); }}
  }});

  // Best line
  ctx.beginPath();
  ctx.strokeStyle = '#2c3e50';
  ctx.lineWidth = 2;
  let started = false;
  bestLine.forEach((b, i) => {{
    if (b <= 0) return;
    const x = pad.l + (i / Math.max(experiments.length - 1, 1)) * pw;
    const y = pad.t + (1 - (b - minS) / (maxS - minS)) * ph;
    if (!started) {{ ctx.moveTo(x, y); started = true; }} else ctx.lineTo(x, y);
  }});
  ctx.stroke();
}}

// Config sensitivity scatter plots
function drawParamCharts() {{
  const container = document.getElementById('paramCharts');
  const paramData = {{}};
  experiments.forEach(e => {{
    const delta = e.config_delta || {{}};
    Object.entries(delta).forEach(([k, v]) => {{
      if (typeof v !== 'number') return;
      if (!paramData[k]) paramData[k] = [];
      paramData[k].push({{value: v, score: e.score, kept: e.kept}});
    }});
  }});

  Object.entries(paramData).forEach(([param, points]) => {{
    if (points.length < 3) return;
    const div = document.createElement('div');
    div.className = 'chart-container';
    div.innerHTML = `<strong>${{param}}</strong>`;
    const canvas = document.createElement('canvas');
    canvas.width = 400; canvas.height = 150;
    div.appendChild(canvas);
    container.appendChild(div);

    const ctx = canvas.getContext('2d');
    const vals = points.map(p => p.value);
    const scores = points.map(p => p.score);
    const minV = Math.min(...vals), maxV = Math.max(...vals);
    const minS = Math.min(...scores.filter(s=>s>0))-0.5, maxS = Math.max(...scores)+0.5;
    const pad = {{l:40,r:10,t:10,b:20}};
    const pw = 400-pad.l-pad.r, ph = 150-pad.t-pad.b;

    points.forEach(p => {{
      const x = pad.l + ((p.value-minV)/(maxV-minV||1))*pw;
      const y = pad.t + (1-(p.score-minS)/(maxS-minS||1))*ph;
      ctx.beginPath(); ctx.arc(x,y,3,0,Math.PI*2);
      ctx.fillStyle = p.kept ? '#2ecc71' : '#bdc3c7';
      ctx.fill();
    }});
  }});
}}

// Init
populateRounds();
drawScoreChart();
drawParamCharts();
window.addEventListener('resize', drawScoreChart);
</script>
</body></html>"""

    with open(output_path, "w") as f:
        f.write(html)
    print(f"Report saved: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate interactive HTML experiment report")
    parser.add_argument("experiments_dir",
                        help="Path to .experiments directory")
    parser.add_argument("--output", "-o", default=None,
                        help="Output HTML path (default: <experiments_dir>/report.html)")
    parser.add_argument("--log", default="experiments.jsonl",
                        help="JSONL log filename (default: experiments.jsonl)")
    args = parser.parse_args()

    log_path = os.path.join(args.experiments_dir, args.log)
    if not os.path.exists(log_path):
        print(f"JSONL log not found: {log_path}", file=sys.stderr)
        sys.exit(1)

    experiments = load_jsonl(log_path)
    print(f"Loaded {len(experiments)} experiments")

    rounds_dir = os.path.join(args.experiments_dir, "rounds")
    rounds = load_rounds(rounds_dir) if os.path.isdir(rounds_dir) else {}
    print(f"Loaded {len(rounds)} round details")

    output = args.output or os.path.join(args.experiments_dir, "report.html")
    generate_report(experiments, rounds, output)


if __name__ == "__main__":
    main()
