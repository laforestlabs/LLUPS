"""RoutingGrid class, grid construction, and path-to-traces conversion.

Shared between RoutingSolver and RipUpRerouter — eliminates ~120 lines
of duplication: both modules used the same grid-building logic (component
obstacles, pad escape corridors, trace/via marking) and identical
_path_to_traces conversion.
"""
from __future__ import annotations
import math

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

from .types import (
    Point, Layer, BoardState, Net, TraceSegment, Via, GridCell
)


COMPONENT_COST = 100.0  # High but not infinite — last resort pathing


class RoutingGrid:
    """Discretized 2-layer grid for A* pathfinding.

    For a 90x58mm board at 0.5mm: 180x116x2 = ~41.8K cells.
    Cost values: 0=free, >0=penalty, inf=hard block.
    """

    def __init__(self, bounds: tuple[Point, Point],
                 resolution_mm: float = 0.5, layers: int = 2):
        self.resolution = resolution_mm
        self.origin = bounds[0]
        self.cols = int(math.ceil(
            (bounds[1].x - bounds[0].x) / resolution_mm)) + 1
        self.rows = int(math.ceil(
            (bounds[1].y - bounds[0].y) / resolution_mm)) + 1
        self.layers = layers
        if _HAS_NUMPY:
            size = self.rows * self.cols
            self.cost = [np.zeros(size, dtype=np.float32) for _ in range(layers)]
        else:
            self.cost = [[0.0] * (self.rows * self.cols) for _ in range(layers)]

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
        if _HAS_NUMPY:
            arr2d = self.cost[layer].reshape(self.rows, self.cols)
            np.maximum(arr2d[r1:r2 + 1, c1:c2 + 1], cost,
                       out=arr2d[r1:r2 + 1, c1:c2 + 1])
        else:
            for r in range(r1, r2 + 1):
                for c in range(c1, c2 + 1):
                    self.set_cost(c, r, layer, cost)

    def clear_rect(self, tl: Point, br: Point, layer: int):
        """Clear a rectangular region on the grid to zero cost."""
        c1 = max(0, int((tl.x - self.origin.x) / self.resolution) - 1)
        r1 = max(0, int((tl.y - self.origin.y) / self.resolution) - 1)
        c2 = min(self.cols - 1, int((br.x - self.origin.x) / self.resolution) + 1)
        r2 = min(self.rows - 1, int((br.y - self.origin.y) / self.resolution) + 1)
        if _HAS_NUMPY:
            arr2d = self.cost[layer].reshape(self.rows, self.cols)
            arr2d[r1:r2 + 1, c1:c2 + 1] = 0.0
        else:
            for r in range(r1, r2 + 1):
                base = self._idx(r, 0)
                for c in range(c1, c2 + 1):
                    self.cost[layer][base + c] = 0.0

    def _segment_cells(self, start: Point, end: Point, width_mm: float):
        """Yield (col, row) for cells within width_mm/2 of the line segment."""
        hw = width_mm / 2
        margin = hw + self.resolution
        min_x = min(start.x, end.x) - margin
        max_x = max(start.x, end.x) + margin
        min_y = min(start.y, end.y) - margin
        max_y = max(start.y, end.y) + margin

        c1 = max(0, int((min_x - self.origin.x) / self.resolution))
        r1 = max(0, int((min_y - self.origin.y) / self.resolution))
        c2 = min(self.cols - 1, int((max_x - self.origin.x) / self.resolution) + 1)
        r2 = min(self.rows - 1, int((max_y - self.origin.y) / self.resolution) + 1)

        sx, sy = start.x, start.y
        dx, dy = end.x - start.x, end.y - start.y
        seg_len_sq = dx * dx + dy * dy

        if _HAS_NUMPY and (r2 - r1) > 2 and (c2 - c1) > 2:
            cols_arr = self.origin.x + np.arange(c1, c2 + 1) * self.resolution
            rows_arr = self.origin.y + np.arange(r1, r2 + 1) * self.resolution
            px = cols_arr[np.newaxis, :]  # (1, nc)
            py = rows_arr[:, np.newaxis]  # (nr, 1)
            if seg_len_sq < 1e-12:
                dist = np.sqrt((px - sx) ** 2 + (py - sy) ** 2)
            else:
                t = np.clip(((px - sx) * dx + (py - sy) * dy) / seg_len_sq, 0, 1)
                cx_arr = sx + t * dx
                cy_arr = sy + t * dy
                dist = np.sqrt((px - cx_arr) ** 2 + (py - cy_arr) ** 2)
            mask = dist <= hw
            ry, cx_idx = np.where(mask)
            for k in range(len(ry)):
                yield c1 + int(cx_idx[k]), r1 + int(ry[k])
        else:
            for r in range(r1, r2 + 1):
                py = self.origin.y + r * self.resolution
                for c in range(c1, c2 + 1):
                    px = self.origin.x + c * self.resolution
                    if seg_len_sq < 1e-12:
                        d = math.hypot(px - sx, py - sy)
                    else:
                        t = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / seg_len_sq))
                        d = math.hypot(px - (sx + t * dx), py - (sy + t * dy))
                    if d <= hw:
                        yield c, r

    def mark_segment(self, start: Point, end: Point, layer: int,
                     width_mm: float, cost: float):
        """Mark cells within width_mm/2 of the line segment."""
        for c, r in self._segment_cells(start, end, width_mm):
            self.set_cost(c, r, layer, cost)

    def unmark_segment(self, seg: TraceSegment, width_mm: float):
        """Clear soft-obstacle cost for cells near a trace segment.

        This is only safe for soft overlays (existing traces/vias), not hard
        component obstacle regions.
        """
        for c, r in self._segment_cells(seg.start, seg.end, width_mm):
            if 0 <= c < self.cols and 0 <= r < self.rows:
                self.cost[seg.layer][self._idx(r, c)] = 0.0

    def copy(self) -> "RoutingGrid":
        """Return a copy with independent cost arrays."""
        g = RoutingGrid.__new__(RoutingGrid)
        g.resolution = self.resolution
        g.origin = self.origin
        g.cols = self.cols
        g.rows = self.rows
        g.layers = self.layers
        if _HAS_NUMPY:
            g.cost = [arr.copy() for arr in self.cost]
        else:
            g.cost = [list(c) for c in self.cost]
        return g


