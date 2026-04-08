from __future__ import annotations

import pathlib
import sys
import unittest

AUTOPLACER_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(AUTOPLACER_ROOT) not in sys.path:
    sys.path.insert(0, str(AUTOPLACER_ROOT))

from brain.grid_builder import RoutingGrid
from brain.router import AStarRouter, RoutingSolver
from brain.types import BoardState, GridCell, Layer, Net, Point, TraceSegment


class RouterGridBehaviorTests(unittest.TestCase):
    def test_find_path_respects_width_cells_in_corridor(self):
        grid = RoutingGrid((Point(0.0, 0.0), Point(10.0, 10.0)), resolution_mm=1.0)
        router = AStarRouter(grid)
        start = GridCell(1, 1, Layer.FRONT)
        end = GridCell(8, 1, Layer.FRONT)

        # Baseline should allow a simple horizontal route for width 1.
        path_thin = router.find_path(start, end, width_cells=1, max_search=5000)
        self.assertIsNotNone(path_thin)

        # Block rows above and below the corridor so only a 1-cell corridor remains.
        for x in range(0, grid.cols):
            grid.set_cost(x, 0, Layer.FRONT, 1e6)
            grid.set_cost(x, 2, Layer.FRONT, 1e6)

        # width=1 should still pass through center row.
        path_width1 = router.find_path(start, end, width_cells=1, max_search=5000)
        self.assertIsNotNone(path_width1)

        # width=2 should fail once width-aware occupancy checks are implemented.
        path_width2 = router.find_path(start, end, width_cells=2, max_search=5000)
        self.assertIsNone(path_width2)

    def test_unmark_segment_clears_soft_obstacle(self):
        grid = RoutingGrid((Point(0.0, 0.0), Point(10.0, 10.0)), resolution_mm=1.0)
        seg = TraceSegment(
            start=Point(2.0, 2.0),
            end=Point(6.0, 2.0),
            layer=Layer.FRONT,
            net="N1",
            width_mm=1.0,
        )
        grid.mark_segment(seg.start, seg.end, seg.layer, seg.width_mm, 100.0)

        probe_idx = grid._idx(2, 4)
        self.assertGreater(grid.cost[Layer.FRONT][probe_idx], 0.0)

        grid.unmark_segment(seg, seg.width_mm)

        self.assertEqual(grid.cost[Layer.FRONT][probe_idx], 0.0)
        # Unrelated cell remains unchanged.
        far_idx = grid._idx(9, 9)
        self.assertEqual(grid.cost[Layer.FRONT][far_idx], 0.0)

    def test_prioritize_nets_uses_priority_then_padcount(self):
        state = BoardState()
        state.nets["LOW"] = Net(name="LOW", pad_refs=[("U1", "1"), ("U2", "1")], priority=1, is_power=False)
        state.nets["HIGH"] = Net(name="HIGH", pad_refs=[("U1", "2"), ("U2", "2")], priority=7, is_power=False)
        state.nets["POWER"] = Net(name="POWER", pad_refs=[("U3", "1"), ("U4", "1")], priority=0, is_power=True)
        state.nets["WIDE"] = Net(
            name="WIDE",
            pad_refs=[("U5", "1"), ("U6", "1"), ("U7", "1")],
            priority=7,
            is_power=False,
        )

        solver = RoutingSolver(state, config={"skip_gnd_routing": False})
        ordered = solver._prioritize_nets()
        ordered_names = [n.name for n in ordered]

        # Power should come first; then higher-priority signals, then pad-count tiebreak.
        self.assertEqual(ordered_names[0], "POWER")
        self.assertLess(ordered_names.index("HIGH"), ordered_names.index("LOW"))
        self.assertLess(ordered_names.index("HIGH"), ordered_names.index("WIDE"))


if __name__ == "__main__":
    unittest.main()
