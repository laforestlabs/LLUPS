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

            # Check facing direction (rotation should point toward nearest edge)
            facing_ok = True
            if rule.get("check_facing") and edge_ok:
                # Expected rotation to face the nearest edge:
                # left edge -> 270° (pointing left)
                # right edge -> 90° (pointing right)
                # top edge -> 0° (pointing up)
                # bottom edge -> 180° (pointing down)
                expected_rots = {
                    "left": [270],
                    "right": [90],
                    "top": [0, 360],
                    "bottom": [180],
                }
                expected = expected_rots[nearest_edge]
                # Allow ±15° tolerance
                facing_ok = any(abs(rot - e) <= 15 or abs(rot - e - 360) <= 15
                                or abs(rot - e + 360) <= 15 for e in expected)

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
