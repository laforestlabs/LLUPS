"""A* pathfinding router with layer biasing and priority net ordering.

Pure Python. Uses heapq for O(log N) priority queue.
Grid resolution matches minimum trace width (0.25mm default).
"""
from __future__ import annotations
import heapq
import math
from typing import Optional

from .types import (
    Point, Layer, BoardState, Net, TraceSegment, Via, GridCell, RoutingResult
)
from .graph import minimum_spanning_tree


class RoutingGrid:
    """Discretized 2-layer grid for A* pathfinding.

    For a 90x58mm board at 0.25mm: 360x232x2 = ~167K cells.
    Cost values: 0=free, >0=penalty, inf=hard block.
    """

    def __init__(self, bounds: tuple[Point, Point],
                 resolution_mm: float = 0.25, layers: int = 2):
        self.resolution = resolution_mm
        self.origin = bounds[0]
        self.cols = int(math.ceil(
            (bounds[1].x - bounds[0].x) / resolution_mm)) + 1
        self.rows = int(math.ceil(
            (bounds[1].y - bounds[0].y) / resolution_mm)) + 1
        self.layers = layers
        # Flat arrays for speed: cost[layer][row * cols + col]
        size = self.rows * self.cols
        self.cost: list[list[float]] = [
            [0.0] * size for _ in range(layers)
        ]

    def _idx(self, row: int, col: int) -> int:
        return row * self.cols + col

    def in_bounds(self, cell: GridCell) -> bool:
        return (0 <= cell.x < self.cols and
                0 <= cell.y < self.rows and
                0 <= cell.layer < self.layers)

    def get_cost(self, cell: GridCell) -> float:
        if not self.in_bounds(cell):
            return float("inf")
        return self.cost[cell.layer][self._idx(cell.y, cell.x)]

    def set_cost(self, col: int, row: int, layer: int, cost: float):
        if 0 <= col < self.cols and 0 <= row < self.rows:
            idx = self._idx(row, col)
            self.cost[layer][idx] = max(self.cost[layer][idx], cost)

    def to_cell(self, point: Point, layer: Layer) -> GridCell:
        col = int(round((point.x - self.origin.x) / self.resolution))
        row = int(round((point.y - self.origin.y) / self.resolution))
        col = max(0, min(self.cols - 1, col))
        row = max(0, min(self.rows - 1, row))
        return GridCell(col, row, layer)

    def to_point(self, cell: GridCell) -> Point:
        return Point(
            self.origin.x + cell.x * self.resolution,
            self.origin.y + cell.y * self.resolution,
        )

    def mark_rect(self, tl: Point, br: Point, layer: int, cost: float):
        """Mark a rectangular region on the grid."""
        c1 = max(0, int((tl.x - self.origin.x) / self.resolution) - 1)
        r1 = max(0, int((tl.y - self.origin.y) / self.resolution) - 1)
        c2 = min(self.cols - 1, int((br.x - self.origin.x) / self.resolution) + 1)
        r2 = min(self.rows - 1, int((br.y - self.origin.y) / self.resolution) + 1)
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                self.set_cost(c, r, layer, cost)

    def mark_segment(self, start: Point, end: Point, layer: int,
                     width_mm: float, cost: float):
        """Mark a trace segment with given width on the grid."""
        hw = width_mm / 2 + self.resolution  # extra cell margin
        min_x = min(start.x, end.x) - hw
        max_x = max(start.x, end.x) + hw
        min_y = min(start.y, end.y) - hw
        max_y = max(start.y, end.y) + hw
        self.mark_rect(Point(min_x, min_y), Point(max_x, max_y), layer, cost)

    def clear_net(self, net_name: str, segments: list[TraceSegment],
                  vias_list: list[Via]):
        """Remove costs associated with a specific net (for rip-up)."""
        # We can't selectively clear, so we rebuild. This method is a placeholder.
        # The conflict resolver rebuilds the grid from scratch.
        pass


