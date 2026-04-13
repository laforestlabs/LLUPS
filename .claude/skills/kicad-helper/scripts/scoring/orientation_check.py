"""Functional footprint orientation check.

Scores whether connectors, switches, test points, and other access-critical
components are oriented correctly for physical use — e.g., USB connectors
should face outward from a board edge, not inward.
"""
import math
import pcbnew
from .base import LayoutCheck, CheckResult, Issue


# Rules: ref prefix -> expected orientation relative to nearest board edge
# "edge_facing" means the component's pad-side should point toward the nearest edge
# "edge_aligned" means the component should be at the board edge (within threshold)
ORIENTATION_RULES = {
    "J": {  # Connectors
        "description": "Connector should face outward from nearest board edge",
        "max_edge_distance_mm": 5.0,
        "check_facing": True,
    },
    "SW": {  # Switches
        "description": "Switch should be accessible near board edge",
        "max_edge_distance_mm": 10.0,
        "check_facing": False,
    },
    "TP": {  # Test points
        "description": "Test point should be accessible",
        "max_edge_distance_mm": 15.0,
        "check_facing": False,
    },
}


class OrientationCheck(LayoutCheck):
    name = "orientation"
    display_name = "Footprint Orientation"
    weight = 0.0  # advisory for now

    def run(self, board, config: dict) -> CheckResult:
        # Board edges
        rect = board.GetBoardEdgesBoundingBox()
        bx1 = pcbnew.ToMM(rect.GetX())
        by1 = pcbnew.ToMM(rect.GetY())
        bx2 = bx1 + pcbnew.ToMM(rect.GetWidth())
        by2 = by1 + pcbnew.ToMM(rect.GetHeight())

        issues = []
        checked = 0
        passed = 0

        for fp in board.Footprints():
            ref = fp.GetReferenceAsString()

            # Find matching rule
            rule = None
            for prefix, r in ORIENTATION_RULES.items():
                if ref.startswith(prefix):
                    rule = r
                    break
            if not rule:
                continue

            checked += 1
            pos = fp.GetPosition()
            px = pcbnew.ToMM(pos.x)
            py = pcbnew.ToMM(pos.y)
            rot = fp.GetOrientationDegrees() % 360

            # Distance to each edge
            edges = {
                "left": px - bx1,
                "right": bx2 - px,
                "top": py - by1,
                "bottom": by2 - py,
            }
            nearest_edge = min(edges, key=edges.get)
            edge_dist = edges[nearest_edge]

            # Check edge distance
            max_dist = rule["max_edge_distance_mm"]
            edge_ok = edge_dist <= max_dist

            # Check facing direction using pad centroid vs body center
            facing_ok = True
            if rule.get("check_facing") and edge_ok:
                # Compute pad centroid relative to body center (courtyard bbox
                # center).  This handles connectors whose footprint origin is
                # at a corner pad rather than the geometric center.
                try:
                    cy_shape = fp.GetCourtyard(
                        pcbnew.F_CrtYd if fp.GetLayer() == pcbnew.F_Cu
                        else pcbnew.B_CrtYd)
                    cbox = cy_shape.BBox()
                    if cbox.GetWidth() > 0 and cbox.GetHeight() > 0:
                        cc = cbox.GetCenter()
                        bcx = pcbnew.ToMM(cc.x)
                        bcy = pcbnew.ToMM(cc.y)
                    else:
                        bcx, bcy = px, py
                except Exception:
                    bcx, bcy = px, py

                # Pad centroid in absolute coords (connected pads only)
                connected_pads = [
                    p for p in fp.Pads()
                    if p.GetNetname() and not p.GetNetname().startswith("unconnected-")
                ]
                if connected_pads:
                    avg_x = sum(pcbnew.ToMM(p.GetPosition().x) for p in connected_pads) / len(connected_pads)
                    avg_y = sum(pcbnew.ToMM(p.GetPosition().y) for p in connected_pads) / len(connected_pads)
                    offset_x = avg_x - bcx
                    offset_y = avg_y - bcy

                    # The pad centroid should point toward the board center
                    # (away from the nearest edge).
                    # desired direction: left->0°(right), right->180°(left),
                    #                    top->90°(down), bottom->270°(up)
                    desired_angle = {"left": 0, "right": 180, "top": 90, "bottom": 270}
                    desired = math.radians(desired_angle[nearest_edge])

                    centroid_mag = math.hypot(offset_x, offset_y)
                    if centroid_mag >= 0.3:
                        actual = math.atan2(offset_y, offset_x)
                        angle_err = abs(math.degrees(actual - desired)) % 360
                        if angle_err > 180:
                            angle_err = 360 - angle_err
                        facing_ok = angle_err <= 50  # generous tolerance

            if edge_ok and facing_ok:
                passed += 1
            else:
                severity = "error" if ref.startswith("J") else "warning"
                if not edge_ok:
                    issues.append(Issue(severity,
                        f"{ref} is {edge_dist:.1f}mm from nearest edge ({nearest_edge}), "
                        f"max {max_dist}mm — {rule['description']}",
                        {"ref": ref, "x": round(px, 1), "y": round(py, 1)}))
                elif not facing_ok:
                    issues.append(Issue(severity,
                        f"{ref} at {rot:.0f}° near {nearest_edge} edge — "
                        f"should face outward. {rule['description']}",
                        {"ref": ref, "rotation": rot, "nearest_edge": nearest_edge}))

        if checked == 0:
            return CheckResult(score=100, issues=[], metrics={},
                               summary="No orientation-critical components found")

        score = round(100 * passed / checked, 1)

        return CheckResult(
            score=score,
            issues=issues,
            metrics={
                "checked": checked,
                "passed": passed,
                "failed": checked - passed,
            },
            summary=f"{passed}/{checked} access-critical components correctly oriented",
        )
