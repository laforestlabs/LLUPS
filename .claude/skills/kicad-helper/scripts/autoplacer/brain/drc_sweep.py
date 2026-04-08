"""Post-route geometric DRC sweep for clearance violations.

Checks actual segment-to-segment distances between traces of different nets
on the same layer. Identifies shorts and near-misses that slip through
grid-based routing due to quantization.
"""
from __future__ import annotations
import math
from collections import defaultdict

from .types import Point, TraceSegment, Via


def _seg_to_seg_dist(a_start: Point, a_end: Point,
                     b_start: Point, b_end: Point) -> float:
    """Minimum distance between two finite line segments in 2D."""
    # Vector math for closest approach of two segments
    d1x, d1y = a_end.x - a_start.x, a_end.y - a_start.y
    d2x, d2y = b_end.x - b_start.x, b_end.y - b_start.y
    rx, ry = a_start.x - b_start.x, a_start.y - b_start.y

    a = d1x * d1x + d1y * d1y  # |d1|^2
    e = d2x * d2x + d2y * d2y  # |d2|^2
    f = d2x * rx + d2y * ry

    EPS = 1e-10

    if a <= EPS and e <= EPS:
        return math.hypot(rx, ry)

    if a <= EPS:
        t = max(0.0, min(1.0, f / e))
        return math.hypot(rx - t * d2x, ry - t * d2y)

    c = d1x * rx + d1y * ry
    if e <= EPS:
        s = max(0.0, min(1.0, -c / a))
        return math.hypot(rx + s * d1x, ry + s * d1y)

    b = d1x * d2x + d1y * d2y
    denom = a * e - b * b

    if denom > EPS:
        s = max(0.0, min(1.0, (b * f - c * e) / denom))
    else:
        s = 0.0

    t = (b * s + f) / e
    if t < 0.0:
        t = 0.0
        s = max(0.0, min(1.0, -c / a))
    elif t > 1.0:
        t = 1.0
        s = max(0.0, min(1.0, (b - c) / a))

    closest_a_x = a_start.x + s * d1x
    closest_a_y = a_start.y + s * d1y
    closest_b_x = b_start.x + t * d2x
    closest_b_y = b_start.y + t * d2y
    return math.hypot(closest_a_x - closest_b_x, closest_a_y - closest_b_y)


def _point_to_seg_dist(px: float, py: float,
                       sx: float, sy: float,
                       ex: float, ey: float) -> float:
    """Distance from point (px,py) to segment (sx,sy)-(ex,ey)."""
    dx, dy = ex - sx, ey - sy
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-12:
        return math.hypot(px - sx, py - sy)
    t = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / len_sq))
    return math.hypot(px - (sx + t * dx), py - (sy + t * dy))