def build_grid(state: BoardState, resolution: float, clearance: float,
               traces: list[TraceSegment] = None,
               vias: list[Via] = None,
               exclude_net: str = "",
               trace_cost: float = 10.0) -> RoutingGrid:
    """Build a RoutingGrid with component obstacles and existing traces."""
    grid = RoutingGrid(state.board_outline, resolution)
    traces = traces or []
    vias = vias or []

    # --- Collect pad and escape corridor cells ---
    pad_cells: set[tuple[int, int, int]] = set()
    escape_cells: set[tuple[int, int, int]] = set()

    for comp in state.components.values():
        comp_tl, comp_br = comp.bbox()
        for pad in comp.pads:
            pc = grid.to_cell(pad.pos, pad.layer)
            for dc in range(-1, 2):
                for dr in range(-1, 2):
                    pad_cells.add((pc.x + dc, pc.y + dr, pad.layer))
            dx_l = pad.pos.x - comp_tl.x
            dx_r = comp_br.x - pad.pos.x
            dy_t = pad.pos.y - comp_tl.y
            dy_b = comp_br.y - pad.pos.y
            min_d = min(dx_l, dx_r, dy_t, dy_b)
            if min_d == dx_l:
                ce = grid.to_cell(Point(comp_tl.x - clearance * 2, pad.pos.y), pad.layer)
                for c in range(ce.x, pc.x + 1):
                    for dr in range(-1, 2):
                        escape_cells.add((c, pc.y + dr, pad.layer))
            elif min_d == dx_r:
                ce = grid.to_cell(Point(comp_br.x + clearance * 2, pad.pos.y), pad.layer)
                for c in range(pc.x, ce.x + 1):
                    for dr in range(-1, 2):
                        escape_cells.add((c, pc.y + dr, pad.layer))
            elif min_d == dy_t:
                ce = grid.to_cell(Point(pad.pos.x, comp_tl.y - clearance * 2), pad.layer)
                for r in range(ce.y, pc.y + 1):
                    for dc in range(-1, 2):
                        escape_cells.add((pc.x + dc, r, pad.layer))
            else:
                ce = grid.to_cell(Point(pad.pos.x, comp_br.y + clearance * 2), pad.layer)
                for r in range(pc.y, ce.y + 1):
                    for dc in range(-1, 2):
                        escape_cells.add((pc.x + dc, r, pad.layer))

    # --- Mark component bodies as obstacles ---
    safe_cells = pad_cells | escape_cells
    for comp in state.components.values():
        tl, br = comp.bbox(clearance)
        c1 = max(0, int((tl.x - grid.origin.x) / grid.resolution) - 1)
        r1 = max(0, int((tl.y - grid.origin.y) / grid.resolution) - 1)
        c2 = min(grid.cols - 1, int((br.x - grid.origin.x) / grid.resolution) + 1)
        r2 = min(grid.rows - 1, int((br.y - grid.origin.y) / grid.resolution) + 1)

        if _HAS_NUMPY:
            for layer in range(2):
                arr2d = grid.cost[layer].reshape(grid.rows, grid.cols)
                np.maximum(arr2d[r1:r2 + 1, c1:c2 + 1], COMPONENT_COST,
                           out=arr2d[r1:r2 + 1, c1:c2 + 1])
            for (c, r, layer) in safe_cells:
                if 0 <= c < grid.cols and 0 <= r < grid.rows:
                    grid.cost[layer][grid._idx(r, c)] = 0.0
        else:
            for layer in range(2):
                for r in range(r1, r2 + 1):
                    for c in range(c1, c2 + 1):
                        if (c, r, layer) in safe_cells:
                            continue
                        idx = grid._idx(r, c)
                        grid.cost[layer][idx] = max(grid.cost[layer][idx],
                                                    COMPONENT_COST)

    # --- Mark existing traces as soft obstacles ---
    for seg in traces:
        if seg.net == exclude_net:
            continue
        grid.mark_segment(seg.start, seg.end, seg.layer,
                          seg.width_mm + clearance, trace_cost)

    # --- Mark existing vias as soft obstacles ---
    for v in vias:
        if v.net == exclude_net:
            continue
        half = v.size_mm / 2
        grid.mark_rect(
            Point(v.pos.x - half, v.pos.y - half),
            Point(v.pos.x + half, v.pos.y + half),
            Layer.FRONT, trace_cost)
        grid.mark_rect(
            Point(v.pos.x - half, v.pos.y - half),
            Point(v.pos.x + half, v.pos.y + half),
            Layer.BACK, trace_cost)

    return grid


def path_to_traces(path: list[GridCell], grid: RoutingGrid,
                   net_name: str, width: float,
                   via_drill: float = 0.3, via_size: float = 0.6
                   ) -> tuple[list[TraceSegment], list[Via]]:
    """Convert contiguous A* path to KiCad trace segments, merging collinear cells."""
    if len(path) < 2:
        return [], []

    segments: list[TraceSegment] = []
    vias: list[Via] = []
    seg_start = path[0]
    prev = path[0]

    for i in range(1, len(path)):
        curr = path[i]

        if curr.layer != prev.layer:
            if seg_start != prev:
                segments.append(TraceSegment(
                    grid.to_point(seg_start), grid.to_point(prev),
                    Layer(prev.layer), net_name, width))
            vias.append(Via(grid.to_point(prev), net_name, via_drill, via_size))
            seg_start = curr

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

    if seg_start != prev:
        segments.append(TraceSegment(
            grid.to_point(seg_start), grid.to_point(prev),
            Layer(prev.layer), net_name, width))

    return segments, vias