class AStarRouter:
    """A* pathfinder on RoutingGrid with layer biasing."""

    # Layer bias: penalize non-preferred direction to reduce vias
    # F.Cu prefers horizontal, B.Cu prefers vertical
    LAYER_BIAS = {
        Layer.FRONT: {"h": 1.0, "v": 1.3},
        Layer.BACK:  {"h": 1.3, "v": 1.0},
    }
    VIA_COST = 8.0
    NEIGHBOR_OFFSETS = [(1, 0), (-1, 0), (0, 1), (0, -1)]  # 4-connected

    def __init__(self, grid: RoutingGrid):
        self.grid = grid

    def find_path(self, start: GridCell, end: GridCell,
                  width_cells: int = 1,
                  max_search: int = 200000) -> Optional[list[GridCell]]:
        """A* with Manhattan heuristic. Returns path or None."""
        if start == end:
            return [start]

        grid = self.grid
        # Priority queue: (f_cost, tiebreaker, cell)
        counter = 0
        open_set: list[tuple[float, int, GridCell]] = []
        g_score: dict[GridCell, float] = {start: 0.0}
        came_from: dict[GridCell, GridCell] = {}

        h = self._heuristic(start, end)
        heapq.heappush(open_set, (h, counter, start))

        while open_set and counter < max_search:
            f, _, current = heapq.heappop(open_set)

            if current == end:
                return self._reconstruct(came_from, current)

            current_g = g_score.get(current, float("inf"))

            # Same-layer neighbors (4-connected)
            for dx, dy in self.NEIGHBOR_OFFSETS:
                nx, ny = current.x + dx, current.y + dy
                nbr = GridCell(nx, ny, current.layer)
                if not grid.in_bounds(nbr):
                    continue

                # Check corridor (width-aware)
                cell_cost = self._corridor_cost(nx, ny, current.layer, width_cells)
                if cell_cost >= float("inf"):
                    continue

                # Direction bias
                if dx != 0:  # horizontal move
                    bias = self.LAYER_BIAS[Layer(current.layer)]["h"]
                else:  # vertical move
                    bias = self.LAYER_BIAS[Layer(current.layer)]["v"]

                tentative_g = current_g + bias + cell_cost

                if tentative_g < g_score.get(nbr, float("inf")):
                    g_score[nbr] = tentative_g
                    came_from[nbr] = current
                    h = self._heuristic(nbr, end)
                    counter += 1
                    heapq.heappush(open_set, (tentative_g + h, counter, nbr))

            # Layer transition (via)
            other_layer = Layer.BACK if current.layer == Layer.FRONT else Layer.FRONT
            via_cell = GridCell(current.x, current.y, other_layer)
            if grid.in_bounds(via_cell):
                via_g = current_g + self.VIA_COST + grid.get_cost(via_cell)
                if via_g < g_score.get(via_cell, float("inf")):
                    g_score[via_cell] = via_g
                    came_from[via_cell] = current
                    counter += 1
                    h = self._heuristic(via_cell, end)
                    heapq.heappush(open_set, (via_g + h, counter, via_cell))

        return None  # no path found

    def _corridor_cost(self, col: int, row: int, layer: int,
                       width_cells: int) -> float:
        """Check all cells within trace width corridor. Return max cost."""
        if width_cells <= 1:
            return self.grid.get_cost(GridCell(col, row, Layer(layer)))
        half = width_cells // 2
        max_cost = 0.0
        for dc in range(-half, half + 1):
            for dr in range(-half, half + 1):
                c = self.grid.get_cost(GridCell(col + dc, row + dr, Layer(layer)))
                if c >= float("inf"):
                    return float("inf")
                max_cost = max(max_cost, c)
        return max_cost

    def _heuristic(self, a: GridCell, b: GridCell) -> float:
        """Manhattan distance + via cost if layers differ."""
        h = abs(a.x - b.x) + abs(a.y - b.y)
        if a.layer != b.layer:
            h += self.VIA_COST
        return float(h)

    def _reconstruct(self, came_from: dict, current: GridCell) -> list[GridCell]:
        path = [current]
        while current in came_from:
            current = came_from[current]
            path.append(current)
        path.reverse()
        return path


