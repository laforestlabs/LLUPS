"""Rip-up and Re-route (RRR) conflict resolver.

When A* fails on first pass, this module iteratively rips victim traces
and re-routes to resolve conflicts. All computation local.
"""
from __future__ import annotations
import math
import time
from collections import defaultdict

from .types import (
    Point, Layer, BoardState, Net, TraceSegment, Via, GridCell, RoutingResult
)
from .router import RoutingGrid, AStarRouter
from .grid_builder import build_grid, path_to_traces
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
        self.timeout_s = self.cfg.get("rrr_timeout_s", 60)
        self.resolution = self.cfg.get("grid_resolution_mm", 0.5)
        self.clearance = self.cfg.get("clearance_mm", 0.2)
        self.trace_cost = self.cfg.get("existing_trace_cost", 100.0)
        self.via_drill = self.cfg.get("via_drill_mm", 0.3)
        self.via_size = self.cfg.get("via_size_mm", 0.6)

    def solve(self, initial_traces: list[TraceSegment],
              initial_vias: list[Via],
              failed_nets: list[str]) -> tuple[list[TraceSegment], list[Via], list[str]]:
        """Rip-up and re-route to resolve failed nets.

        Returns (traces, vias, still_failed_nets).
        """
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

        t_start = time.monotonic()

        for iteration in range(self.max_iterations):
            if not queue:
                break

            # Wall-clock timeout
            if time.monotonic() - t_start > self.timeout_s:
                print(f"  RRR timed out after {self.timeout_s}s")
                break

            net_name = queue.pop(0)
            net = self.state.nets.get(net_name)
            if not net:
                continue

            # Build grid excluding this net's traces
            grid = build_grid(
                self.state, self.resolution, self.clearance,
                traces=[t for segs in net_traces.values() for t in segs],
                vias=[v for vs in net_vias.values() for v in vs],
                exclude_net=net_name,
                trace_cost=self.trace_cost)
            router = AStarRouter(grid)
            result = self._try_route(router, grid, net)

            if result.success:
                net_traces[net_name] = result.segments
                net_vias[net_name] = result.vias
                continue

            # Find victims to rip (rip-count-aware)
            victims = self._find_victims(net, net_traces, rip_counts)
            ripped_any = False

            for victim_name in victims:
                if rip_counts[victim_name] >= self.max_rips_per_net:
                    continue
                rip_counts[victim_name] += 1
                del net_traces[victim_name]
                net_vias.pop(victim_name, None)
                queue.append(victim_name)
                ripped_any = True

            if ripped_any:
                # Retry blocked net with victims removed
                grid = build_grid(
                    self.state, self.resolution, self.clearance,
                    traces=[t for segs in net_traces.values() for t in segs],
                    vias=[v for vs in net_vias.values() for v in vs],
                    exclude_net=net_name,
                    trace_cost=self.trace_cost)
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
        width_cells = max(1, math.ceil(width / self.resolution))
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

            segs, pvias = path_to_traces(
                path, grid, net.name, width, self.via_drill, self.via_size)
            segments.extend(segs)
            vias.extend(pvias)

            # Mark this edge so subsequent MST edges see it
            for seg in segs:
                grid.mark_segment(seg.start, seg.end, seg.layer,
                                  seg.width_mm + self.clearance,
                                  self.trace_cost)

        return RoutingResult(segments=segments, vias=vias,
                             cost=sum(s.length for s in segments),
                             success=all_ok)

    def _find_victims(self, blocked_net: Net,
                      net_traces: dict[str, list[TraceSegment]],
                      rip_counts: dict[str, int]) -> list[str]:
        """Score which nets to rip.

        Prefer short, low-priority nets that haven't been ripped many times.
        """
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
                n_rips = rip_counts.get(net_name, 0) + 1  # +1 so never divide by 0
                # Score: short, low-priority, low-rip-count nets are preferred
                score = (1.0 / (total_len + 1) *
                        1.0 / (priority + 1) *
                        1.0 / n_rips)
                candidates.append((score, net_name))

        candidates.sort(reverse=True)
        return [name for _, name in candidates[:2]]
