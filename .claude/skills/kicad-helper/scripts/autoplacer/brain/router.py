"""A* pathfinding router with layer biasing and priority net ordering.

Pure Python. Uses heapq for O(log N) priority queue.
Grid resolution matches minimum trace width (0.5mm default).
"""
from __future__ import annotations
import heapq
import math
from typing import Optional

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

from .types import (
    Point, Layer, BoardState, Net, TraceSegment, Via, GridCell, RoutingResult
)
from .graph import minimum_spanning_tree
from .grid_builder import RoutingGrid, build_grid, path_to_traces


class AStarRouter:
    """A* pathfinder on RoutingGrid with layer biasing."""

    # Layer bias: penalize non-preferred direction to reduce vias
    # F.Cu prefers horizontal, B.Cu prefers vertical
    LAYER_BIAS = {
        Layer.FRONT: {"h": 1.0, "v": 1.3},
        Layer.BACK:  {"h": 1.3, "v": 1.0},
    }
    VIA_COST = 8.0
    NEIGHBOR_OFFSETS = [(1, 0), (-1, 0), (0, 1), (0, -1),
                        (1, 1), (1, -1), (-1, 1), (-1, -1)]
    DIAG_COST = 1.41421356  # sqrt(2)

    def __init__(self, grid: RoutingGrid):
        self.grid = grid

    def find_path(self, start: GridCell, end: GridCell,
                  width_cells: int = 1,
                  max_search: int = 500000) -> Optional[list[GridCell]]:
        """A* with octile heuristic (numpy-optimized)."""
        if start == end:
            return [start]

        grid = self.grid
        ex, ey, el = end.x, end.y, end.layer
        sx, sy, sl = start.x, start.y, start.layer
        cols, rows = grid.cols, grid.rows
        n_cells = rows * cols
        via_cost = self.VIA_COST
        width_radius = max(0, width_cells - 1)
        width_offsets = (
            [(0, 0)] if width_radius == 0 else
            [(ox, oy)
             for oy in range(-width_radius, width_radius + 1)
             for ox in range(-width_radius, width_radius + 1)]
        )

        end_t = (ex, ey, el)

        bias_h = [self.LAYER_BIAS[Layer.FRONT]["h"], self.LAYER_BIAS[Layer.BACK]["h"]]
        bias_v = [self.LAYER_BIAS[Layer.FRONT]["v"], self.LAYER_BIAS[Layer.BACK]["v"]]
        cost_arrays = grid.cost

        if _HAS_NUMPY:
            INF = 1e18
            g_arr = np.full((2, n_cells), INF, dtype=np.float64)
            g_arr[sl, sy * cols + sx] = 0.0

            # Octile distance
            col_idx = np.arange(cols, dtype=np.float64)
            row_idx = np.arange(rows, dtype=np.float64)
            dx_arr = np.abs(col_idx - ex)[np.newaxis, :]
            dy_arr = np.abs(row_idx - ey)[:, np.newaxis]
            h_2d = (np.maximum(dx_arr, dy_arr) +
                    (self.DIAG_COST - 1.0) * np.minimum(dx_arr, dy_arr))
            h_flat = h_2d.flatten()
            h_arr = np.empty((2, n_cells), dtype=np.float64)
            h_arr[0] = h_flat + (via_cost if 0 != el else 0.0)
            h_arr[1] = h_flat + (via_cost if 1 != el else 0.0)

            came_from = np.full((2, n_cells), -1, dtype=np.int32)
            counter = 0
            open_set = []
            start_h = float(h_arr[sl, sy * cols + sx])
            heapq.heappush(open_set, (start_h, counter, (sx, sy, sl)))

            while open_set and counter < max_search:
                f, _, cur = heapq.heappop(open_set)
                cx, cy, cl = cur

                if cur == end_t:
                    path = [GridCell(ex, ey, Layer(el))]
                    x, y, layer = ex, ey, el
                    while True:
                        parent_idx = came_from[layer, y * cols + x]
                        if parent_idx == -1:
                            break
                        px = parent_idx % cols
                        py = (parent_idx // cols) % rows
                        pl = parent_idx // n_cells
                        path.append(GridCell(px, py, Layer(pl)))
                        x, y, layer = px, py, pl
                    path.reverse()
                    return path

                cur_idx = cy * cols + cx
                cur_g = g_arr[cl, cur_idx]
                if f > cur_g + h_arr[cl, cur_idx] + 1e-6:
                    continue

                layer_costs = cost_arrays[cl]
                bh = bias_h[cl]
                bv = bias_v[cl]
                diag_bias = (bh + bv) * 0.5 * self.DIAG_COST

                def footprint_cost_or_blocked(x: int, y: int, layer: int) -> float:
                    if width_radius == 0:
                        if not (0 <= x < cols and 0 <= y < rows):
                            return 1e6
                        return cost_arrays[layer][y * cols + x]
                    y1 = max(0, y - width_radius)
                    y2 = min(rows, y + width_radius + 1)
                    x1 = max(0, x - width_radius)
                    x2 = min(cols, x + width_radius + 1)
                    if y1 >= y2 or x1 >= x2:
                        return 1e6
                    arr_2d = cost_arrays[layer].reshape(rows, cols)
                    region = arr_2d[y1:y2, x1:x2]
                    max_c = float(region.max())
                    return 1e6 if max_c >= 1e6 else max_c

                # Cardinals
                card_free = [False, False, False, False]
                for i, (dx, dy) in enumerate(((1, 0), (-1, 0), (0, 1), (0, -1))):
                    nx, ny = cx + dx, cy + dy
                    if not (0 <= nx < cols and 0 <= ny < rows):
                        continue
                    cell_cost = footprint_cost_or_blocked(nx, ny, cl)
                    if cell_cost >= 1e6:
                        continue
                    nidx = ny * cols + nx
                    card_free[i] = True
                    bias = bh if dx != 0 else bv
                    tent_g = cur_g + bias + cell_cost * 0.5
                    if tent_g < g_arr[cl, nidx]:
                        g_arr[cl, nidx] = tent_g
                        came_from[cl, nidx] = cl * n_cells + cy * cols + cx
                        nbr = (nx, ny, cl)
                        counter += 1
                        heapq.heappush(open_set,
                                       (tent_g + h_arr[cl, nidx], counter, nbr))

                # Diagonals
                diag_dirs = ((1, 1, 0, 2), (1, -1, 0, 3),
                             (-1, 1, 1, 2), (-1, -1, 1, 3))
                for dx, dy, ci1, ci2 in diag_dirs:
                    if not (card_free[ci1] and card_free[ci2]):
                        continue
                    nx, ny = cx + dx, cy + dy
                    if not (0 <= nx < cols and 0 <= ny < rows):
                        continue
                    cell_cost = footprint_cost_or_blocked(nx, ny, cl)
                    if cell_cost >= 1e6:
                        continue
                    nidx = ny * cols + nx
                    tent_g = cur_g + diag_bias + cell_cost * 0.5 * self.DIAG_COST
                    if tent_g < g_arr[cl, nidx]:
                        g_arr[cl, nidx] = tent_g
                        came_from[cl, nidx] = cl * n_cells + cy * cols + cx
                        nbr = (nx, ny, cl)
                        counter += 1
                        heapq.heappush(open_set,
                                       (tent_g + h_arr[cl, nidx], counter, nbr))

                # Via transition
                ol = 1 - cl
                other_cost = footprint_cost_or_blocked(cx, cy, ol)
                if other_cost < 1e6:
                    via_g = cur_g + via_cost + other_cost * 0.5
                    if via_g < g_arr[ol, cur_idx]:
                        g_arr[ol, cur_idx] = via_g
                        came_from[ol, cur_idx] = cl * n_cells + cy * cols + cx
                        nbr_v = (cx, cy, ol)
                        counter += 1
                        heapq.heappush(open_set,
                                       (via_g + h_arr[ol, cur_idx], counter, nbr_v))

            return None

        # --- Pure-Python fallback (no numpy) ---
        start_t = (sx, sy, sl)
        counter = 0
        open_set = []
        g_score: dict[tuple, float] = {start_t: 0.0}
        came_from: dict[tuple, tuple] = {}

        h = abs(sx - ex) + abs(sy - ey) + (via_cost if sl != el else 0)
        heapq.heappush(open_set, (h, counter, start_t))

        while open_set and counter < max_search:
            f, _, cur = heapq.heappop(open_set)
            cx, cy, cl = cur

            if cur == end_t:
                path = [GridCell(ex, ey, Layer(el))]
                t = cur
                while t in came_from:
                    t = came_from[t]
                    path.append(GridCell(t[0], t[1], Layer(t[2])))
                path.reverse()
                return path

            cur_g = g_score.get(cur, 1e18)
            if f > cur_g + abs(cx - ex) + abs(cy - ey) + 1e-6:
                continue

            layer_costs = cost_arrays[cl]
            def footprint_cost_or_blocked(x: int, y: int, layer: int) -> float:
                if width_radius == 0:
                    if not (0 <= x < cols and 0 <= y < rows):
                        return 1e6
                    return cost_arrays[layer][y * cols + x]
                max_cost = 0.0
                layer_arr = cost_arrays[layer]
                for ox, oy in width_offsets:
                    tx, ty = x + ox, y + oy
                    if not (0 <= tx < cols and 0 <= ty < rows):
                        return 1e6
                    c = layer_arr[ty * cols + tx]
                    if c >= 1e6:
                        return c
                    if c > max_cost:
                        max_cost = c
                return max_cost

            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < cols and 0 <= ny < rows):
                    continue
                cell_cost = footprint_cost_or_blocked(nx, ny, cl)
                if cell_cost >= 1e6:
                    continue
                bias = bias_h[cl] if dx != 0 else bias_v[cl]
                tent_g = cur_g + bias + cell_cost * 0.5
                nbr = (nx, ny, cl)
                if tent_g < g_score.get(nbr, 1e18):
                    g_score[nbr] = tent_g
                    came_from[nbr] = cur
                    h = abs(nx - ex) + abs(ny - ey) + (via_cost if cl != el else 0)
                    counter += 1
                    heapq.heappush(open_set, (tent_g + h, counter, nbr))

            ol = 1 - cl
            other_cost = footprint_cost_or_blocked(cx, cy, ol)
            if other_cost < 1e6:
                via_g = cur_g + via_cost + other_cost * 0.5
                nbr_v = (cx, cy, ol)
                if via_g < g_score.get(nbr_v, 1e18):
                    g_score[nbr_v] = via_g
                    came_from[nbr_v] = cur
                    h = abs(cx - ex) + abs(cy - ey) + (via_cost if ol != el else 0)
                    counter += 1
                    heapq.heappush(open_set, (via_g + h, counter, nbr_v))

        return None

    def _heuristic(self, a: GridCell, b: GridCell) -> float:
        """Manhattan distance + via cost if layers differ."""
        h = abs(a.x - b.x) + abs(a.y - b.y)
        if a.layer != b.layer:
            h += self.VIA_COST
        return float(h)