def find_clearance_violations(traces: list[TraceSegment],
                              vias: list[Via],
                              clearance_mm: float = 0.2
                              ) -> list[tuple[str, str, float]]:
    """Find pairs of (net_a, net_b) that violate clearance.

    Returns list of (net_a, net_b, min_distance_mm) tuples where
    min_distance < clearance_mm.
    """
    # Group by layer for trace-trace checks
    by_layer: dict[int, list[TraceSegment]] = defaultdict(list)
    for seg in traces:
        by_layer[seg.layer].append(seg)

    violations: list[tuple[str, str, float]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for layer, segs in by_layer.items():
        n = len(segs)
        for i in range(n):
            a = segs[i]
            # Quick bounding box for early rejection
            a_min_x = min(a.start.x, a.end.x) - clearance_mm - a.width_mm / 2
            a_max_x = max(a.start.x, a.end.x) + clearance_mm + a.width_mm / 2
            a_min_y = min(a.start.y, a.end.y) - clearance_mm - a.width_mm / 2
            a_max_y = max(a.start.y, a.end.y) + clearance_mm + a.width_mm / 2

            for j in range(i + 1, n):
                b = segs[j]
                if a.net == b.net:
                    continue

                # Bounding box rejection
                b_min_x = min(b.start.x, b.end.x) - b.width_mm / 2
                b_max_x = max(b.start.x, b.end.x) + b.width_mm / 2
                b_min_y = min(b.start.y, b.end.y) - b.width_mm / 2
                b_max_y = max(b.start.y, b.end.y) + b.width_mm / 2

                if (a_min_x > b_max_x or a_max_x < b_min_x or
                        a_min_y > b_max_y or a_max_y < b_min_y):
                    continue

                # Actual segment-to-segment distance
                dist = _seg_to_seg_dist(a.start, a.end, b.start, b.end)
                # Subtract half-widths to get copper-edge-to-copper-edge distance
                edge_dist = dist - a.width_mm / 2 - b.width_mm / 2

                if edge_dist < clearance_mm:
                    pair = tuple(sorted([a.net, b.net]))
                    if pair not in seen_pairs:
                        seen_pairs.add(pair)
                        violations.append((a.net, b.net, edge_dist))

    # Via-to-trace checks
    for v in vias:
        for layer, segs in by_layer.items():
            for seg in segs:
                if seg.net == v.net:
                    continue
                dist = _point_to_seg_dist(
                    v.pos.x, v.pos.y,
                    seg.start.x, seg.start.y,
                    seg.end.x, seg.end.y)
                edge_dist = dist - v.size_mm / 2 - seg.width_mm / 2
                if edge_dist < clearance_mm:
                    pair = tuple(sorted([v.net, seg.net]))
                    if pair not in seen_pairs:
                        seen_pairs.add(pair)
                        violations.append((v.net, seg.net, edge_dist))

    # Via-to-via checks
    for i in range(len(vias)):
        for j in range(i + 1, len(vias)):
            va, vb = vias[i], vias[j]
            if va.net == vb.net:
                continue
            dist = va.pos.dist(vb.pos)
            edge_dist = dist - va.size_mm / 2 - vb.size_mm / 2
            if edge_dist < clearance_mm:
                pair = tuple(sorted([va.net, vb.net]))
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    violations.append((va.net, vb.net, edge_dist))

    return violations


def nudge_traces_apart(traces: list[TraceSegment],
                       vias: list[Via],
                       clearance_mm: float = 0.2
                       ) -> tuple[list[TraceSegment], int]:
    """Attempt to nudge traces apart where clearance is violated.

    For each violation, tries to shift the shorter trace segment
    perpendicular to itself by the clearance deficit.

    Returns (modified_traces, num_nudged).
    """
    # Group segments by net for quick lookup
    by_layer: dict[int, list[int]] = defaultdict(list)
    for idx, seg in enumerate(traces):
        by_layer[seg.layer].append(idx)

    nudged = 0
    nudge_delta = 0.05  # mm per nudge step

    for layer, indices in by_layer.items():
        for ii in range(len(indices)):
            i = indices[ii]
            a = traces[i]
            for jj in range(ii + 1, len(indices)):
                j = indices[jj]
                b = traces[j]
                if a.net == b.net:
                    continue

                dist = _seg_to_seg_dist(a.start, a.end, b.start, b.end)
                edge_dist = dist - a.width_mm / 2 - b.width_mm / 2

                if edge_dist >= clearance_mm:
                    continue

                deficit = clearance_mm - edge_dist + 0.01  # small extra margin

                # Nudge the shorter segment perpendicular to itself
                shorter = i if a.length <= b.length else j
                seg = traces[shorter]

                dx = seg.end.x - seg.start.x
                dy = seg.end.y - seg.start.y
                seg_len = math.hypot(dx, dy)
                if seg_len < 1e-6:
                    continue

                # Perpendicular unit vector
                nx, ny = -dy / seg_len, dx / seg_len

                # Try both perpendicular directions, pick the one that moves away
                # from the other segment
                other = traces[j if shorter == i else i]
                mid_x = (seg.start.x + seg.end.x) / 2
                mid_y = (seg.start.y + seg.end.y) / 2
                other_mid_x = (other.start.x + other.end.x) / 2
                other_mid_y = (other.start.y + other.end.y) / 2

                # Direction from other to this segment
                to_x = mid_x - other_mid_x
                to_y = mid_y - other_mid_y

                # Pick perpendicular direction that moves away from other
                if nx * to_x + ny * to_y < 0:
                    nx, ny = -nx, -ny

                shift_x = nx * deficit
                shift_y = ny * deficit

                traces[shorter] = TraceSegment(
                    start=Point(seg.start.x + shift_x, seg.start.y + shift_y),
                    end=Point(seg.end.x + shift_x, seg.end.y + shift_y),
                    layer=seg.layer,
                    net=seg.net,
                    width_mm=seg.width_mm,
                )
                nudged += 1

    return traces, nudged
