"""Rip-up and Re-route (RRR) conflict resolver.

When A* fails on first pass, this module iteratively rips victim traces
and re-routes to resolve conflicts. All computation local.
"""
from __future__ import annotations
import math
from collections import defaultdict

from .types import (
    Point, Layer, BoardState, Net, TraceSegment, Via, RoutingResult
)
from .router import RoutingGrid, AStarRouter, RoutingSolver
from .graph import minimum_spanning_tree


class RipUpRerouter:
    """Iterative rip-up and re-route engine."""

    def __init__(self, state: BoardState, config: dict = None,
                 max_iterations: int = 50):
        self.state = state
        self.cfg = config or {}
        self.max_iterations = max_iterations
        self.max_rips_per_net = self.cfg.get("max_rips_per_net", 5)
        self.stagnation_limit = self.cfg.get("rip_stagnation_limit", 5)
        self.resolution = self.cfg.get("grid_resolution_mm", 0.25)
        self.clearance = self.cfg.get("clearance_mm", 0.2)
        self.trace_cost = self.cfg.get("existing_trace_cost", 10.0)
        self.via_drill = self.cfg.get("via_drill_mm", 0.3)
        self.via_size = self.cfg.get("via_size_mm", 0.6)

    def solve(self, initial_traces: list[TraceSegment],
              initial_vias: list[Via],
              failed_nets: list[str]) -> tuple[list[TraceSegment], list[Via], list[str]]:
        """Rip-up and re-route to resolve failed nets.

        Returns (traces, vias, still_failed_nets).
        """
        # Group traces/vias by net
        net_traces: dict[str, list[TraceSegment]] = defaultdict(list)
        net_vias: dict[str, list[Via]] = defaultdict(list)
        for t in initial_traces:
            net_traces[t.net].append(t)
        for v in initial_vias:
            net_vias[v.net].append(v)

        queue = list(failed_nets)
        rip_counts: dict[str, int] = defaultdict(int)
        best_failed = len(queue)
        stagnant = 0

        for iteration in range(self.max_iterations):
            if not queue:
                break

            net_name = queue.pop(0)
            net = self.state.nets.get(net_name)
            if not net:
                continue

            # Rebuild grid excluding this net's traces
            grid = self._build_grid(net_traces, net_vias, exclude=net_name)
            router = AStarRouter(grid)
            result = self._try_route(router, grid, net)

            if result.success:
                net_traces[net_name] = result.segments
                net_vias[net_name] = result.vias
                # Mark on grid
                for seg in result.segments:
                    grid.mark_segment(seg.start, seg.end, seg.layer,
                                      seg.width_mm + self.clearance,
                                      self.trace_cost)
                continue

            # Find victims to rip
            victims = self._find_victims(net, net_traces)
            ripped_any = False

            for victim_name in victims:
                if rip_counts[victim_name] >= self.max_rips_per_net:
                    continue
                rip_counts[victim_name] += 1
                # Remove victim traces
                del net_traces[victim_name]
                net_vias.pop(victim_name, None)
                queue.append(victim_name)
                ripped_any = True

            if ripped_any:
                # Retry blocked net with victims removed
                grid = self._build_grid(net_traces, net_vias, exclude=net_name)
                router = AStarRouter(grid)
                result = self._try_route(router, grid, net)
                if result.success:
                    net_traces[net_name] = result.segments
                    net_vias[net_name] = result.vias
                else:
                    queue.append(net_name)
            else:
                queue.append(net_name)

            # Stagnation check
            current_failed = len(queue)
            if current_failed < best_failed:
                best_failed = current_failed
                stagnant = 0
            else:
                stagnant += 1
                if stagnant >= self.stagnation_limit:
                    print(f"  RRR stagnated after {iteration+1} iterations")
                    break

        # Flatten results
        all_traces = [t for segs in net_traces.values() for t in segs]
        all_vias = [v for vs in net_vias.values() for v in vs]
        still_failed = list(set(queue))

        print(f"  RRR complete: {len(still_failed)} nets still failed "
              f"(was {len(failed_nets)})")
        return all_traces, all_vias, still_failed

    def _build_grid(self, net_traces: dict[str, list[TraceSegment]],
                    net_vias: dict[str, list[Via]],
                    exclude: str = "") -> RoutingGrid:
        """Build grid with component obstacles and existing traces (excluding one net)."""
        grid = RoutingGrid(self.state.board_outline, self.resolution)

        # Build pad + escape corridor sets (same logic as RoutingSolver)
        pad_cells: set[tuple[int, int, int]] = set()
        escape_cells: set[tuple[int, int, int]] = set()

        for comp in self.state.components.values():
            comp_tl, comp_br = comp.bbox()
            for pad in comp.pads:
                pc = grid.to_cell(pad.pos, pad.layer)
                for dc in range(-1, 2):
                    for dr in range(-1, 2):
                        pad_cells.add((pc.x + dc, pc.y + dr, pad.layer))
                # Escape to nearest edge
                dx_l = pad.pos.x - comp_tl.x
                dx_r = comp_br.x - pad.pos.x
                dy_t = pad.pos.y - comp_tl.y
                dy_b = comp_br.y - pad.pos.y
                min_d = min(dx_l, dx_r, dy_t, dy_b)
                if min_d == dx_l:
                    ce = grid.to_cell(Point(comp_tl.x - self.clearance * 2, pad.pos.y), pad.layer)
                    for c in range(ce.x, pc.x + 1):
                        for dr in range(-1, 2):
                            escape_cells.add((c, pc.y + dr, pad.layer))
                elif min_d == dx_r:
                    ce = grid.to_cell(Point(comp_br.x + self.clearance * 2, pad.pos.y), pad.layer)
                    for c in range(pc.x, ce.x + 1):
                        for dr in range(-1, 2):
                            escape_cells.add((c, pc.y + dr, pad.layer))
                elif min_d == dy_t:
                    ce = grid.to_cell(Point(pad.pos.x, comp_tl.y - self.clearance * 2), pad.layer)
                    for r in range(ce.y, pc.y + 1):
                        for dc in range(-1, 2):
                            escape_cells.add((pc.x + dc, r, pad.layer))
                else:
                    ce = grid.to_cell(Point(pad.pos.x, comp_br.y + self.clearance * 2), pad.layer)
                    for r in range(pc.y, ce.y + 1):
                        for dc in range(-1, 2):
                            escape_cells.add((pc.x + dc, r, pad.layer))

        COMPONENT_COST = 100.0
        for comp in self.state.components.values():
            tl, br = comp.bbox(self.clearance)
            c1 = max(0, int((tl.x - grid.origin.x) / grid.resolution) - 1)
            r1 = max(0, int((tl.y - grid.origin.y) / grid.resolution) - 1)
            c2 = min(grid.cols - 1, int((br.x - grid.origin.x) / grid.resolution) + 1)
            r2 = min(grid.rows - 1, int((br.y - grid.origin.y) / grid.resolution) + 1)
            for layer in range(2):
                for r in range(r1, r2 + 1):
                    for c in range(c1, c2 + 1):
                        if (c, r, layer) in pad_cells or (c, r, layer) in escape_cells:
                            continue
                        idx = grid._idx(r, c)
                        grid.cost[layer][idx] = max(grid.cost[layer][idx], COMPONENT_COST)

        # Existing traces as soft obstacles (except excluded net)
        for net_name, segs in net_traces.items():
            if net_name == exclude:
                continue
            for seg in segs:
                grid.mark_segment(seg.start, seg.end, seg.layer,
                                  seg.width_mm + self.clearance, self.trace_cost)

        for net_name, vs in net_vias.items():
            if net_name == exclude:
                continue
            for v in vs:
                for layer in range(2):
                    grid.mark_rect(
                        Point(v.pos.x - v.size_mm / 2, v.pos.y - v.size_mm / 2),
                        Point(v.pos.x + v.size_mm / 2, v.pos.y + v.size_mm / 2),
                        layer, self.trace_cost)

        return grid

    def _try_route(self, router: AStarRouter, grid: RoutingGrid,
                   net: Net) -> RoutingResult:
        """Try to route a net."""
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

        names = [str(i) for i in range(len(pad_points))]
        pos_map = {names[i]: pad_points[i][0] for i in range(len(pad_points))}
        mst = minimum_spanning_tree(
            names, lambda a, b: pos_map[a].dist(pos_map[b])
        )

        width = net.width_mm
        width_cells = max(1, int(width / self.resolution))
        segments, vias = [], []
        all_ok = True

        for a_name, b_name, _ in mst:
            a_idx, b_idx = int(a_name), int(b_name)
            a_pos, a_layer = pad_points[a_idx]
            b_pos, b_layer = pad_points[b_idx]

            start = grid.to_cell(a_pos, a_layer)
            end = grid.to_cell(b_pos, b_layer)
            path = router.find_path(start, end, width_cells)

            if path is None:
                for try_layer in [Layer.FRONT, Layer.BACK]:
                    alt_s = GridCell(start.x, start.y, try_layer)
                    alt_e = GridCell(end.x, end.y, try_layer)
                    path = router.find_path(alt_s, alt_e, width_cells)
                    if path:
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

            segs, pvias = self._path_to_traces(path, grid, net.name, width)
            segments.extend(segs)
            vias.extend(pvias)

        return RoutingResult(segments=segments, vias=vias,
                             cost=sum(s.length for s in segments),
                             success=all_ok)

    def _find_victims(self, blocked_net: Net,
                      net_traces: dict[str, list[TraceSegment]]) -> list[str]:
        """Score which nets to rip. Prefer short, low-priority, rarely-ripped."""
        # Get bounding box of blocked net's pads
        pad_xs, pad_ys = [], []
        for ref, pad_id in blocked_net.pad_refs:
            comp = self.state.components.get(ref)
            if comp:
                for p in comp.pads:
                    if p.pad_id == pad_id:
                        pad_xs.append(p.pos.x)
                        pad_ys.append(p.pos.y)

        if not pad_xs:
            return []

        margin = 5.0
        bbox_min = Point(min(pad_xs) - margin, min(pad_ys) - margin)
        bbox_max = Point(max(pad_xs) + margin, max(pad_ys) + margin)

        candidates: list[tuple[float, str]] = []
        for net_name, segs in net_traces.items():
            if net_name == blocked_net.name:
                continue
            # Check if any segment is in the bounding box
            in_box = False
            total_len = 0.0
            for seg in segs:
                total_len += seg.length
                if (min(seg.start.x, seg.end.x) < bbox_max.x and
                    max(seg.start.x, seg.end.x) > bbox_min.x and
                    min(seg.start.y, seg.end.y) < bbox_max.y and
                    max(seg.start.y, seg.end.y) > bbox_min.y):
                    in_box = True

            if in_box and total_len > 0:
                net_obj = self.state.nets.get(net_name)
                priority = net_obj.priority if net_obj else 0
                # Score: prefer short, low-priority
                score = 1.0 / (total_len + 1) * 1.0 / (priority + 1)
                candidates.append((score, net_name))

        candidates.sort(reverse=True)
        return [name for _, name in candidates[:2]]

    def _path_to_traces(self, path, grid, net_name, width):
        """Same as RoutingSolver._path_to_traces."""
        if len(path) < 2:
            return [], []

        segments, vias = [], []
        seg_start = path[0]
        prev = path[0]

        for i in range(1, len(path)):
            curr = path[i]
            if curr.layer != prev.layer:
                if seg_start != prev:
                    segments.append(TraceSegment(
                        grid.to_point(seg_start), grid.to_point(prev),
                        Layer(prev.layer), net_name, width))
                vias.append(Via(grid.to_point(prev), net_name,
                                self.via_drill, self.via_size))
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


# Need GridCell import for _try_route layer fallback
from .types import GridCell