class RoutingSolver:
    """Routes all nets with priority ordering using A* on a grid."""

    def __init__(self, state: BoardState, config: dict = None):
        self.state = state
        self.cfg = config or {}
        self.resolution = self.cfg.get("grid_resolution_mm", 0.25)
        self.clearance = self.cfg.get("clearance_mm", 0.2)
        self.signal_width = self.cfg.get("signal_width_mm", 0.25)
        self.power_width = self.cfg.get("power_width_mm", 1.0)
        self.skip_gnd = self.cfg.get("skip_gnd_routing", True)
        self.via_drill = self.cfg.get("via_drill_mm", 0.3)
        self.via_size = self.cfg.get("via_size_mm", 0.6)
        self.trace_cost = self.cfg.get("existing_trace_cost", 10.0)

    def solve(self) -> tuple[list[TraceSegment], list[Via], list[str]]:
        """Route all nets. Returns (traces, vias, failed_net_names)."""
        grid = self._build_grid()
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
                # Mark routed traces as soft obstacles
                for seg in result.segments:
                    grid.mark_segment(seg.start, seg.end, seg.layer,
                                      seg.width_mm + self.clearance,
                                      self.trace_cost)
                for v in result.vias:
                    grid.mark_rect(
                        Point(v.pos.x - v.size_mm / 2, v.pos.y - v.size_mm / 2),
                        Point(v.pos.x + v.size_mm / 2, v.pos.y + v.size_mm / 2),
                        Layer.FRONT, self.trace_cost)
                    grid.mark_rect(
                        Point(v.pos.x - v.size_mm / 2, v.pos.y - v.size_mm / 2),
                        Point(v.pos.x + v.size_mm / 2, v.pos.y + v.size_mm / 2),
                        Layer.BACK, self.trace_cost)
            else:
                failed.append(net.name)

        print(f"  Routed {len(ordered) - len(failed)}/{len(ordered)} nets, "
              f"{len(all_traces)} segments, {len(all_vias)} vias")
        if failed:
            print(f"  Failed: {failed}")

        return all_traces, all_vias, failed

    def _build_grid(self) -> RoutingGrid:
        """Create grid and mark component obstacles."""
        grid = RoutingGrid(self.state.board_outline, self.resolution)

        # Mark component bodies as hard obstacles (except pad areas)
        for comp in self.state.components.values():
            tl, br = comp.bbox(self.clearance)
            for layer in range(2):
                grid.mark_rect(tl, br, layer, float("inf"))

        # Clear pad locations (they're connection targets, not obstacles)
        for comp in self.state.components.values():
            for pad in comp.pads:
                pad_size = self.resolution * 2
                grid.mark_rect(
                    Point(pad.pos.x - pad_size, pad.pos.y - pad_size),
                    Point(pad.pos.x + pad_size, pad.pos.y + pad_size),
                    pad.layer, 0.0)  # Note: set_cost uses max(), so this won't clear
                # We need direct write to clear pad areas
                c = grid.to_cell(pad.pos, pad.layer)
                for dc in range(-1, 2):
                    for dr in range(-1, 2):
                        col, row = c.x + dc, c.y + dr
                        if 0 <= col < grid.cols and 0 <= row < grid.rows:
                            idx = grid._idx(row, col)
                            grid.cost[pad.layer][idx] = 0.0

        return grid

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
            if n.is_power:
                return (2, -len(n.pad_refs), n.name)
            return (1, len(n.pad_refs), n.name)

        return sorted(nets, key=sort_key)

    def _route_net(self, router: AStarRouter, grid: RoutingGrid,
                   net: Net) -> RoutingResult:
        """Route a single net via MST of its pads."""
        # Gather pad positions
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

        # Build MST
        names = [str(i) for i in range(len(pad_points))]
        pos_map = {names[i]: pad_points[i][0] for i in range(len(pad_points))}
        mst_edges = minimum_spanning_tree(
            names, lambda a, b: pos_map[a].dist(pos_map[b])
        )

        width = net.width_mm
        width_cells = max(1, int(width / self.resolution))
        segments: list[TraceSegment] = []
        vias: list[Via] = []
        all_ok = True

        for a_name, b_name, _ in mst_edges:
            a_idx, b_idx = int(a_name), int(b_name)
            a_pos, a_layer = pad_points[a_idx]
            b_pos, b_layer = pad_points[b_idx]

            start = grid.to_cell(a_pos, a_layer)
            end = grid.to_cell(b_pos, b_layer)

            path = router.find_path(start, end, width_cells)
            if path is None:
                # Try from both layers
                for try_layer in [Layer.FRONT, Layer.BACK]:
                    alt_start = GridCell(start.x, start.y, try_layer)
                    alt_end = GridCell(end.x, end.y, try_layer)
                    path = router.find_path(alt_start, alt_end, width_cells)
                    if path:
                        # Add vias at endpoints if layer changed
                        if try_layer != a_layer:
                            vias.append(Via(a_pos, net.name,
                                            self.via_drill, self.via_size))
                        if try_layer != b_layer:
                            vias.append(Via(b_pos, net.name,
                                            self.via_drill, self.via_size))
                        break

            if path is None:
                all_ok = False
                continue

            # Convert path to trace segments + vias
            segs, path_vias = self._path_to_traces(path, grid, net.name, width)
            segments.extend(segs)
            vias.extend(path_vias)

        return RoutingResult(segments=segments, vias=vias,
                             cost=sum(s.length for s in segments),
                             success=all_ok)

    def _path_to_traces(self, path: list[GridCell], grid: RoutingGrid,
                        net_name: str,
                        width: float) -> tuple[list[TraceSegment], list[Via]]:
        """Convert grid path to trace segments, merging collinear cells."""
        if len(path) < 2:
            return [], []

        segments: list[TraceSegment] = []
        vias: list[Via] = []

        seg_start = path[0]
        prev = path[0]

        for i in range(1, len(path)):
            curr = path[i]

            # Layer change -> via
            if curr.layer != prev.layer:
                # End current segment
                if seg_start != prev:
                    segments.append(TraceSegment(
                        grid.to_point(seg_start), grid.to_point(prev),
                        Layer(prev.layer), net_name, width))
                vias.append(Via(grid.to_point(prev), net_name,
                                self.via_drill, self.via_size))
                seg_start = curr

            # Direction change -> new segment
            elif i >= 2:
                pp = path[i - 2]
                if pp.layer == prev.layer == curr.layer:
                    dx1, dy1 = prev.x - pp.x, prev.y - pp.y
                    dx2, dy2 = curr.x - prev.x, curr.y - prev.y
                    if (dx1, dy1) != (dx2, dy2):
                        segments.append(TraceSegment(
                            grid.to_point(seg_start), grid.to_point(prev),
                            Layer(prev.layer), net_name, width))
                        seg_start = prev

            prev = curr

        # Final segment
        if seg_start != prev:
            segments.append(TraceSegment(
                grid.to_point(seg_start), grid.to_point(prev),
                Layer(prev.layer), net_name, width))

        return segments, vias