class RoutingSolver:
    """Routes all nets with priority ordering using A* on a grid."""

    def __init__(self, state: BoardState, config: dict = None):
        self.state = state
        self.cfg = config or {}
        self.resolution = self.cfg.get("grid_resolution_mm", 0.5)
        self.clearance = self.cfg.get("clearance_mm", 0.2)
        self.signal_width = self.cfg.get("signal_width_mm", 0.127)
        self.power_width = self.cfg.get("power_width_mm", 0.127)
        self.skip_gnd = self.cfg.get("skip_gnd_routing", True)
        self.via_drill = self.cfg.get("via_drill_mm", 0.3)
        self.via_size = self.cfg.get("via_size_mm", 0.6)
        self.trace_cost = self.cfg.get("existing_trace_cost", 100.0)
        self.max_search = self.cfg.get("max_search", 500_000)
        self.mst_retry_limit = self.cfg.get("mst_retry_limit", 3)
        self.allow_width_relaxation = self.cfg.get("allow_width_relaxation", True)

    def solve(self) -> tuple[list[TraceSegment], list[Via], list[str]]:
        """Route all nets. Returns (traces, vias, failed_net_names)."""
        grid = build_grid(self.state, self.resolution, self.clearance)
        router = AStarRouter(grid)
        ordered = self._prioritize_nets()

        all_traces: list[TraceSegment] = []
        all_vias: list[Via] = []
        failed: list[str] = []

        for net in ordered:
            result = self._route_net(router, grid, net)
            if result.success:
                all_traces.extend(result.segments)
                all_vias.extend(result.vias)
                # Mark routed traces as hard blocks to prevent cross-net shorts
                HARD_BLOCK = 1e6
                for seg in result.segments:
                    grid.mark_segment(seg.start, seg.end, seg.layer,
                                      seg.width_mm + self.clearance,
                                      HARD_BLOCK)
                for v in result.vias:
                    half = v.size_mm / 2 + self.clearance
                    grid.mark_rect(
                        Point(v.pos.x - half, v.pos.y - half),
                        Point(v.pos.x + half, v.pos.y + half),
                        Layer.FRONT, HARD_BLOCK)
                    grid.mark_rect(
                        Point(v.pos.x - half, v.pos.y - half),
                        Point(v.pos.x + half, v.pos.y + half),
                        Layer.BACK, HARD_BLOCK)
            else:
                failed.append(net.name)

        print(f"  Routed {len(ordered) - len(failed)}/{len(ordered)} nets, "
              f"{len(all_traces)} segments, {len(all_vias)} vias")
        if failed:
            print(f"  Failed: {failed}")

        return all_traces, all_vias, failed

    def _prioritize_nets(self) -> list[Net]:
        """Order nets for routing."""
        nets = []
        for net in self.state.nets.values():
            if self.skip_gnd and net.name in ("GND", "/GND"):
                continue
            if len(net.pad_refs) < 2:
                continue
            nets.append(net)

        def sort_key(n: Net) -> tuple:
            return (
                0 if n.is_power else 1,   # power nets first
                -n.priority,              # higher priority first
                len(n.pad_refs),          # then simpler nets first
                n.name,                   # stable deterministic order
            )

        return sorted(nets, key=sort_key)

    def _route_net(self, router: AStarRouter, grid: RoutingGrid,
                   net: Net) -> RoutingResult:
        """Route a single net via MST of its pads, retrying with different roots on failure."""
        pad_points: list[tuple[Point, Layer]] = []
        for ref, pad_id in net.pad_refs:
            comp = self.state.components.get(ref)
            if not comp:
                continue
            for p in comp.pads:
                if p.pad_id == pad_id and p.net == net.name:
                    pad_points.append((p.pos, p.layer))
                    break

        if len(pad_points) < 2:
            return RoutingResult(success=len(pad_points) <= 1)

        width = net.width_mm
        strict_width_cells = self._width_to_cells(width + self.clearance)
        relaxed_width_cells = self._width_to_cells(width)

        names = [str(i) for i in range(len(pad_points))]
        pos_map = {names[i]: pad_points[i][0] for i in range(len(pad_points))}
        mst_edges = minimum_spanning_tree(
            names, lambda a, b: pos_map[a].dist(pos_map[b])
        )

        # Retry only for multi-pad nets where edge ordering matters.
        # 2-pad nets have one edge — retry is useless.
        try_limit = self._mst_try_limit(len(pad_points))
        best_result = None
        best_edges = -1

        for attempt in range(try_limit):
            edges = mst_edges if attempt == 0 else self._mst_from_root(
                attempt - 1, names, pos_map)

            segments: list[TraceSegment] = []
            vias: list[Via] = []
            edges_routed = 0

            for a_name, b_name, _ in edges:
                a_idx, b_idx = int(a_name), int(b_name)
                a_pos, a_layer = pad_points[a_idx]
                b_pos, b_layer = pad_points[b_idx]

                start = grid.to_cell(a_pos, a_layer)
                end = grid.to_cell(b_pos, b_layer)

                path = None
                for width_cells in self._edge_width_candidates(
                        strict_width_cells, relaxed_width_cells):
                    path = router.find_path(start, end, width_cells, self.max_search)
                    if path is not None:
                        break
                if path is None:
                    vias_before = len(vias)
                    for width_cells in self._edge_width_candidates(
                            strict_width_cells, relaxed_width_cells):
                        for try_layer in [Layer.FRONT, Layer.BACK]:
                            alt_start = GridCell(start.x, start.y, try_layer)
                            alt_end = GridCell(end.x, end.y, try_layer)
                            path = router.find_path(alt_start, alt_end, width_cells, self.max_search)
                            if path:
                                if try_layer != a_layer:
                                    vias.append(Via(a_pos, net.name,
                                                    self.via_drill, self.via_size))
                                if try_layer != b_layer:
                                    vias.append(Via(b_pos, net.name,
                                                    self.via_drill, self.via_size))
                                break
                        if path is not None:
                            break
                    # Mark newly-added escape vias as hard blocks
                    HARD_BLOCK = 1e6
                    for ev in vias[vias_before:]:
                        half = ev.size_mm / 2 + self.clearance
                        grid.mark_rect(
                            Point(ev.pos.x - half, ev.pos.y - half),
                            Point(ev.pos.x + half, ev.pos.y + half),
                            Layer.FRONT, HARD_BLOCK)
                        grid.mark_rect(
                            Point(ev.pos.x - half, ev.pos.y - half),
                            Point(ev.pos.x + half, ev.pos.y + half),
                            Layer.BACK, HARD_BLOCK)

                if path is None:
                    continue

                edges_routed += 1
                segs, path_vias = path_to_traces(
                    path, grid, net.name, width,
                    self.via_drill, self.via_size)
                segments.extend(segs)
                vias.extend(path_vias)

                # Mark this edge on the grid so subsequent MST edges
                # see where we already routed (avoids overlap / wasted space)
                for seg in segs:
                    grid.mark_segment(seg.start, seg.end, seg.layer,
                                      seg.width_mm + self.clearance,
                                      self.trace_cost)

            all_ok = edges_routed == len(edges)
            if edges_routed > best_edges:
                best_edges = edges_routed
                best_result = RoutingResult(
                    segments=segments, vias=vias,
                    cost=sum(s.length for s in segments),
                    success=all_ok)
            if all_ok:
                break

        return best_result

    def _width_to_cells(self, width_mm: float) -> int:
        """Convert geometric width to conservative grid occupancy."""
        return max(1, math.ceil(width_mm / self.resolution))

    def _edge_width_candidates(self, strict_cells: int, relaxed_cells: int) -> list[int]:
        """Try strict width first, then optional relaxed fallback."""
        if self.allow_width_relaxation and relaxed_cells < strict_cells:
            return [strict_cells, relaxed_cells]
        return [strict_cells]

    def _mst_try_limit(self, n_pads: int) -> int:
        """Adaptive retry budget for multi-pad nets."""
        if n_pads <= 2:
            return 1
        if self.mst_retry_limit > 0:
            return self.mst_retry_limit
        return min(4, n_pads - 1)

    def _mst_from_root(self, root: int, names: list[str],
                       pos_map: dict[str, Point]) -> list[tuple[str, str, float]]:
        """Build MST with different root, producing varied edge ordering."""
        n = len(names)
        from .graph import minimum_spanning_tree

        reordered = [names[root]] + [nm for i, nm in enumerate(names) if i != root]
        reordered_map = {reordered[i]: i for i in range(n)}
        remapped_pos = {str(reordered_map[nm]): pos_map[nm] for nm in names}
        remapped_names = [str(i) for i in range(n)]

        edges = minimum_spanning_tree(
            remapped_names, lambda a, b: remapped_pos[a].dist(remapped_pos[b])
        )
        return [(names[int(a)], names[int(b)], d) for a, b, d in edges]
